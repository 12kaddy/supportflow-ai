"""Shared access-token dispatch for supported account providers."""

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.local_tokens import local_claims
from app.core.oidc import token_claims


def access_claims(authorization, role):
    mode = get_settings().auth_mode
    if mode == "local":
        return local_claims(authorization, role)
    if mode == "oidc":
        return token_claims(authorization, role)
    raise HTTPException(403, "A verified account session is required")
