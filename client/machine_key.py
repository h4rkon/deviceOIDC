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
import os
import sys
import time
import uuid
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError


DEBUG = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")


def log(msg: str):
    print(f"[slot] {msg}")


def debug(msg: str):
    if DEBUG:
        print(f"[debug] {msg}")


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


def main() -> int:
    ingress_base = os.getenv("INGRESS_BASE", "http://localhost:8081")

    realm = os.getenv("KC_REALM", "deviceoidc")
    client_id = os.getenv("KC_CLIENT_ID", "slot-machine")

    # Path to RSA private key used to sign the client_assertion
    # Example: ./secrets/slot-machine.key.pem
    key_path = os.getenv("KC_PRIVATE_KEY", "")
    kid = os.getenv("KC_KID", "").strip() or None  # optional but often helpful

    machine_id = os.getenv("MACHINE_ID", "slot-001")
    bet = int(os.getenv("BET", "1"))

    if not key_path:
        log("KC_PRIVATE_KEY missing (export KC_PRIVATE_KEY=slot-machine.private.pem)")
        return 2

    token_url = f"{ingress_base}/realms/{realm}/protocol/openid-connect/token"
    token_aud = get_token_endpoint(ingress_base, realm)
    hello_url = f"{ingress_base}/hello"

    log("Starting slot machine client (private_key_jwt)")
    log(f"Ingress base: {ingress_base}")
    log(f"Machine ID: {machine_id}")
    log(f"Client ID: {client_id}")

    # ---- 1) Build client_assertion ----
    try:
        client_assertion = build_client_assertion_rs256(
            client_id=client_id,
            token_endpoint_aud=token_aud,   # IMPORTANT: must match token endpoint URL Keycloak expects
            private_key_path=key_path,
            kid=kid,
            lifetime_sec=300,
        )
    except Exception as e:
        log(f"Failed to build client_assertion: {e}")
        return 3

    # ---- 2) Token (client_credentials) ----
    log("Requesting access token from Keycloak (client_credentials + private_key_jwt)")

    try:
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
    except (HTTPError, URLError) as e:
        log(f"Token request failed: {e}")
        return 4

    access_token = token_resp.get("access_token")
    if not access_token:
        log("No access_token returned")
        debug(json.dumps(token_resp, indent=2))
        return 5

    log("Access token received")

    claims = decode_jwt_payload(access_token)
    debug("Decoded JWT claims:")
    debug(json.dumps({k: claims.get(k) for k in ("iss", "aud", "azp", "sub", "exp")}, indent=2))

    # ---- 3) Call hello ----
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
        return 6

    log("Spin completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
