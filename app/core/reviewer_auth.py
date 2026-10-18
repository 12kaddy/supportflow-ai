"""Reviewer identities come from server configuration, never request headers."""

import secrets

from fastapi import Header, HTTPException

from app.core.access_tokens import access_claims
from app.core.config import get_settings


def reviewer_identity(
    x_reviewer_key: str = Header(default=""), authorization: str = Header(default="")
) -> str:
    settings = get_settings()
    if settings.auth_mode != "demo":
        return access_claims(authorization, "reviewer")["sub"]
    for reviewer, key in settings.reviewer_api_keys.items():
        if (
            reviewer
            and key
            and x_reviewer_key
            and not secrets.compare_digest(key, settings.api_key)
            and secrets.compare_digest(x_reviewer_key, key)
        ):
            return reviewer
    raise HTTPException(403, "Valid reviewer credentials required")
