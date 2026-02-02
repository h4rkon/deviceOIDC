#!/usr/bin/env python3
"""
Slot machine demo client (debug-friendly)

Flow:
1) Request access token from Keycloak (password grant)
2) Decode and print selected JWT claims (debug only, no verification)
3) Call POST /hello through Envoy with Bearer token

No external deps, stdlib only.
"""

import argparse
import base64
import json
import sys
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
from enum import Enum


DEBUG = False


class LogLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    SUCCESS = "success"
    ERROR = "error"


_COLOR = {
    LogLevel.DEBUG: "\033[90m",   # light grey
    LogLevel.INFO: "\033[37m",    # white
    LogLevel.SUCCESS: "\033[32m", # green
    LogLevel.ERROR: "\033[31m",   # red
}
_RESET = "\033[0m"


def log(msg: str, level: LogLevel = LogLevel.INFO):
    color = _COLOR.get(level, _RESET)
    print(f"{color}[slot] {msg}{_RESET}")


def debug(msg: str):
    if DEBUG:
        log(msg, LogLevel.DEBUG)


def decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload WITHOUT verification (debug only)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64.encode())
        return json.loads(raw.decode())
    except Exception as e:
        return {"error": str(e)}


def post_form(url: str, data: dict, host: str, timeout: int = 10) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Host", host)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    debug(f"POST {url}")
    debug(f"Host: {host}")
    debug(f"Form data: {data}")

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        debug(f"Token response ({resp.status}): {raw[:200]}...")
        return json.loads(raw)


def post_json(url: str, payload: dict, host: str, bearer: str, timeout: int = 10):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Host", host)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {bearer}")

    debug(f"POST {url}")
    debug(f"Host: {host}")
    debug(f"Payload: {payload}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, raw
    except HTTPError as e:
        return e.code, e.read().decode("utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Slot machine demo client.")
    parser.add_argument(
        "--ingress-base",
        default="http://localhost:8081",
        help="Ingress base URL (default: http://localhost:8081).",
    )
    parser.add_argument(
        "--realm",
        default="deviceoidc",
        help="Keycloak realm (default: deviceoidc).",
    )
    parser.add_argument(
        "--client-id",
        default="deviceoidc-cli",
        help="Keycloak client ID (default: deviceoidc-cli).",
    )
    parser.add_argument(
        "--username",
        default="test",
        help="Keycloak username (default: test).",
    )
    parser.add_argument(
        "--password",
        required=True,
        help="Keycloak password.",
    )
    parser.add_argument(
        "--machine-id",
        default="slot-001",
        help="Machine ID (default: slot-001).",
    )
    parser.add_argument(
        "--bet",
        type=int,
        default=1,
        help="Bet amount (default: 1).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    global DEBUG
    DEBUG = args.debug

    ingress_base = args.ingress_base
    realm = args.realm
    client_id = args.client_id
    username = args.username
    password = args.password
    machine_id = args.machine_id
    bet = args.bet

    token_url = f"{ingress_base}/realms/{realm}/protocol/openid-connect/token"
    hello_url = f"{ingress_base}/hello"

    log("Starting slot machine client")
    log(f"Ingress base: {ingress_base}")
    log(f"Machine ID: {machine_id}")

    # ---- 1) Token ----
    log("Requesting access token from Keycloak")

    try:
        token_resp = post_form(
            token_url,
            {
                "grant_type": "password",
                "client_id": client_id,
                "username": username,
                "password": password,
            },
            host="keycloak.local",
        )
    except (HTTPError, URLError) as e:
        log(f"Token request failed: {e}", LogLevel.ERROR)
        return 3

    access_token = token_resp.get("access_token")
    if not access_token:
        log("No access_token returned", LogLevel.ERROR)
        debug(json.dumps(token_resp, indent=2))
        return 4

    log("Access token received", LogLevel.SUCCESS)

    claims = decode_jwt_payload(access_token)
    debug("Decoded JWT claims:")
    debug(json.dumps(
        {k: claims.get(k) for k in ("iss", "aud", "azp", "sub", "exp")},
        indent=2
    ))

    # ---- 2) Call hello ----
    payload = {
        "machineId": machine_id,
        "spinId": f"spin-{int(time.time())}",
        "bet": bet,
        "ts": int(time.time()),
    }

    log("Calling protected API via Envoy")

    status, body = post_json(
        hello_url,
        payload,
        host="hello.local",
        bearer=access_token,
    )

    if status < 400:
        log(f"API response status: {status}", LogLevel.SUCCESS)
    else:
        log(f"API response status: {status}", LogLevel.ERROR)
    print(body)

    if status >= 400:
        log("Call failed", LogLevel.ERROR)
        return 5

    log("Spin completed successfully", LogLevel.SUCCESS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
