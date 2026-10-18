import argparse
import asyncio

from app.db.session import SessionLocal
from app.models.entities import DeliveryEvidence, Order


async def main(customer_id="demo-customer", prefix="ORD"):
    examples = [
        Order(
            id=f"{prefix}-1001",
            customer_id=customer_id,
            status="delivered",
            amount_cents=299900,
            days_since_delivery=3,
        ),
        Order(
            id=f"{prefix}-1002",
            customer_id=customer_id,
            status="shipped",
            amount_cents=159900,
            days_since_delivery=None,
        ),
        Order(
            id=f"{prefix}-1003",
            customer_id=customer_id,
            status="delivered",
            amount_cents=499900,
            days_since_delivery=14,
        ),
    ]
    async with SessionLocal() as db:
        for order in examples:
            existing = await db.get(Order, order.id)
            if existing and existing.customer_id != customer_id:
                raise ValueError("Order prefix belongs to another customer; choose a new prefix")
            if not existing:
                db.add(order)
        await db.commit()
        if not await db.get(DeliveryEvidence, f"{prefix}-1001"):
            db.add(
                DeliveryEvidence(
                    order_id=f"{prefix}-1001",
                    tracking_events=[{"event": "delivered", "source": "simulated-carrier"}],
                    proof_status="mismatched",
                    source="seeded-simulation",
                )
            )
        await db.commit()
    print("Demo orders seeded")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer-id", default="demo-customer")
    parser.add_argument("--order-prefix", default="ORD")
    args = parser.parse_args()
    if not args.customer_id.strip() or len(args.customer_id) > 40:
        parser.error("Customer ID must be between 1 and 40 characters")
    if not args.order_prefix.isalnum() or len(args.order_prefix) > 30:
        parser.error("Order prefix must be alphanumeric and no longer than 30 characters")
    asyncio.run(main(args.customer_id, args.order_prefix))
