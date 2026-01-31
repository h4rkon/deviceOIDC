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

# -----------------------------------------------------------------------------
# Config (env overrides)
# -----------------------------------------------------------------------------
GRAFANA = os.getenv("GRAFANA_URL", "http://localhost:3000")

# Grafana datasource ids (from /api/datasources)
DS_PROM = int(os.getenv("DS_PROM_ID", "1"))   # Mimir/Prometheus
DS_LOKI = int(os.getenv("DS_LOKI_ID", "2"))   # Loki

REFRESH = float(os.getenv("REFRESH", "2.0"))
META_REFRESH = float(os.getenv("META_REFRESH", "30.0"))  # refresh metric-name cache

# Loki tail settings
# Use labels that exist in your Loki: app/namespace/pod/... (NOT job)
LOKI_QUERY = os.getenv("LOKI_QUERY", '{app=~".+"}')
LOKI_LIMIT = int(os.getenv("LOKI_LIMIT", "30"))
LOKI_WINDOW_SEC = int(os.getenv("LOKI_WINDOW_SEC", "600"))  # last N seconds

# Prom panels (will show empty until metrics ingestion is wired)
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

# -----------------------------------------------------------------------------
# HTTP helpers
# -----------------------------------------------------------------------------
def _get(path: str, params=None, timeout=6) -> requests.Response:
    return requests.get(f"{GRAFANA}{path}", params=params, timeout=timeout)

def grafana_health() -> Tuple[bool, str]:
    try:
        r = _get("/api/health", timeout=3)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        j = r.json()
        return True, f"v{j.get('version','?')} db={j.get('database','?')}"
    except Exception as e:
        return False, str(e)

