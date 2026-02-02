#!/usr/bin/env python3
"""
Slot machine demo client (debug-friendly) — private_key_jwt

Flow:
1) Create a client_assertion JWT signed with the machine's private key (RS256)
2) Request access token from Keycloak (client_credentials + private_key_jwt)
3) Decode and print selected JWT claims (debug only, no verification)
4) Call POST /hello through Envoy with Bearer token

No external deps, stdlib only.

Prereqs (Keycloak):
- Client "slot-machine"
- Client authentication enabled
- Service accounts enabled
- Client Authenticator: "Signed JWT" (private_key_jwt)
- Public key uploaded to client (Keys / Credentials, depending on UI)

Networking model (your setup):
- Ingress port-forward: localhost:8081
- Routing via Host header:
    Host: keycloak.local -> Keycloak
    Host: hello.local    -> Hello service
"""

import base64
import json
import sys
import time
import uuid
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
import argparse
from enum import Enum
import datetime


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


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload WITHOUT verification (debug only)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64.encode())
        return json.loads(raw.decode())
    except Exception as e:
        return {"error": str(e)}
    
def get_token_endpoint(ingress_base: str, realm: str) -> str:
    url = f"{ingress_base}/realms/{realm}/.well-known/openid-configuration"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Host", "keycloak.local")

    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        doc = json.loads(raw)
        return doc["token_endpoint"]


def post_form(url: str, data: dict, host: str, timeout: int = 10) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Host", host)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    debug(f"POST {url}")
    debug(f"Host: {host}")
    debug(f"Form data keys: {list(data.keys())}")

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


# ---------- Minimal RS256 signing (stdlib only) ----------
# Python stdlib has no RSA signer. We shell out to openssl (available on macOS / most dev boxes).
# This keeps the script dependency-free while still being reproducible.

