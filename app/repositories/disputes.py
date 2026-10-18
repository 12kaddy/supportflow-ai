"""Customer-scoped reads and locks for conversational case management."""

from sqlalchemy import select

from app.models.entities import DisputeCase, Order

ACTIVE_STATUSES = ("awaiting_review", "awaiting_investigation", "approved")


async def lock_customer_order(db, order_id, customer_id):
    return await db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.customer_id == customer_id)
        .with_for_update()
    )


async def find_order_case(db, order_id, customer_id, active_only=False):
    query = select(DisputeCase).where(
        DisputeCase.order_id == order_id, DisputeCase.customer_id == customer_id
    )
    if active_only:
        query = query.where(DisputeCase.status.in_(ACTIVE_STATUSES))
    # Prefer active cases, then newest first. Deterministic for older duplicate cases.
    return await db.scalar(
        query.order_by(
            DisputeCase.status.in_(ACTIVE_STATUSES).desc(),
            DisputeCase.created_at.desc(),
            DisputeCase.id.desc(),
        ).limit(1)
    )
