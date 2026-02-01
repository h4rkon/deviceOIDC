#!/usr/bin/env python3
import os
import time
import re
import json
import requests
from typing import List, Tuple, Optional
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
DS_LOKI = int(os.getenv("DS_LOKI_ID", "2"))

REFRESH = float(os.getenv("REFRESH", "2.0"))

# ✅ TUI default query (NO line_format; we parse JSON locally)
# Shows "meaningful stuff": token mint + hello call via envoy structured logs
LOKI_QUERY = os.getenv(
    "LOKI_QUERY",
    '{app="envoy", namespace=~".+", namespace!~"observability|argocd|kube-system"}'
    ' | json | method="POST" | upstream=~"keycloak|hello_upstream"'
)

# Fallback if query fails
LOKI_FALLBACK_QUERY = os.getenv("LOKI_FALLBACK_QUERY", '{app=~".+"}')

LOKI_LIMIT = int(os.getenv("LOKI_LIMIT", "80"))
LOKI_WINDOW_SEC = int(os.getenv("LOKI_WINDOW_SEC", "900"))

# Visual tuning
MAX_PATH_LEN = int(os.getenv("MAX_PATH_LEN", "60"))
MAX_UPSTREAM_LEN = int(os.getenv("MAX_UPSTREAM_LEN", "18"))
MAX_POD_LEN = int(os.getenv("MAX_POD_LEN", "24"))
MAX_MSG_LEN = int(os.getenv("MAX_MSG_LEN", "120"))

console = Console()

# -----------------------------------------------------------------------------
# HTTP helpers
# -----------------------------------------------------------------------------
def _get(path: str, params=None, timeout=8) -> requests.Response:
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

def raise_for_status_with_body(r: requests.Response, ctx: str):
    if 200 <= r.status_code < 300:
        return
    body = ""
    try:
        body = r.text.strip()
    except Exception:
        body = "<no body>"
    raise requests.HTTPError(f"{ctx}: HTTP {r.status_code} | {body}", response=r)

# -----------------------------------------------------------------------------
# Loki via Grafana datasource proxy
# -----------------------------------------------------------------------------
def loki_api(path: str, params=None, timeout=10) -> dict:
    r = _get(f"/api/datasources/proxy/{DS_LOKI}{path}", params=params, timeout=timeout)
    raise_for_status_with_body(r, f"Loki {path}")
    return r.json()

def loki_health() -> Tuple[bool, str]:
    try:
        end_ns = int(time.time() * 1e9)
        start_ns = int((time.time() - 60) * 1e9)
        loki_api(
            "/loki/api/v1/query_range",
            params={
                "query": LOKI_FALLBACK_QUERY,
                "limit": 1,
                "direction": "BACKWARD",
                "start": start_ns,
                "end": end_ns,
            },
            timeout=5,
        )
        return True, "query ok"
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
# Rendering helpers
# -----------------------------------------------------------------------------
def truncate(s: str, n: int) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 1] + "…"

def fmt_ts(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9).strftime("%H:%M:%S.%f")[:-3]

def pick_label(labels: dict, *keys: str, default: str = "-") -> str:
    for k in keys:
        v = labels.get(k)
        if v:
            return v
    return default

# -----------------------------------------------------------------------------
# 1) Parse Envoy structured JSON logs
# -----------------------------------------------------------------------------
def parse_envoy_json(line: str) -> Optional[dict]:
    line = line.strip()
    if not (line.startswith("{") and line.endswith("}")):
        return None
    try:
        obj = json.loads(line)
    except Exception:
        return None

    # We only treat it as envoy access JSON if it looks like one
    needed = {"authority", "method", "path", "status", "upstream"}
    if not needed.issubset(obj.keys()):
        return None

    # Normalize / safe casts
    status = obj.get("status")
    try:
        status = int(status)
    except Exception:
        status = status

    return {
        "authority": str(obj.get("authority", "-")),
        "method": str(obj.get("method", "-")),
        "path": str(obj.get("path", "-")),
        "status": status,
        "upstream": str(obj.get("upstream", "-")),
        "req_id": str(obj.get("req_id", obj.get("request_id", "-"))),
        "ts": str(obj.get("ts", "-")),
    }

# -----------------------------------------------------------------------------
# 2) Parse nginx-ish access log lines (your other envoy format)
# -----------------------------------------------------------------------------
ACCESS_RE = re.compile(r'"(?P<method>[A-Z]+)\s+(?P<path>\S+)\s+HTTP/[^"]+"\s+(?P<status>\d{3})\s')

def parse_access_line(line: str) -> Optional[dict]:
    m = ACCESS_RE.search(line)
    if not m:
        return None

    method = m.group("method")
    path = m.group("path")
    status = int(m.group("status"))

    # heuristic for req_id: last token often 32-hex
    tokens = line.strip().split()
    req_id = "-"
    if tokens:
        last = tokens[-1]
        if re.fullmatch(r"[0-9a-f]{32}", last):
            req_id = last

    # heuristic for upstream: first token that looks like IP:port
    upstream = "-"
    for tok in tokens:
        if ":" in tok and tok.count(".") >= 1 and tok.split(":")[-1].isdigit():
            upstream = tok
            break

    # heuristic duration: first token that looks like 0.002
    dur = "-"
    for tok in tokens:
        if tok.count(".") == 1 and tok.replace(".", "").isdigit():
            dur = tok
            break

    return {
        "method": method,
        "path": path,
        "status": status,
        "upstream": upstream,
        "dur": dur,
        "req_id": req_id,
    }

