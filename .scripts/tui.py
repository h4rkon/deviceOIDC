#!/usr/bin/env python3
import os
import time
import requests
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.layout import Layout

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
GRAFANA = os.getenv("GRAFANA_URL", "http://localhost:3000")

DS_PROM = int(os.getenv("DS_PROM_ID", "1"))   # Mimir
DS_LOKI = int(os.getenv("DS_LOKI_ID", "2"))   # Loki

REFRESH = float(os.getenv("REFRESH", "2.0"))
META_REFRESH = float(os.getenv("META_REFRESH", "30.0"))

LOKI_QUERY = os.getenv("LOKI_QUERY", '{app=~".+"}')
LOKI_LIMIT = int(os.getenv("LOKI_LIMIT", "30"))
LOKI_WINDOW_SEC = int(os.getenv("LOKI_WINDOW_SEC", "600"))

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
def _get(path: str, params=None, timeout=6):
    return requests.get(f"{GRAFANA}{path}", params=params, timeout=timeout)

def grafana_health():
    try:
        r = _get("/api/health", timeout=3)
        j = r.json()
        return True, f"v{j.get('version')} db={j.get('database')}"
    except Exception as e:
        return False, str(e)

# -----------------------------------------------------------------------------
# Prometheus / Mimir
# -----------------------------------------------------------------------------
def prom_api(path: str, params=None, timeout=6):
    r = _get(f"/api/datasources/proxy/{DS_PROM}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def prom_query(q: str):
    j = prom_api("/api/v1/query", params={"query": q})
    return j.get("data", {}).get("result", []) or []

def prom_buildinfo():
    try:
        j = prom_api("/api/v1/status/buildinfo")
        return True, j.get("data", {}).get("version", "ok")
    except Exception as e:
        return False, str(e)

def prom_metric_names():
    j = prom_api("/api/v1/label/__name__/values")
    return j.get("data", []) or []

# -----------------------------------------------------------------------------
# Loki
# -----------------------------------------------------------------------------
def loki_api(path: str, params=None, timeout=8):
    r = _get(f"/api/datasources/proxy/{DS_LOKI}{path}", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def loki_health():
    try:
        end_ns = int(time.time() * 1e9)
        start_ns = int((time.time() - 60) * 1e9)
        j = loki_api(
            "/loki/api/v1/query_range",
            params={
                "query": '{app=~".+"}',
                "limit": 1,
                "direction": "BACKWARD",
                "start": start_ns,
                "end": end_ns,
            },
        )
        return j.get("status") == "success", "query ok"
    except Exception as e:
        return False, str(e)

def loki_tail(query: str, limit: int, window_sec: int):
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
    )
    return j.get("data", {}).get("result", []) or []

# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------
def render_loki_table(query: str, streams: List[dict], limit: int) -> Table:
    t = Table(title=f"Loki tail | {query}", show_lines=False)
    t.add_column("time", width=12)
    t.add_column("line", overflow="fold")

    rows: List[Tuple[int, str]] = []
    for s in streams:
        for ts_ns, line in s.get("values", []):
            rows.append((int(ts_ns), line))

    rows.sort(key=lambda x: x[0], reverse=True)

    if not rows:
        t.add_row("-", "(no logs in window)")
        return t

    for ts_ns, line in rows[:limit]:
        ts = datetime.fromtimestamp(ts_ns / 1e9).strftime("%H:%M:%S.%f")[:-3]
        t.add_row(ts, line.rstrip())

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
    layout["body"].split_column(*[Layout(t) for t in tables])
    return layout

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    meta = MetaState(metric_names=[])

    with Live(console=console, refresh_per_second=10, screen=True) as live:
        while True:
            now = time.time()

            if now - meta.last_meta > META_REFRESH:
                try:
                    meta.metric_names = prom_metric_names()
                    meta.last_meta = now
                except Exception:
                    pass

            g_ok, g_msg = grafana_health()
            p_ok, p_msg = prom_buildinfo()
            l_ok, l_msg = loki_health()

            header = Text()
            header.append("tui.py ", style="bold")
            header.append(f"refresh={REFRESH}s | ")

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
            header.append(str(len(meta.metric_names)), style="cyan")

            banner = Panel(header, title="Status", border_style="blue")

            tables: List[Table] = []

            if len(meta.metric_names) == 0:
                t = Table(title="Prometheus/Mimir: no metrics ingested yet", show_lines=False)
                t.add_column("hint", overflow="fold")
                t.add_row(
                    "Metrics pipeline not wired yet.\n"
                    "Once Prometheus / Agent / Alloy ships data into Mimir, panels will populate."
                )
                tables.append(t)

            streams = loki_tail(LOKI_QUERY, LOKI_LIMIT, LOKI_WINDOW_SEC)
            tables.append(render_loki_table(LOKI_QUERY, streams, LOKI_LIMIT))

            live.update(build_layout(banner, tables))
            time.sleep(REFRESH)

if __name__ == "__main__":
    main()