# -----------------------------------------------------------------------------
# Prometheus/Mimir via Grafana datasource proxy
# Note: datasource URL is ...:9009/prometheus, so we call only /api/v1/...
# -----------------------------------------------------------------------------
def prom_api(path: str, params=None, timeout=6) -> dict:
    r = _get(f"/api/datasources/proxy/{DS_PROM}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def prom_query(q: str) -> List[dict]:
    j = prom_api("/api/v1/query", params={"query": q}, timeout=6)
    return j.get("data", {}).get("result", []) or []

def prom_buildinfo() -> Tuple[bool, str]:
    try:
        j = prom_api("/api/v1/status/buildinfo", timeout=4)
        if j.get("status") != "success":
            return False, "not success"
        data = j.get("data", {}) or {}
        ver = data.get("version") or data.get("revision") or "ok"
        return True, str(ver)
    except Exception as e:
        return False, str(e)

def prom_metric_names() -> List[str]:
    j = prom_api("/api/v1/label/__name__/values", timeout=10)
    return j.get("data", []) or []

# -----------------------------------------------------------------------------
# Loki via Grafana datasource proxy
# -----------------------------------------------------------------------------
def loki_api(path: str, params=None, timeout=8) -> dict:
    r = _get(f"/api/datasources/proxy/{DS_LOKI}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def loki_buildinfo() -> Tuple[bool, str]:
    # Loki has /loki/api/v1/status/buildinfo
    try:
        j = loki_api("/loki/api/v1/status/buildinfo", timeout=5)
        if j.get("status") != "success":
            return False, "not success"
        data = j.get("data", {}) or {}
        ver = data.get("version") or data.get("revision") or "ok"
        return True, str(ver)
    except Exception as e:
        return False, str(e)

def loki_tail(query: str, limit: int, window_sec: int) -> List[dict]:
    end_ns = int(time.time() * 1e9)
    start_ns = int((time.time() - window_sec) * 1e9)
    j = loki_api(
        "/loki/api/v1/query_range",
        params={
            "query": query,
            "limit": limit,
            "direction": "BACKWARD",
            "start": start_ns,
            "end": end_ns,
        },
        timeout=10,
    )
    return j.get("data", {}).get("result", []) or []

# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------
def render_prom_table(title: str, query: str, result: List[dict]) -> Table:
    t = Table(title=f"{title} | {query}", show_lines=False)
    t.add_column("labels", overflow="fold")
    t.add_column("value", justify="right")

    if not result:
        t.add_row("(no data)", "")
        return t

    for row in result[:10]:
        metric = row.get("metric", {}) or {}
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

def render_loki_table(query: str, streams: List[dict], limit: int) -> Table:
    t = Table(title=f"Loki tail | {query}", show_lines=False)
    t.add_column("ts", width=12)
    t.add_column("line", overflow="fold")

    lines: List[Tuple[int, str]] = []
    for s in streams:
        for ts, line in s.get("values", []):
            lines.append((int(ts), line))

    lines.sort(key=lambda x: x[0], reverse=True)

    if not lines:
        t.add_row("-", "(no logs in window)")
        return t

    for ts, line in lines[:limit]:
        t.add_row(str(ts // 1_000_000_000), line.rstrip())
    return t

@dataclass
class MetaState:
    last_meta: float = 0.0
    metric_names: List[str] = None

def build_layout(banner: Panel, tables: List[Table]) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(banner, size=6),
        Layout(name="body"),
    )
    body = layout["body"]
    body.split_column(*[Layout(t, ratio=1) for t in tables])
    return layout

# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------
def main():
    meta = MetaState(last_meta=0.0, metric_names=[])
    last_err: Optional[str] = None

    with Live(console=console, refresh_per_second=10, screen=True) as live:
        while True:
            now = time.time()

            # Refresh metric-name cache occasionally (cheap "are we ingesting?" signal)
            if now - meta.last_meta > META_REFRESH:
                try:
                    meta.metric_names = prom_metric_names()
                    meta.last_meta = now
                    last_err = None
                except Exception as e:
                    last_err = f"metric cache failed: {e}"

            g_ok, g_msg = grafana_health()
            p_ok, p_msg = prom_buildinfo()
            l_ok, l_msg = loki_buildinfo()

            metric_count = len(meta.metric_names or [])

            header = Text()
            header.append("tui.py ", style="bold")
            header.append(f"refresh={REFRESH}s  ", style="dim")
            header.append("| ")

            header.append("Grafana=", style="bold")
            header.append("OK " if g_ok else "FAIL ", style="green" if g_ok else "red")
            header.append(f"({g_msg})  ")

            header.append("Mimir=", style="bold")
            header.append("OK " if p_ok else "FAIL ", style="green" if p_ok else "red")
            header.append(f"({p_msg})  ")

            header.append("Loki=", style="bold")
            header.append("OK " if l_ok else "FAIL ", style="green" if l_ok else "red")
            header.append(f"({l_msg})  ")

            header.append("series=", style="bold")
            header.append(str(metric_count), style="cyan")

            header.append("  ")
            header.append("logs_window=", style="bold")
            header.append(f"{LOKI_WINDOW_SEC}s", style="cyan")

            if last_err:
                header.append("\n")
                header.append(last_err, style="yellow")

            banner = Panel(header, title="Status", border_style="blue")

            tables: List[Table] = []

            # Prom block: if no series exist, show a single informative panel
            if metric_count == 0:
                t = Table(title="Prometheus/Mimir: no metrics ingested yet", show_lines=False)
                t.add_column("hint", overflow="fold")
                t.add_row(
                    "Mimir answers API requests but contains zero time series right now.\n"
                    "Once your collector (Prometheus / Grafana Agent / Alloy / otel-collector) ships metrics into Mimir, "
                    "the Prom panels will populate.\n"
                    "Tooling is fine; ingestion is the missing wire."
                )
                tables.append(t)
            else:
                for title, (primary, fallback) in PANELS.items():
                    used = primary
                    try:
                        res = prom_query(primary)
                        if not res and fallback:
                            res = prom_query(fallback)
                            used = fallback
                        tables.append(render_prom_table(title, used, res))
                    except Exception as e:
                        err_t = Table(title=f"{title} | ERROR", show_lines=False)
                        err_t.add_column("error", overflow="fold")
                        err_t.add_row(str(e))
                        tables.append(err_t)

            # Loki tail block (independent of Prom)
            try:
                streams = loki_tail(LOKI_QUERY, LOKI_LIMIT, LOKI_WINDOW_SEC)
                tables.append(render_loki_table(LOKI_QUERY, streams, LOKI_LIMIT))
            except Exception as e:
                err_t = Table(title="Loki tail | ERROR", show_lines=False)
                err_t.add_column("error", overflow="fold")
                err_t.add_row(str(e))
                tables.append(err_t)

            live.update(build_layout(banner, tables))
            time.sleep(REFRESH)

if __name__ == "__main__":
    main()