# -----------------------------------------------------------------------------
# Render table
# -----------------------------------------------------------------------------
def render_loki_table(active_query: str, streams: List[dict], limit: int) -> Table:
    t = Table(title=f"Loki | {active_query}", show_lines=False)

    t.add_column("time", width=12)
    t.add_column("ns", width=12, overflow="fold")
    t.add_column("app", width=8, overflow="fold")
    t.add_column("pod", width=MAX_POD_LEN, overflow="fold")

    # Structured request columns
    t.add_column("st", width=3, justify="right")
    t.add_column("auth", width=16, overflow="fold")
    t.add_column("m", width=4)
    t.add_column("path", width=MAX_PATH_LEN, overflow="fold")
    t.add_column("up", width=MAX_UPSTREAM_LEN, overflow="fold")
    t.add_column("req_id", width=12, overflow="fold")

    # Fallback msg
    t.add_column("msg", overflow="fold")

    rows: List[Tuple[int, dict, str]] = []
    for s in streams:
        labels = s.get("stream", {}) or {}
        for ts_ns, line in s.get("values", []):
            rows.append((int(ts_ns), labels, line))

    rows.sort(key=lambda x: x[0], reverse=True)

    if not rows:
        t.add_row("-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "(no logs in window)")
        return t

    for ts_ns, labels, line in rows[:limit]:
        ns = pick_label(labels, "namespace")
        app = pick_label(labels, "app", "service_name", "container")
        pod = truncate(pick_label(labels, "pod"), MAX_POD_LEN)

        # Prefer envoy JSON access logs (best structured)
        ej = parse_envoy_json(line)
        if ej:
            t.add_row(
                fmt_ts(ts_ns),
                ns,
                app,
                pod,
                str(ej["status"]),
                truncate(ej["authority"], 16),
                ej["method"],
                truncate(ej["path"], MAX_PATH_LEN),
                truncate(ej["upstream"], MAX_UPSTREAM_LEN),
                truncate(ej["req_id"], 12),
                "",  # msg empty, we have structure
            )
            continue

        # Next: nginx-ish access log
        al = parse_access_line(line)
        if al:
            t.add_row(
                fmt_ts(ts_ns),
                ns,
                app,
                pod,
                str(al["status"]),
                "-",  # authority unknown in this format
                al["method"],
                truncate(al["path"], MAX_PATH_LEN),
                truncate(al["upstream"], MAX_UPSTREAM_LEN),
                truncate(al["req_id"], 12),
                f"dur={al['dur']}",
            )
            continue

        # Raw fallback
        t.add_row(
            fmt_ts(ts_ns),
            ns,
            app,
            pod,
            "-",
            "-",
            "-",
            "-",
            "-",
            "-",
            truncate(line.rstrip(), MAX_MSG_LEN),
        )

    return t

def build_layout(banner: Panel, table: Table) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(banner, size=7),
        Layout(table),
    )
    return layout

# -----------------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------------
def main():
    last_loki_error: Optional[str] = None
    active_query = LOKI_QUERY

    with Live(console=console, refresh_per_second=10, screen=True) as live:
        while True:
            g_ok, g_msg = grafana_health()
            l_ok, l_msg = loki_health()

            header = Text()
            header.append("tui.py ", style="bold")
            header.append(
                f"refresh={REFRESH}s  window={LOKI_WINDOW_SEC}s  limit={LOKI_LIMIT}  ",
                style="dim",
            )
            header.append("| ")

            header.append("Grafana=", style="bold")
            header.append("OK " if g_ok else "FAIL ", style="green" if g_ok else "red")
            header.append(f"({g_msg})  ")

            header.append("Loki=", style="bold")
            header.append("OK " if l_ok else "FAIL ", style="green" if l_ok else "red")
            header.append(f"({l_msg})")

            if last_loki_error:
                header.append("\n")
                header.append(f"Loki tail error: {last_loki_error}", style="yellow")

            banner = Panel(header, title="Status", border_style="blue")

            try:
                streams = loki_tail(LOKI_QUERY, LOKI_LIMIT, LOKI_WINDOW_SEC)
                active_query = LOKI_QUERY
                last_loki_error = None
            except Exception as e:
                last_loki_error = str(e)
                streams = loki_tail(LOKI_FALLBACK_QUERY, LOKI_LIMIT, LOKI_WINDOW_SEC)
                active_query = LOKI_FALLBACK_QUERY

            table = render_loki_table(active_query, streams, LOKI_LIMIT)
            live.update(build_layout(banner, table))
            time.sleep(REFRESH)

if __name__ == "__main__":
    main()
