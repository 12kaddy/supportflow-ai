"""Bounded reads of completed, reviewed simulations under the current policy."""

from sqlalchemy import select

from app.models.entities import DisputeCase
from app.models.resolutions import CaseReview, SimulatedRefund


async def resolved_candidates(db, target, policy_version, limit=200):
    query = (
        select(DisputeCase)
        .join(CaseReview, CaseReview.case_id == DisputeCase.id)
        .join(SimulatedRefund, SimulatedRefund.case_id == DisputeCase.id)
        .where(
            DisputeCase.status == "resolved",
            DisputeCase.order_id != target.order_id,
            CaseReview.decision == "approve",
            SimulatedRefund.order_id == DisputeCase.order_id,
            SimulatedRefund.amount_cents == CaseReview.amount_cents,
            DisputeCase.investigation["decision"]["policy_version"].as_string() == policy_version,
        )
        .order_by(SimulatedRefund.created_at.desc(), DisputeCase.id.desc())
        .limit(limit + 1)
    )
    rows = (await db.scalars(query)).all()
    return rows[:limit], len(rows) > limit
