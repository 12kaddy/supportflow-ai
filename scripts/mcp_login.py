"""Acquire a short-lived local customer token without putting passwords in shell history."""

import argparse
import json
from getpass import getpass
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path(".local/mcp-token.json"))
    args = parser.parse_args()
    response = httpx.post(
        args.api_url.rstrip("/") + "/v1/auth/login",
        json={"email": args.email, "password": getpass("Customer password: ")},
        timeout=15,
    )
    if not response.is_success:
        raise SystemExit(f"Customer login failed ({response.status_code})")
    data = response.json()
    if data["user"]["role"] != "customer":
        raise SystemExit("MCP read tools require a customer account")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"access_token": data["access_token"], "expires_in": data["expires_in"]}),
        encoding="utf-8",
    )
    print(
        f"Private token file saved: {args.output.resolve()}. Keep it ignored and renew after expiry."
    )


if __name__ == "__main__":
    main()
