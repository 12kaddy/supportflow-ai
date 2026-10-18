"""In-memory tool fixtures for model behavior evaluation, never application data.

Persistence, locks, and authorization are covered by the integration suite. This
environment tests model selection of tools and communication of returned facts.
"""

import json

from langchain_core.tools import tool

from app.schemas.disputes import DisputeRequest
from app.services.customer_cases import NEXT_STEPS
from app.services.disputes import evaluate_dispute

CASE_ID = "CASE-EVAL-1001"
ORDER_ID = "ORD-1001"


def make_fixture_tools(scenario):
    state = {"status": scenario.existing_status}
    order = {"id": ORDER_ID, "status": "delivered", "amount_cents": 10000, "days_since_delivery": 3}
    decision = evaluate_dispute(order, {"proof_status": scenario.proof_status})

    def summary():
        status = state["status"]
        return {
            "case_id": CASE_ID,
            "order_id": ORDER_ID,
            "status": status,
            "proposed_action": decision["action"],
            "proposal_reason": decision["reason"],
            "missing_information": decision["missing_information"],
            "policy_version": decision["policy_version"],
            "policy_source": decision["policy_source"],
            "next_step": NEXT_STEPS[status],
            "notifications_enabled": False,
            "status_follow_up": "Ask for status here; automatic notifications are not available.",
            "review_decision": "approve"
            if status in {"approved", "resolved"}
            else "reject"
            if status == "rejected"
            else None,
            "approved_amount_cents": 10000 if status in {"approved", "resolved"} else None,
            "simulated_refund": {
                "id": "REFUND-EVAL-1001",
                "amount_cents": 10000,
                "status": "simulated",
            }
            if status == "resolved"
            else None,
            "real_payment_executed": False,
        }

    @tool
    def lookup_order(order_id: str) -> str:
        """Look up the authenticated customer's order by ID."""
        return json.dumps(
            order if scenario.order_owned and order_id == ORDER_ID else {"error": "Order not found"}
        )

    @tool(args_schema=DisputeRequest)
    def report_delivery_issue(order_id: str, issue: str) -> str:
        """Open a delivery dispute or reuse the customer's active case. Never authorizes refunds."""
        if not scenario.order_owned or order_id != ORDER_ID:
            return json.dumps({"error": "Order not found"})
        reused = state["status"] in {"awaiting_review", "awaiting_investigation", "approved"}
        if not reused:
            state["status"] = (
                "awaiting_investigation" if decision["missing_information"] else "awaiting_review"
            )
        return json.dumps({**summary(), "reused": reused})

    @tool
    def lookup_dispute(case_id: str) -> str:
        """Read the authenticated customer's current case status by case ID."""
        return json.dumps(
            summary()
            if scenario.order_owned and case_id == CASE_ID and state["status"]
            else {"error": "Case not found"}
        )

    @tool
    def lookup_order_dispute(order_id: str) -> str:
        """Find the authenticated customer's active or most recent case for an order."""
        if not scenario.order_owned or order_id != ORDER_ID:
            return json.dumps({"error": "Order not found"})
        return json.dumps(summary() if state["status"] else {"error": "Case not found"})

    @tool
    def find_policy(question: str) -> str:
        """Search official policy documents with versioned citations."""
        from app.rag.store import search_policy

        return json.dumps(search_policy(question, use_vectors=False))

    return [lookup_order, find_policy, report_delivery_issue, lookup_dispute, lookup_order_dispute]
