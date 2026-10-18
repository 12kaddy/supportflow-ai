"""Obtain a local Keycloak access token through browser device authorization."""

import argparse
import base64
import hashlib
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx


def device_login(issuer, output):
    parsed = urlparse(issuer)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    ):
        raise ValueError("Use HTTPS or a local development issuer")
    base = issuer.rstrip("/") + "/protocol/openid-connect"
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    with httpx.Client(timeout=15) as client:
        response = client.post(
            base + "/auth/device",
            data={
                "client_id": "supportflow-ui",
                "scope": "openid email",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        response.raise_for_status()
        device = response.json()
        print("Open this address and sign in:", device["verification_uri_complete"], flush=True)
        print("Verification code:", device["user_code"], flush=True)
        interval = max(1, device.get("interval", 5))
        deadline = time.monotonic() + min(device["expires_in"], 600)
        while time.monotonic() < deadline:
            time.sleep(interval)
            token = client.post(
                base + "/token",
                data={
                    "client_id": "supportflow-ui",
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "code_verifier": verifier,
                    "device_code": device["device_code"],
                },
            )
            payload = token.json()
            if token.is_success:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(
                        {
                            "access_token": payload["access_token"],
                            "expires_in": payload["expires_in"],
                        }
                    ),
                    encoding="utf-8",
                )
                print("Access token saved to", output.resolve(), flush=True)
                return
            if payload.get("error") == "slow_down":
                interval += 5
            elif payload.get("error") != "authorization_pending":
                raise RuntimeError("Login was denied or could not complete")
    raise TimeoutError("Login expired; run the command again")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", default="http://localhost:8080/realms/supportflow")
    parser.add_argument("--output", type=Path, default=Path(".local/oidc-token.json"))
    args = parser.parse_args()
    device_login(args.issuer, args.output)
