"""Optional verified contact bound to the authenticated customer, never tool input."""

from fastapi import Depends, Header

from app.core.access_tokens import access_claims
from app.core.config import get_settings
from app.core.security import identity
from app.schemas.email_address import validate_address


def customer_email(customer_id: str = Depends(identity), authorization: str = Header(default="")):
    settings = get_settings()
    if not (
        settings.email_enabled
        and settings.email_delivery_mode == "smtp"
        and settings.auth_mode in {"oidc", "local"}
    ):
        return None
    claims = access_claims(authorization, "customer")
    if claims["sub"] != customer_id or claims.get("email_verified") is not True:
        return None
    try:
        return validate_address(claims.get("email"))
    except ValueError:
        return None
