#!/usr/bin/env python3
import os
import time
import re
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

# Default: workload feed, exclude platform noise
LOKI_QUERY = os.getenv(
    "LOKI_QUERY",
    '{namespace=~".+", namespace!~"observability|argocd|kube-system|postgres"}'
)

# Fallback if query fails (still shows something)
LOKI_FALLBACK_QUERY = os.getenv("LOKI_FALLBACK_QUERY", '{app=~".+"}')

LOKI_LIMIT = int(os.getenv("LOKI_LIMIT", "80"))
LOKI_WINDOW_SEC = int(os.getenv("LOKI_WINDOW_SEC", "600"))

# Visual tuning
MAX_MSG_LEN = int(os.getenv("MAX_MSG_LEN", "140"))   # for raw/unknown lines
MAX_PATH_LEN = int(os.getenv("MAX_PATH_LEN", "52"))  # keep tables tight
MAX_UPSTREAM_LEN = int(os.getenv("MAX_UPSTREAM_LEN", "26"))

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
def fmt_ts(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9).strftime("%H:%M:%S.%f")[:-3]

def truncate(s: str, n: int) -> str:
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 1] + "…"

def pick_label(labels: dict, *keys: str, default: str = "-") -> str:
    for k in keys:
        v = labels.get(k)
        if v:
            return v
    return default

# -----------------------------------------------------------------------------
# Access log compaction
# We target lines like:
# 127.0.0.1 - - [31/Jan/2026:14:09:06 +0000] "HEAD /hello HTTP/1.1" 401 0 "-" "curl/8.7.1" 80 0.002  [] 10.42.0.37:8080 0 0.002 401 <reqid>
#
# We parse method, path, status, upstream, duration (best-effort).
# -----------------------------------------------------------------------------
ACCESS_RE = re.compile(r'"(?P<method>[A-Z]+)\s+(?P<path>\S+)\s+HTTP/[^"]+"\s+(?P<status>\d{3})\s')

def parse_access_line(line: str) -> Optional[dict]:
    m = ACCESS_RE.search(line)
    if not m:
        return None

    method = m.group("method")
    path = m.group("path")
    status = m.group("status")

    # After the second quoted part, remaining tokens usually contain upstream + durations.
    # We’ll do a best-effort parse by splitting on quotes and then tokenizing the tail.
    parts = line.split('"')
    tail = parts[-1].strip() if parts else ""
    tokens = tail.split()

    upstream = "-"
    dur = "-"

    # Heuristic: find first token that looks like IP:port (upstream)
    for tok in tokens:
        if ":" in tok and tok.count(".") >= 1 and tok.split(":")[-1].isdigit():
            upstream = tok
            break

    # Heuristic: find first token that looks like duration seconds (e.g. 0.002)
    for tok in tokens:
        if tok.count(".") == 1 and tok.replace(".", "").isdigit():
            # keep the first plausible duration
            dur = tok
            break

    return {
        "method": method,
        "path": path,
        "status": status,
        "upstream": upstream,
        "dur": dur,
    }

def render_loki_table(active_query: str, streams: List[dict], limit: int) -> Table:
    t = Table(title=f"Loki | {active_query}", show_lines=False)
    t.add_column("time", width=12)
    t.add_column("ns", width=14, overflow="fold")
    t.add_column("app", width=10, overflow="fold")
    t.add_column("pod", width=22, overflow="fold")
    t.add_column("kind", width=6)

    t.add_column("m", width=4)
    t.add_column("path", width=MAX_PATH_LEN, overflow="fold")
    t.add_column("st", width=3, justify="right")
    t.add_column("upstream", width=MAX_UPSTREAM_LEN, overflow="fold")
    t.add_column("dur", width=7, justify="right")
    t.add_column("msg", overflow="fold")

    rows: List[Tuple[int, dict, str]] = []  # (ts_ns, labels, line)

    for s in streams:
        labels = s.get("stream", {}) or {}
        for ts_ns, line in s.get("values", []):
            rows.append((int(ts_ns), labels, line))

    rows.sort(key=lambda x: x[0], reverse=True)

    if not rows:
        t.add_row("-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "(no logs in window)")
        return t

    for ts_ns, labels, line in rows[:limit]:
        ns = pick_label(labels, "namespace")
        app = pick_label(labels, "app", "service_name", "container")
        pod = pick_label(labels, "pod")

        parsed = parse_access_line(line)
        if parsed:
            kind = "http"
            method = parsed["method"]
            path = truncate(parsed["path"], MAX_PATH_LEN)
            status = parsed["status"]
            upstream = truncate(parsed["upstream"], MAX_UPSTREAM_LEN)
            dur = parsed["dur"]
            msg = ""  # keep compact
        else:
            kind = "log"
            method = "-"
            path = "-"
            status = "-"
            upstream = "-"
            dur = "-"
            msg = truncate(line.rstrip(), MAX_MSG_LEN)

        t.add_row(
            fmt_ts(ts_ns),
            ns,
            app,
            pod,
            kind,
            method,
            path,
            status,
            upstream,
            dur,
            msg,
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
                style="dim"
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
