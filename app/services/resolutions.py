"""Transactional review and simulated execution. No payment provider is called."""

from uuid import uuid4

from sqlalchemy import select

from app.models.entities import DeliveryEvidence, Refund
from app.models.resolutions import CaseReview, SimulatedRefund
from app.repositories.resolutions import lock_case, record_event
from app.services.disputes import POLICY_VERSION, evaluate_dispute
from app.services.email_notifications import enqueue_case_email


class ResolutionError(Exception):
    def __init__(self, message, status=409):
        self.status = status
        super().__init__(message)


async def validate_refund(db, case, order, amount):
    evidence = await db.get(DeliveryEvidence, order.id)
    current = evaluate_dispute(
        {"status": order.status, "days_since_delivery": order.days_since_delivery},
        {"proof_status": evidence.proof_status} if evidence else None,
    )
    proposal = case.investigation["decision"]
    if (
        order.customer_id != case.customer_id
        or proposal.get("policy_version") != POLICY_VERSION
        or proposal.get("action") != "refund_review"
        or current["action"] != "refund_review"
    ):
        raise ResolutionError("Case requires a current, eligible refund proposal")
    if amount is None or not 0 < amount <= order.amount_cents:
        raise ResolutionError("Amount must be positive and within the order total", 422)
    if await db.scalar(select(Refund.id).where(Refund.order_id == order.id)):
        raise ResolutionError("Order already has a legacy refund request; reconcile manually")


async def review_case(db, case_id, reviewer, body):
    async with db.begin():
        case, order = await lock_case(db, case_id)
        if case is None:
            raise ResolutionError("Case not found", 404)
        if case.status not in {"awaiting_review", "awaiting_investigation"}:
            raise ResolutionError("Case already reviewed")
        if body.decision == "approve":
            await validate_refund(db, case, order, body.amount_cents)
            if await db.scalar(
                select(SimulatedRefund.id).where(SimulatedRefund.order_id == order.id)
            ):
                raise ResolutionError("Order already refunded")
        db.add(
            CaseReview(
                case_id=case_id,
                reviewer_id=reviewer,
                decision=body.decision,
                reason=body.reason,
                amount_cents=body.amount_cents,
            )
        )
        case.status = "approved" if body.decision == "approve" else "rejected"
        record_event(db, case_id, reviewer, "review_recorded", body.model_dump())
        await enqueue_case_email(
            db, case, "case_approved" if body.decision == "approve" else "case_rejected"
        )
    return {"case_id": case_id, "status": case.status}


async def execute_refund(db, case_id, reviewer):
    async with db.begin():
        case, order = await lock_case(db, case_id)
        if case is None:
            raise ResolutionError("Case not found", 404)
        review = await db.get(CaseReview, case_id)
        if review is None or review.decision != "approve":
            raise ResolutionError("Approved review required")
        existing = await db.scalar(
            select(SimulatedRefund).where(SimulatedRefund.order_id == order.id)
        )
        if existing:
            if existing.case_id != case_id:
                raise ResolutionError("Order already refunded through another case")
            return refund_result(existing, duplicate=True)
        if case.status != "approved":
            raise ResolutionError("Case is not approved")
        await validate_refund(db, case, order, review.amount_cents)
        payment = SimulatedRefund(
            id=str(uuid4()), order_id=order.id, case_id=case_id, amount_cents=review.amount_cents
        )
        db.add(payment)
        case.status = "resolved"
        record_event(db, case_id, reviewer, "refund_simulated", refund_result(payment))
        await enqueue_case_email(db, case, "case_resolved")
    return refund_result(payment)


def refund_result(payment, duplicate=False):
    return {
        "refund_id": payment.id,
        "case_id": payment.case_id,
        "amount_cents": payment.amount_cents,
        "status": "simulated",
        "duplicate": duplicate,
    }
