#!/usr/bin/env python3
import os
import time
import requests
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.layout import Layout

# ---- Config ----
GRAFANA = os.getenv("GRAFANA_URL", "http://localhost:3000")
DS_PROM = int(os.getenv("DS_PROM_ID", "1"))
REFRESH = float(os.getenv("REFRESH", "2.0"))
META_REFRESH = float(os.getenv("META_REFRESH", "30.0"))  # refresh metric-name cache

# These will be empty until kube exporters + scrape/remote_write are wired.
PANELS: Dict[str, Tuple[str, Optional[str]]] = {
    "CPU top pods": (
        'topk(10, rate(container_cpu_usage_seconds_total[5m]))',
        'topk(10, go_goroutines)',
    ),
    "Mem top pods": (
        'topk(10, container_memory_working_set_bytes)',
        'topk(10, process_resident_memory_bytes)',
    ),
    "Restarts (5m)": (
        'topk(10, increase(kube_pod_container_status_restarts_total[5m]))',
        'topk(10, rate(promhttp_metric_handler_requests_total[5m]))',
    ),
}

console = Console()

def _get(path: str, params=None, timeout=6):
    r = requests.get(f"{GRAFANA}{path}", params=params, timeout=timeout)
    return r

def grafana_health() -> Tuple[bool, str]:
    try:
        r = _get("/api/health", timeout=3)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        j = r.json()
        return True, f"v{j.get('version','?')} db={j.get('database','?')}"
    except Exception as e:
        return False, str(e)

def prom_api(path: str, params=None, timeout=6):
    # DS url already includes /prometheus, so we only call /api/v1/...
    r = _get(f"/api/datasources/proxy/{DS_PROM}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def prom_query(q: str) -> List[dict]:
    j = prom_api("/api/v1/query", params={"query": q}, timeout=6)
    # On success, Prom returns {status:"success", data:{result:[...]}}
    return j.get("data", {}).get("result", []) or []

def prom_buildinfo() -> Tuple[bool, str]:
    try:
        j = prom_api("/api/v1/status/buildinfo", timeout=4)
        if j.get("status") != "success":
            return False, "not success"
        data = j.get("data", {})
        # Keys differ a bit between impls; keep it generic
        ver = data.get("version") or data.get("revision") or "ok"
        return True, str(ver)
    except Exception as e:
        return False, str(e)

def prom_metric_names() -> List[str]:
    j = prom_api("/api/v1/label/__name__/values", timeout=10)
    return j.get("data", []) or []

def render_result_table(title: str, query: str, result: List[dict]) -> Table:
    t = Table(title=f"{title} | {query}", show_lines=False)
    t.add_column("labels", overflow="fold")
    t.add_column("value", justify="right")

    if not result:
        t.add_row("(no data)", "")
        return t

    for row in result[:10]:
        metric = row.get("metric", {}) or {}
        # Keep labels compact: show most relevant ones first if present
        preferred = ["namespace", "pod", "container", "job", "instance"]
        items = []
        for k in preferred:
            if k in metric:
                items.append((k, metric[k]))
        for k, v in metric.items():
            if k not in preferred:
                items.append((k, v))
        labels = ", ".join([f'{k}="{v}"' for k, v in items]) or "(no labels)"
        val = row.get("value", ["", ""])[1]
        t.add_row(labels, str(val))
    return t

@dataclass
class MetaState:
    last_meta: float = 0.0
    metric_names: List[str] = None

def build_layout(banner: Panel, tables: List[Table]) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(banner, size=5),
        Layout(name="body"),
    )
    body = layout["body"]
    # Stack tables vertically
    body.split_column(*[Layout(t, ratio=1) for t in tables])
    return layout

def main():
    meta = MetaState(last_meta=0.0, metric_names=[])
    last_err: Optional[str] = None

    with Live(console=console, refresh_per_second=8, screen=True) as live:
        while True:
            now = time.time()

            # Refresh metric-name cache occasionally
            if now - meta.last_meta > META_REFRESH:
                try:
                    meta.metric_names = prom_metric_names()
                    meta.last_meta = now
                    last_err = None
                except Exception as e:
                    last_err = f"metric name cache failed: {e}"

            g_ok, g_msg = grafana_health()
            p_ok, p_msg = prom_buildinfo()

            metric_count = len(meta.metric_names or [])

            header = Text()
            header.append("observtop ", style="bold")
            header.append(f"refresh={REFRESH}s  ")
            header.append(" | ")

            header.append("Grafana=", style="bold")
            header.append("OK " if g_ok else "FAIL ", style="green" if g_ok else "red")
            header.append(f"({g_msg})  ")

            header.append("Mimir API=", style="bold")
            header.append("OK " if p_ok else "FAIL ", style="green" if p_ok else "red")
            header.append(f"({p_msg})  ")

            header.append("series=", style="bold")
            header.append(str(metric_count), style="cyan")

            if last_err:
                header.append("  |  ", style="dim")
                header.append(last_err, style="yellow")

            banner = Panel(header, title="Status", border_style="blue")

            tables: List[Table] = []

            # If no series exist, don’t waste cycles; show a single helpful panel
            if metric_count == 0:
                t = Table(title="No metrics ingested yet", show_lines=False)
                t.add_column("hint", overflow="fold")
                t.add_row(
                    "Mimir answers API requests, but contains zero time series.\n"
                    "Once a collector (Prometheus / Grafana Agent / Alloy) remote_writes into Mimir, these panels will populate.\n"
                    "Tooling is fine; data plane isn’t wired yet."
                )
                tables.append(t)
            else:
                # Normal mode: run panel queries with fallbacks
                for title, (primary, fallback) in PANELS.items():
                    res = []
                    used = primary
                    try:
                        res = prom_query(primary)
                        if not res and fallback:
                            res = prom_query(fallback)
                            used = fallback
                    except Exception as e:
                        # Show error as a table
                        err_t = Table(title=f"{title} | ERROR", show_lines=False)
                        err_t.add_column("error", overflow="fold")
                        err_t.add_row(str(e))
                        tables.append(err_t)
                        continue

                    tables.append(render_result_table(title, used, res))

            live.update(build_layout(banner, tables))
            time.sleep(REFRESH)

if __name__ == "__main__":
    main()