def sign_rs256_with_openssl(message: bytes, private_key_path: str) -> bytes:
    """
    Returns RSA PKCS#1 v1.5 + SHA-256 signature of `message`.
    Requires `openssl` in PATH.

    Equivalent to:
      openssl dgst -sha256 -sign key.pem
    """
    import subprocess

    try:
        p = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", private_key_path],
            input=message,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return p.stdout
    except FileNotFoundError:
        raise RuntimeError("openssl not found. Install it or put it on PATH.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"openssl signing failed: {e.stderr.decode('utf-8', 'ignore')}")


def build_client_assertion_rs256(
    client_id: str,
    token_endpoint_aud: str,
    private_key_path: str,
    kid: str | None = None,
    lifetime_sec: int = 300,
) -> str:
    """
    Build a JWT suitable for Keycloak private_key_jwt authentication.

    Claims:
      iss, sub = client_id
      aud      = token endpoint URL
      iat/exp  = now / now+lifetime
      jti      = random id
    """
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    if kid:
        header["kid"] = kid

    payload = {
        "iss": client_id,
        "sub": client_id,
        "aud": token_endpoint_aud,
        "iat": now,
        "exp": now + lifetime_sec,
        "jti": str(uuid.uuid4()),
    }

    signing_input = f"{b64url(json.dumps(header, separators=(',', ':')).encode())}.{b64url(json.dumps(payload, separators=(',', ':')).encode())}".encode("ascii")
    sig = sign_rs256_with_openssl(signing_input, private_key_path)
    jwt = signing_input.decode("ascii") + "." + b64url(sig)

    debug("Built client_assertion:")
    debug(f"  aud: {token_endpoint_aud}")
    debug(f"  iss/sub: {client_id}")
    debug(f"  kid: {kid or '<none>'}")
    return jwt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Slot machine demo client (private_key_jwt)."
    )
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
        default="slot-machine",
        help="Keycloak client ID (default: slot-machine).",
    )
    parser.add_argument(
        "--private-key",
        required=True,
        help="Path to RSA private key used to sign the client_assertion.",
    )
    parser.add_argument(
        "--kid",
        default=None,
        help="Key ID (kid) to set in JWT header (optional).",
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
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between hello calls (default: 2.0).",
    )
    parser.add_argument(
        "--token-max-age",
        type=int,
        default=60,
        help="client_assertion lifetime in seconds (default: 60).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def fetch_access_token(
    *,
    token_url: str,
    token_aud: str,
    client_id: str,
    key_path: str,
    kid: str | None,
    token_max_age: int,
) -> tuple[str, int]:
    try:
        client_assertion = build_client_assertion_rs256(
            client_id=client_id,
            token_endpoint_aud=token_aud,   # IMPORTANT: must match token endpoint URL Keycloak expects
            private_key_path=key_path,
            kid=kid,
            lifetime_sec=token_max_age,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to build client_assertion: {e}")

    log("Requesting access token from Keycloak (client_credentials + private_key_jwt)")

    token_resp = post_form(
        token_url,
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": client_assertion,
        },
        host="keycloak.local",
    )

    access_token = token_resp.get("access_token")
    if not access_token:
        debug(json.dumps(token_resp, indent=2))
        raise RuntimeError("No access_token returned")

    now = int(time.time())
    expires_in = token_resp.get("expires_in")
    if isinstance(expires_in, int) and expires_in > 0:
        exp = now + min(expires_in, token_max_age)
    else:
        claims = decode_jwt_payload(access_token)
        exp = int(claims.get("exp") or 0)
        if not exp:
            exp = now + token_max_age

    claims = decode_jwt_payload(access_token)
    debug("Decoded JWT claims:")
    debug(json.dumps({k: claims.get(k) for k in ("iss", "aud", "azp", "sub", "exp")}, indent=2))
    if isinstance(claims.get("exp"), int):
        exp_utc = datetime.datetime.utcfromtimestamp(claims["exp"]).isoformat() + "Z"
        log(f"Access token exp (UTC): {exp_utc}")

    return access_token, exp


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    global DEBUG
    DEBUG = args.debug

    ingress_base = args.ingress_base
    realm = args.realm
    client_id = args.client_id
    key_path = args.private_key
    kid = args.kid.strip() if isinstance(args.kid, str) and args.kid.strip() else None
    machine_id = args.machine_id
    bet = args.bet
    interval = args.interval
    token_max_age = args.token_max_age

    token_url = f"{ingress_base}/realms/{realm}/protocol/openid-connect/token"
    token_aud = get_token_endpoint(ingress_base, realm)
    hello_url = f"{ingress_base}/hello"

    log("Starting slot machine client (private_key_jwt)")
    log(f"Ingress base: {ingress_base}")
    log(f"Machine ID: {machine_id}")
    log(f"Client ID: {client_id}")

    access_token: str | None = None

    log("Calling protected API via Envoy (loop)")

    try:
        while True:
            if access_token is None:
                try:
                    access_token, _token_exp = fetch_access_token(
                        token_url=token_url,
                        token_aud=token_aud,
                        client_id=client_id,
                        key_path=key_path,
                        kid=kid,
                        token_max_age=token_max_age,
                    )
                    log("Access token received", LogLevel.SUCCESS)
                except (HTTPError, URLError, RuntimeError) as e:
                    log(f"Token request failed: {e}", LogLevel.ERROR)
                    time.sleep(interval)
                    continue

            payload = {
                "machineId": machine_id,
                "spinId": f"spin-{int(time.time())}",
                "bet": bet,
                "ts": int(time.time()),
            }

            try:
                status, body = post_json(
                    hello_url,
                    payload,
                    host="hello.local",
                    bearer=access_token,
                )
            except (HTTPError, URLError) as e:
                log(f"Hello call failed: {e}", LogLevel.ERROR)
                access_token = None
                time.sleep(interval)
                continue

            if status < 400:
                log(f"API response status: {status}", LogLevel.SUCCESS)
            else:
                log(f"API response status: {status}", LogLevel.ERROR)
            print(body)

            if status >= 400:
                log("Call failed; refreshing token and continuing", LogLevel.ERROR)
                access_token = None
                time.sleep(interval)
                continue

            time.sleep(interval)
    except KeyboardInterrupt:
        log("Stopped by user")
        return 0


if __name__ == "__main__":
    sys.exit(main())
