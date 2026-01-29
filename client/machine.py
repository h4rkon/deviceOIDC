#!/usr/bin/env python3
"""
Slot machine demo client (debug-friendly)

Flow:
1) Request access token from Keycloak (password grant)
2) Decode and print selected JWT claims (debug only, no verification)
3) Call POST /hello through Envoy with Bearer token

No external deps, stdlib only.
"""

import json
import os
import sys
import time
import base64
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError


DEBUG = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")


def log(msg: str):
    print(f"[slot] {msg}")


def debug(msg: str):
    if DEBUG:
        print(f"[debug] {msg}")


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


def main() -> int:
    ingress_base = os.getenv("INGRESS_BASE", "http://localhost:8081")

    realm = os.getenv("KC_REALM", "deviceoidc")
    client_id = os.getenv("KC_CLIENT_ID", "deviceoidc-cli")
    username = os.getenv("KC_USER", "test")
    password = os.getenv("KC_PASS", "")

    machine_id = os.getenv("MACHINE_ID", "slot-001")
    bet = int(os.getenv("BET", "1"))

    if not password:
        log("KC_PASS missing (export KC_PASS=swordfish)")
        return 2

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
        log(f"Token request failed: {e}")
        return 3

    access_token = token_resp.get("access_token")
    if not access_token:
        log("No access_token returned")
        debug(json.dumps(token_resp, indent=2))
        return 4

    log("Access token received")

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

    log(f"API response status: {status}")
    print(body)

    if status >= 400:
        log("Call failed")
        return 5

    log("Spin completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
