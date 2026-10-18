from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Order, Refund
from app.models.resolutions import SimulatedRefund


async def get_order(db: AsyncSession, order_id: str, customer_id: str):
    return await db.scalar(
        select(Order).where(Order.id == order_id, Order.customer_id == customer_id)
    )


async def request_refund(db: AsyncSession, order_id: str, customer_id: str):
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.customer_id == customer_id)
        .with_for_update()
    )
    if order is None:
        return {"error": "Order not found"}
    if await db.scalar(select(SimulatedRefund.id).where(SimulatedRefund.order_id == order_id)):
        return {"error": "Order already has a simulated refund"}
    if (
        order.status != "delivered"
        or order.days_since_delivery is None
        or order.days_since_delivery > 7
    ):
        return {"error": "Not eligible for automatic refund; review policy or contact support"}
    existing = await db.scalar(select(Refund).where(Refund.order_id == order_id))
    if existing:
        return {"refund_id": existing.id, "status": existing.status, "duplicate": True}
    refund = Refund(order_id=order_id, customer_id=customer_id, status="requested")
    db.add(refund)
    await db.commit()
    await db.refresh(refund)
    return {"refund_id": refund.id, "status": refund.status}
