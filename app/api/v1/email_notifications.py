from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.core.access_tokens import access_claims
from app.core.config import get_settings
from app.core.security import identity
from app.db.session import SessionLocal
from app.models.entities import DisputeCase, utcnow
from app.models.notifications import EmailSubscription
from app.repositories.resolutions import record_event
from app.schemas.email_address import validate_address

router = APIRouter(prefix="/cases", tags=["email"])


class SubscriptionRequest(BaseModel):
    enabled: bool
    email: str | None = Field(default=None, max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        return validate_address(value) if value is not None else None


async def owned_case(db, case_id, customer_id, lock=False):
    query = select(DisputeCase).where(
        DisputeCase.id == case_id, DisputeCase.customer_id == customer_id
    )
    case = await db.scalar(query.with_for_update() if lock else query)
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


@router.get("/{case_id}/email-subscription")
async def subscription(case_id: str, customer_id=Depends(identity)):
    async with SessionLocal() as db:
        await owned_case(db, case_id, customer_id)
        row = await db.get(EmailSubscription, case_id)
        return {
            "enabled": bool(
                row and row.enabled and row.delivery_mode == get_settings().email_delivery_mode
            ),
            "email": row.recipient if row else None,
            "delivery_mode": get_settings().email_delivery_mode,
            "service_enabled": get_settings().email_enabled,
        }


@router.put("/{case_id}/email-subscription")
async def subscribe(
    case_id: str,
    body: SubscriptionRequest,
    customer_id=Depends(identity),
    authorization: str = Header(default=""),
):
    settings = get_settings()
    if body.enabled and not settings.email_enabled:
        raise HTTPException(503, "Email notifications are disabled")
    recipient = body.email
    if body.enabled and settings.email_delivery_mode == "smtp":
        if settings.auth_mode not in {"oidc", "local"}:
            raise HTTPException(403, "External email requires a verified account address")
        claims = access_claims(authorization, "customer")
        if claims.get("email_verified") is not True:
            raise HTTPException(403, "Verify your email with the identity provider first")
        try:
            verified = validate_address(claims.get("email"))
        except ValueError:
            raise HTTPException(403, "Verified email address required") from None
        if recipient is not None and recipient != verified:
            raise HTTPException(403, "Use your verified email address")
        recipient = verified
    if body.enabled and not recipient:
        raise HTTPException(422, "Email address required for local capture")
    async with SessionLocal() as db:
        async with db.begin():
            await owned_case(db, case_id, customer_id, lock=True)
            row = await db.get(EmailSubscription, case_id)
            if row is None and body.enabled:
                row = EmailSubscription(
                    case_id=case_id,
                    customer_id=customer_id,
                    recipient=recipient,
                    delivery_mode=settings.email_delivery_mode,
                )
                db.add(row)
            if row is not None:
                row.enabled = body.enabled
                row.updated_at = utcnow()
                if body.enabled:
                    row.recipient = recipient
                    row.delivery_mode = settings.email_delivery_mode
            record_event(
                db, case_id, customer_id, "email_preference_changed", {"enabled": body.enabled}
            )
    return {"enabled": body.enabled, "delivery_mode": settings.email_delivery_mode}
