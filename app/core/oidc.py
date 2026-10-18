"""Verify access tokens against one server-configured OIDC issuer."""

from functools import lru_cache
from urllib.parse import urlparse

import jwt
from fastapi import HTTPException

from app.core.config import get_settings


@lru_cache(maxsize=4)
def jwks_client(url):
    return jwt.PyJWKClient(url, timeout=5, lifespan=300)


def unauthorized():
    return HTTPException(401, "Valid access token required", headers={"WWW-Authenticate": "Bearer"})


def token_claims(authorization: str, role: str) -> dict:
    settings = get_settings()
    for value in [settings.oidc_issuer, settings.oidc_jwks_url]:
        parsed = urlparse(value)
        if (
            not parsed.netloc
            or parsed.scheme not in {"https", "http"}
            or (parsed.scheme == "http" and not settings.oidc_allow_http)
        ):
            raise HTTPException(503, "OIDC authentication is not configured")
    if not settings.oidc_audience:
        raise HTTPException(503, "OIDC authentication is not configured")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 16384:
        raise unauthorized()
    try:
        header = jwt.get_unverified_header(token)
        if (
            header.get("alg") != "RS256"
            or not isinstance(header.get("kid"), str)
            or not header["kid"]
        ):
            raise unauthorized()
        key = jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWKClientConnectionError:
        raise HTTPException(503, "Identity provider is unavailable") from None
    except (jwt.PyJWTError, TypeError, ValueError):
        raise unauthorized() from None
    subject = claims["sub"]
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 40:
        raise unauthorized()
    if claims.get("typ", "Bearer") != "Bearer":
        raise unauthorized()
    realm_access = claims.get("realm_access", {})
    roles = realm_access.get("roles", []) if isinstance(realm_access, dict) else []
    if not isinstance(roles, list) or role not in roles:
        raise HTTPException(403, "Required role is missing")
    return claims


def token_identity(authorization: str, role: str) -> str:
    return token_claims(authorization, role)["sub"]
