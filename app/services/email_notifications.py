"""Opt-in notifications queued inside the case transition's transaction."""

from uuid import uuid4

from app.core.config import get_settings
from app.models.notifications import EmailOutbox, EmailSubscription
from app.repositories.resolutions import record_event


async def enable_verified_case_email(db, case, verified_email):
    settings = get_settings()
    if not (
        verified_email
        and settings.email_enabled
        and settings.email_delivery_mode == "smtp"
        and settings.auth_mode in {"oidc", "local"}
    ):
        return
    # An existing preference, including an explicit opt-out, always wins.
    if await db.get(EmailSubscription, case.id) is not None:
        return
    db.add(
        EmailSubscription(
            case_id=case.id,
            customer_id=case.customer_id,
            recipient=verified_email,
            delivery_mode="smtp",
            enabled=True,
        )
    )
    record_event(
        db,
        case.id,
        case.customer_id,
        "email_preference_initialized",
        {"enabled": True, "source": "verified_account"},
    )


async def enqueue_case_email(db, case, kind):
    if not get_settings().email_enabled:
        return
    subscription = await db.get(EmailSubscription, case.id)
    if (
        subscription
        and subscription.enabled
        and subscription.customer_id == case.customer_id
        and subscription.delivery_mode == get_settings().email_delivery_mode
    ):
        db.add(
            EmailOutbox(
                id=str(uuid4()),
                case_id=case.id,
                customer_id=case.customer_id,
                recipient=subscription.recipient,
                kind=kind,
                delivery_mode=subscription.delivery_mode,
            )
        )
