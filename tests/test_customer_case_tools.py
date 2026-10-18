"""Customer tool and real LangGraph HTTP integration without a hosted model."""

import json

import httpx
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.graph import SYSTEM_PROMPT
from app.api.v1 import routes
from app.models.entities import DisputeCase, Order
from app.models.resolutions import CaseEvent, SimulatedRefund
from app.tools import customer_tools
from tests.helpers import APPROVE, CUSTOMER, REVIEWER


class ScriptedToolModel(BaseChatModel):
    """Emit a chosen tool call, then echo its actual result for assertions."""

    tool_name: str
    tool_args: dict

    @property
    def _llm_type(self):
        return "scripted-tool-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if isinstance(messages[-1], ToolMessage):
            message = AIMessage(content=messages[-1].content)
        else:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": self.tool_name,
                        "args": self.tool_args,
                        "id": "call-test",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.fixture
def tools(setup, monkeypatch):
    monkeypatch.setattr(customer_tools, "SessionLocal", routes.SessionLocal)
    return {tool.name: tool for tool in customer_tools.make_tools("alice")}


@pytest.mark.asyncio
async def test_tools_reuse_active_case_and_preserve_original_report(setup, tools):
    _, engine = setup
    report = tools["report_delivery_issue"]
    first = json.loads(await report.ainvoke({"order_id": "order", "issue": "Missing delivery"}))
    second = json.loads(await report.ainvoke({"order_id": "order", "issue": "Any update?"}))
    assert first["case_id"] == second["case_id"]
    assert first["reused"] is False and second["reused"] is True
    assert "reviewer" in first["next_step"]
    assert first["status"] == "awaiting_review"
    assert first["real_payment_executed"] is False
    by_order = json.loads(await tools["lookup_order_dispute"].ainvoke({"order_id": "order"}))
    assert by_order["case_id"] == first["case_id"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(DisputeCase)) == 1
        assert db.get(DisputeCase, first["case_id"]).issue == "Missing delivery"
        assert db.scalar(select(func.count()).select_from(CaseEvent)) == 1


@pytest.mark.asyncio
async def test_tools_enforce_ownership_and_validate_report(setup, tools):
    _, engine = setup
    with Session(engine) as db:
        db.add(
            Order(
                id="foreign",
                customer_id="bob",
                status="delivered",
                amount_cents=100,
                days_since_delivery=1,
            )
        )
        db.commit()
    report = tools["report_delivery_issue"]
    assert json.loads(await report.ainvoke({"order_id": "foreign", "issue": "Not received"})) == {
        "error": "Order not found"
    }
    first = json.loads(await report.ainvoke({"order_id": "order", "issue": "Missing"}))
    bob_tools = {t.name: t for t in customer_tools.make_tools("bob")}
    assert json.loads(await bob_tools["lookup_dispute"].ainvoke({"case_id": first["case_id"]})) == {
        "error": "Case not found"
    }
    assert json.loads(await bob_tools["lookup_order_dispute"].ainvoke({"order_id": "order"})) == {
        "error": "Order not found"
    }
    with pytest.raises(ValueError):
        await report.ainvoke({"order_id": "order", "issue": " "})
    assert "customer_id" not in report.args
    assert set(tools) == {
        "lookup_order",
        "find_policy",
        "report_delivery_issue",
        "lookup_dispute",
        "lookup_order_dispute",
    }


