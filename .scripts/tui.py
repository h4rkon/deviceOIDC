import time
import requests
from rich.console import Console
from rich.table import Table

GRAFANA = "http://localhost:3000"
DS_PROM = 1
REFRESH = 2.0

PROM_QUERIES = {
  "CPU top pods": 'topk(10, rate(container_cpu_usage_seconds_total[5m]))',
  "Mem top pods": 'topk(10, container_memory_working_set_bytes)',
  "Restarts (5m)": 'topk(10, increase(kube_pod_container_status_restarts_total[5m]))',
}

console = Console()

def prom(q: str):
    r = requests.get(
        f"{GRAFANA}/api/datasources/proxy/{DS_PROM}/api/v1/query",
        params={"query": q},
        timeout=5,
    )
    r.raise_for_status()
    return r.json()["data"]["result"]

def render_block(title, query, result):
    t = Table(title=f"{title}  |  {query}", show_header=True, header_style="bold")
    t.add_column("labels", overflow="fold")
    t.add_column("value", justify="right")
    if not result:
        t.add_row("(no data)", "")
        return t
    for row in result[:10]:
        labels = ", ".join([f'{k}="{v}"' for k, v in row.get("metric", {}).items()])
        val = row.get("value", ["", ""])[1]
        t.add_row(labels or "(no labels)", str(val))
    return t

while True:
    console.clear()
    for title, q in PROM_QUERIES.items():
        try:
            res = prom(q)
            console.print(render_block(title, q, res))
        except Exception as e:
            console.print(f"[red]{title} failed:[/red] {e}")
    time.sleep(REFRESH)
