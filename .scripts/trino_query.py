#!/usr/bin/env python3
"""
Simple interactive Trino query runner over HTTP.
"""

import json
import sys
import urllib.request
from typing import Any


TRINO_URL = "http://localhost:8084/v1/statement"
TRINO_USER = "admin"


def trino_post(sql: str) -> dict[str, Any]:
    req = urllib.request.Request(
        TRINO_URL,
        data=sql.encode("utf-8"),
        headers={
            "X-Trino-User": TRINO_USER,
            "Content-Type": "text/plain",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def trino_get(uri: str) -> dict[str, Any]:
    with urllib.request.urlopen(uri) as resp:
        return json.load(resp)


def run_query(sql: str) -> tuple[list[dict[str, Any]] | None, list[list[Any]]]:
    payload = trino_post(sql)
    columns = payload.get("columns")
    rows = payload.get("data", []) or []
    next_uri = payload.get("nextUri")

    while next_uri:
        payload = trino_get(next_uri)
        columns = columns or payload.get("columns")
        rows.extend(payload.get("data", []) or [])
        next_uri = payload.get("nextUri")

    return columns, rows


def main() -> int:
    print("Trino query runner (empty line to quit)")
    while True:
        try:
            sql = input("> ").strip()
        except EOFError:
            print()
            return 0
        if not sql:
            return 0

        try:
            columns, rows = run_query(sql)
        except Exception as exc:
            print(f"Error: {exc}")
            continue

        if columns:
            print("COLUMNS:")
            print(json.dumps(columns, indent=2))
        else:
            print("COLUMNS: []")

        print("ROWS:")
        print(json.dumps(rows, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