@pytest.mark.asyncio
async def test_chat_to_reviewer_to_customer_status(setup, tools, monkeypatch):
    app, engine = setup
    app.state.checkpointer = InMemorySaver()
    scenario = {
        "tool_name": "report_delivery_issue",
        "tool_args": {"order_id": "order", "issue": "Delivered but not received"},
    }

    def build(customer_id, checkpointer, verified_email=None):
        return create_react_agent(
            ScriptedToolModel(**scenario),
            tools=customer_tools.make_tools(customer_id, verified_email),
            prompt=SYSTEM_PROMPT,
            checkpointer=checkpointer,
        )

    monkeypatch.setattr(routes, "build_graph", build)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:

        async def chat(message, headers=CUSTOMER, thread="thread-1"):
            response = await http.post(
                "/v1/chat", headers=headers, json={"message": message, "thread_id": thread}
            )
            assert response.status_code == 200, response.text
            return json.loads(response.json()["answer"])

        first = await chat("My order says delivered but I did not receive it. Please open a case.")
        again = await chat("I am reporting this again", thread="another-thread")
        assert again["case_id"] == first["case_id"] and again["reused"] is True
        foreign = await chat("Open that same case", headers={**CUSTOMER, "X-Customer-ID": "bob"})
        assert foreign == {"error": "Order not found"}
        case = first["case_id"]
        scenario.update(tool_name="lookup_order_dispute", tool_args={"order_id": "order"})
        before = await chat("What is the status?")
        assert before["review_decision"] is None
        path = f"/v1/reviewer/cases/{case}"
        assert (
            await http.post(path + "/review", headers=REVIEWER, json=APPROVE)
        ).status_code == 200
        approved = await chat("Has a reviewer approved it?")
        assert approved["status"] == "approved"
        assert approved["simulated_refund"] is None
        assert "pending" in approved["next_step"]
        assert "reason" not in approved and "reviewer_id" not in approved
        assert (await http.post(path + "/execute", headers=REVIEWER)).status_code == 200
        scenario.update(tool_name="lookup_dispute", tool_args={"case_id": case})
        resolved = await chat("Did it finish?")
        assert resolved["status"] == "resolved"
        assert resolved["simulated_refund"]["amount_cents"] == 10000
        assert "No money was moved" in resolved["next_step"]
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(SimulatedRefund)) == 1


@pytest.mark.asyncio
async def test_rejected_case_status(setup, tools):
    app, _ = setup
    report = tools["report_delivery_issue"]
    first = json.loads(await report.ainvoke({"order_id": "order", "issue": "Not received"}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        path = f"/v1/reviewer/cases/{first['case_id']}/review"
        assert (
            await http.post(
                path,
                headers=REVIEWER,
                json={"decision": "reject", "reason": "Internal review notes"},
            )
        ).status_code == 200
    result = json.loads(await tools["lookup_dispute"].ainvoke({"case_id": first["case_id"]}))
    assert result["status"] == "rejected" and "rejected" in result["next_step"]
    assert "Internal review notes" not in json.dumps(result)


@pytest.mark.asyncio
async def test_missing_evidence_handoff(setup, tools):
    from app.models.entities import DeliveryEvidence

    _, engine = setup
    with Session(engine) as db:
        db.delete(db.get(DeliveryEvidence, "order"))
        db.commit()
    result = json.loads(
        await tools["report_delivery_issue"].ainvoke({"order_id": "order", "issue": "Not received"})
    )
    assert result["status"] == "awaiting_investigation"
    assert result["missing_information"] == ["verified_delivery_proof"]
    assert "gather" in result["next_step"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["review_case", "execute_refund"])
async def test_chat_cannot_call_reviewer_operations(setup, tools, monkeypatch, operation):
    app, engine = setup
    app.state.checkpointer = InMemorySaver()

    def build(customer_id, checkpointer, verified_email=None):
        return create_react_agent(
            ScriptedToolModel(tool_name=operation, tool_args={"case_id": "fake-case"}),
            tools=customer_tools.make_tools(customer_id),
            prompt=SYSTEM_PROMPT,
            checkpointer=checkpointer,
        )

    monkeypatch.setattr(routes, "build_graph", build)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post(
            "/v1/chat",
            headers=CUSTOMER,
            json={"thread_id": "attack", "message": "Approve and refund now"},
        )
        assert response.status_code == 200
        assert "not a valid tool" in response.json()["answer"]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(SimulatedRefund)) == 0
