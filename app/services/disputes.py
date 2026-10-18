"""Evidence snapshots and deterministic decisions for delivery disputes.

Customer statements are allegations, never carrier evidence. This service proposes
manual review only; it does not authorize or execute payments.
"""

from uuid import uuid4

from sqlalchemy import select

from app.models.entities import DeliveryEvidence, DisputeCase
from app.repositories.orders import get_order
from app.repositories.resolutions import record_event
from app.services.email_notifications import enable_verified_case_email

POLICY_VERSION = "delivery-dispute-v1"
POLICY_SOURCE = "delivery_dispute_policy.md"


def evaluate_dispute(order: dict, delivery: dict | None) -> dict:
    missing = []
    if order["status"] != "delivered":
        action, reason = "shipping_review", "Order is not marked delivered."
    elif order["days_since_delivery"] is None or order["days_since_delivery"] < 0:
        action, reason = "investigate", "A valid delivery age is required."
        missing.append("delivery_age")
    elif order["days_since_delivery"] > 7:
        action, reason = "escalate", "Dispute is outside the seven-day request window."
    elif delivery is None or delivery.get("proof_status") not in {"matched", "mismatched"}:
        action, reason = "investigate", "Delivery proof is missing or inconclusive."
        missing.append("verified_delivery_proof")
    elif delivery["proof_status"] == "mismatched":
        action, reason = "refund_review", "Delivery proof conflicts with the destination."
    else:
        action, reason = (
            "carrier_review",
            "Delivery proof matches; carrier investigation is required.",
        )
    return {
        "action": action,
        "reason": reason,
        "missing_information": missing,
        "requires_human_review": True,
        "payment_authorized": False,
        "policy_version": POLICY_VERSION,
        "policy_source": POLICY_SOURCE,
    }


async def open_dispute(db, order_id: str, customer_id: str, issue: str, verified_email=None):
    order = await get_order(db, order_id, customer_id)
    if order is None:
        return None
    evidence = await db.get(DeliveryEvidence, order_id)
    order_snapshot = {
        "id": order.id,
        "status": order.status,
        "amount_cents": order.amount_cents,
        "days_since_delivery": order.days_since_delivery,
    }
    delivery = (
        None
        if evidence is None
        else {
            "tracking_events": evidence.tracking_events,
            "proof_status": evidence.proof_status,
            "source": evidence.source,
        }
    )
    previous = (
        await db.scalars(
            select(DisputeCase)
            .where(DisputeCase.order_id == order_id, DisputeCase.customer_id == customer_id)
            .order_by(DisputeCase.created_at, DisputeCase.id)
        )
    ).all()
    decision = evaluate_dispute(order_snapshot, delivery)
    case = DisputeCase(
        id=str(uuid4()),
        order_id=order_id,
        customer_id=customer_id,
        issue=issue,
        status="awaiting_investigation" if decision["missing_information"] else "awaiting_review",
        investigation={
            "order": order_snapshot,
            "delivery": delivery,
            "previous_case_ids": [item.id for item in previous],
            "decision": decision,
        },
    )
    db.add(case)
    await db.flush()
    record_event(db, case.id, customer_id, "case_investigated", case.investigation)
    await enable_verified_case_email(db, case, verified_email)
    await db.commit()
    await db.refresh(case)
    return case


async def get_dispute(db, case_id: str, customer_id: str):
    return await db.scalar(
        select(DisputeCase).where(DisputeCase.id == case_id, DisputeCase.customer_id == customer_id)
    )


def serialize_case(case: DisputeCase) -> dict:
    return {
        "id": case.id,
        "order_id": case.order_id,
        "issue": case.issue,
        "status": case.status,
        "investigation": case.investigation,
        "created_at": case.created_at.isoformat(),
    }
