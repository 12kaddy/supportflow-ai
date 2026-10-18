from sqlalchemy import select

from app.models.entities import DisputeCase, Order
from app.models.resolutions import CaseEvent


async def lock_case(db, case_id):
    case = await db.get(DisputeCase, case_id)
    if case is None:
        return None, None
    # Shared order lock serializes actions even across different cases for one order.
    order = await db.scalar(select(Order).where(Order.id == case.order_id).with_for_update())
    case = await db.scalar(
        select(DisputeCase)
        .where(DisputeCase.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return case, order


def record_event(db, case_id, actor, kind, details):
    db.add(CaseEvent(case_id=case_id, actor=actor, kind=kind, details=details))


async def list_events(db, case_id):
    rows = await db.scalars(
        select(CaseEvent).where(CaseEvent.case_id == case_id).order_by(CaseEvent.id)
    )
    return [
        {
            "id": e.id,
            "actor": e.actor,
            "kind": e.kind,
            "details": e.details,
            "created_at": e.created_at.isoformat(),
        }
        for e in rows
    ]


async def list_cases(db, status, limit, offset):
    query = select(DisputeCase)
    if status is not None:
        query = query.where(DisputeCase.status == status)
    rows = (
        await db.scalars(
            query.order_by(DisputeCase.created_at.desc(), DisputeCase.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    ).all()
    return rows[:limit], len(rows) > limit
