"""Chat case lifecycle and customer-facing handoff; no reviewer operations."""

from sqlalchemy import select

from app.core.config import get_settings
from app.models.notifications import EmailSubscription
from app.models.resolutions import CaseReview, SimulatedRefund
from app.repositories.disputes import find_order_case, lock_customer_order
from app.services.disputes import open_dispute
from app.services.email_notifications import enable_verified_case_email

NEXT_STEPS = {
    "awaiting_investigation": "Support must gather the missing evidence before a resolution can be decided.",
    "awaiting_review": "Your case is awaiting a support reviewer. The proposal is not an approved refund.",
    "approved": "A reviewer approved a simulated refund; execution is still pending with support.",
    "rejected": "The reviewer rejected this case. Contact support if you want the decision reconsidered.",
    "resolved": "The simulated resolution is complete. No money was moved.",
}


async def open_or_reuse_case(db, order_id, customer_id, issue, verified_email=None):
    # Serialize creation across chat threads for the same owned order. The lock is
    # held until open_dispute commits or the existing case is returned.
    order = await lock_customer_order(db, order_id, customer_id)
    if order is None:
        return None, False
    case = await find_order_case(db, order_id, customer_id, active_only=True)
    if case is not None:
        await enable_verified_case_email(db, case, verified_email)
        await db.commit()
        return case, True
    return await open_dispute(db, order_id, customer_id, issue, verified_email), False


async def customer_case_status(db, case):
    """Expose workflow facts without reviewer credentials or internal review notes."""
    decision = case.investigation["decision"]
    review = await db.get(CaseReview, case.id)
    refund = await db.scalar(select(SimulatedRefund).where(SimulatedRefund.case_id == case.id))
    settings = get_settings()
    subscription = await db.get(EmailSubscription, case.id) if settings.email_enabled else None
    subscribed = bool(
        subscription
        and subscription.enabled
        and subscription.delivery_mode == settings.email_delivery_mode
    )
    real_email = subscribed and settings.email_delivery_mode == "smtp"
    return {
        "case_id": case.id,
        "order_id": case.order_id,
        "status": case.status,
        "proposed_action": decision["action"],
        "proposal_reason": decision["reason"],
        "missing_information": decision["missing_information"],
        "policy_version": decision["policy_version"],
        "policy_source": decision["policy_source"],
        "next_step": NEXT_STEPS.get(case.status, "Contact support for the next step."),
        "review_decision": review.decision if review else None,
        "approved_amount_cents": review.amount_cents if review else None,
        "simulated_refund": None
        if refund is None
        else {
            "id": refund.id,
            "amount_cents": refund.amount_cents,
            "status": "simulated",
        },
        "real_payment_executed": False,
        "notifications_enabled": real_email,
        "email_delivery_mode": settings.email_delivery_mode if subscribed else None,
        "status_follow_up": (
            "Case email updates are enabled and queued on status changes; delivery is not guaranteed."
            if real_email
            else "Ask for your case status here. Local captured emails do not reach real inboxes."
            if subscribed
            else "Ask for your case status here; email updates are disabled or a verified account email is unavailable."
        ),
    }
