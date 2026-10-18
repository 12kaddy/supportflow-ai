"""Short-lived signed tokens; passwords and roles are never supplied by the UI."""

import secrets
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import jwt
from fastapi import HTTPException

from app.core.config import get_settings
from app.models.entities import utcnow


@lru_cache
def file_secret():
    path = Path(__file__).resolve().parents[2] / ".local/auth-signing.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    return path.read_text(encoding="utf-8").strip()


def signing_secret():
    value = get_settings().local_auth_secret or file_secret()
    if len(value) < 32:
        raise HTTPException(503, "Local signing key must be at least 32 characters")
    return value


def issue_token(account):
    now = utcnow()
    return jwt.encode(
        {
            "sub": account.id,
            "iss": "supportflow-local",
            "aud": "supportflow-api",
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "email": account.email,
            "email_verified": account.email_verified,
            "realm_access": {
                "roles": ["admin", "reviewer"] if account.role == "admin" else ["customer"]
            },
        },
        signing_secret(),
        algorithm="HS256",
    )


def local_claims(authorization, role):
    scheme, _, token = authorization.partition(" ")
    try:
        if scheme.lower() != "bearer" or not token or len(token) > 16384:
            raise jwt.InvalidTokenError()
        claims = jwt.decode(
            token,
            signing_secret(),
            algorithms=["HS256"],
            issuer="supportflow-local",
            audience="supportflow-api",
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
        if not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 40:
            raise jwt.InvalidTokenError()
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(
            401, "Please log in again", headers={"WWW-Authenticate": "Bearer"}
        ) from None
    if role not in claims.get("realm_access", {}).get("roles", []):
        raise HTTPException(403, "This account does not have the required role")
    return claims
