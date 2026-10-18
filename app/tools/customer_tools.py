import json

from langchain_core.tools import tool

from app.db.session import SessionLocal
from app.repositories.disputes import find_order_case
from app.repositories.orders import get_order
from app.schemas.disputes import DisputeRequest
from app.services.customer_cases import customer_case_status, open_or_reuse_case
from app.services.disputes import get_dispute


# Identity is bound by the API, never supplied as a tool argument.
def make_tools(customer_id: str, verified_email=None):
    @tool
    async def lookup_order(order_id: str) -> str:
        """Look up an order by its identifier for the authenticated customer."""
        async with SessionLocal() as db:
            order = await get_order(db, order_id, customer_id)
            if order is None:
                return json.dumps({"error": "Order not found"})
            return json.dumps(
                {
                    "id": order.id,
                    "status": order.status,
                    "amount_cents": order.amount_cents,
                    "days_since_delivery": order.days_since_delivery,
                }
            )

    @tool
    def find_policy(question: str) -> str:
        """Search the official refund, shipping and cancellation policy documents."""
        from app.rag.store import search_policy

        return json.dumps(search_policy(question))

    @tool(args_schema=DisputeRequest)
    async def report_delivery_issue(order_id: str, issue: str) -> str:
        """Open a support dispute when the customer reports a delivery problem.

        Use the customer's order ID and a factual summary of their report. Reuses
        an active case for that order. Does not approve or execute any resolution.
        """
        async with SessionLocal() as db:
            case, reused = await open_or_reuse_case(
                db, order_id, customer_id, issue, verified_email
            )
            if case is None:
                return json.dumps({"error": "Order not found"})
            return json.dumps({**await customer_case_status(db, case), "reused": reused})

    @tool
    async def lookup_dispute(case_id: str) -> str:
        """Read this customer's current case status by case ID. Proposals are not approval."""
        async with SessionLocal() as db:
            case = await get_dispute(db, case_id, customer_id)
            return json.dumps(
                await customer_case_status(db, case) if case else {"error": "Case not found"}
            )

    @tool
    async def lookup_order_dispute(order_id: str) -> str:
        """Find this customer's active case or most recent closed case for an order.

        Use for status questions when the customer knows the order ID, not the case ID.
        """
        async with SessionLocal() as db:
            if await get_order(db, order_id, customer_id) is None:
                return json.dumps({"error": "Order not found"})
            case = await find_order_case(db, order_id, customer_id)
            return json.dumps(
                await customer_case_status(db, case) if case else {"error": "Case not found"}
            )

    return [lookup_order, find_policy, report_delivery_issue, lookup_dispute, lookup_order_dispute]
