#!/usr/bin/env python3
"""
Generate a client_assertion JWT for Keycloak private_key_jwt auth.

Prints the JWT to stdout so it can be captured in shell:
  CLIENT_ASSERTION="$(./client/client_assertion.py --private-key slot-machine.private.pem)"
"""

import argparse
import base64
import json
import time
import uuid
import urllib.request


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def get_token_endpoint(ingress_base: str, realm: str) -> str:
    url = f"{ingress_base}/realms/{realm}/.well-known/openid-configuration"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Host", "keycloak.local")

    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        doc = json.loads(raw)
        return doc["token_endpoint"]


def sign_rs256_with_openssl(message: bytes, private_key_path: str) -> bytes:
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Keycloak client_assertion JWT (private_key_jwt)."
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
        "--lifetime-sec",
        type=int,
        default=300,
        help="JWT lifetime in seconds (default: 300).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    token_endpoint = get_token_endpoint(args.ingress_base, args.realm)
    now = int(time.time())

    header = {"alg": "RS256", "typ": "JWT"}
    kid = args.kid.strip() if isinstance(args.kid, str) and args.kid.strip() else None
    if kid:
        header["kid"] = kid

    payload = {
        "iss": args.client_id,
        "sub": args.client_id,
        "aud": token_endpoint,
        "iat": now,
        "exp": now + args.lifetime_sec,
        "jti": str(uuid.uuid4()),
    }

    signing_input = (
        f"{b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    ).encode("ascii")

    sig = sign_rs256_with_openssl(signing_input, args.private_key)
    jwt = signing_input.decode("ascii") + "." + b64url(sig)
    print(jwt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
