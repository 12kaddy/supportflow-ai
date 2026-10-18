import secrets

from fastapi import Header, HTTPException

from app.core.access_tokens import access_claims
from app.core.config import get_settings


def identity(
    x_api_key: str = Header(default=""),
    x_customer_id: str = Header(default=""),
    authorization: str = Header(default=""),
) -> str:
    settings = get_settings()
    if settings.auth_mode != "demo":
        return access_claims(authorization, "customer")["sub"]
    if not settings.api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not x_customer_id or len(x_customer_id) > 40:
        raise HTTPException(status_code=400, detail="X-Customer-ID required")
    # Demo only: X-Customer-ID is caller-supplied. Replace with JWT claims in production.
    return x_customer_id
