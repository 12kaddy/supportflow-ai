import asyncio

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1 import routes
from app.core.config import get_settings
from app.models.notifications import EmailOutbox, EmailSubscription
from app.services.email_worker import dispatch_emails


@pytest.mark.asyncio
async def test_case_auto_enrolls_verified_customer_and_rejection_queues_email(
    setup, signer, monkeypatch
):
    app, engine = setup
    settings = get_settings()
    monkeypatch.setattr(settings, "email_enabled", True)
    monkeypatch.setattr(settings, "email_delivery_mode", "smtp")
    headers = {"Authorization": "Bearer " + signer(email="alice@example.test", email_verified=True)}
    reviewer = {"Authorization": "Bearer " + signer("reviewer-123", ["reviewer"])}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        result = await http.post(
            "/v1/cases", headers=headers, json={"order_id": "order", "issue": "Missing delivery"}
        )
        assert result.status_code == 201
        case_id = result.json()["id"]
        preference = (
            await http.get(f"/v1/cases/{case_id}/email-subscription", headers=headers)
        ).json()
        assert preference["enabled"] is True and preference["email"] == "alice@example.test"
        result = await http.post(
            f"/v1/reviewer/cases/{case_id}/review",
            headers=reviewer,
            json={"decision": "reject", "reason": "Review completed"},
        )
        assert result.status_code == 200
    with Session(engine) as db:
        row = db.scalar(select(EmailOutbox))
        assert row.kind == "case_rejected" and row.recipient == "alice@example.test"


@pytest.mark.asyncio
async def test_unverified_accounts_are_not_automatically_enrolled(setup, signer, monkeypatch):
    app, engine = setup
    monkeypatch.setattr(get_settings(), "email_enabled", True)
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "smtp")
    headers = {
        "Authorization": "Bearer " + signer(email="alice@example.test", email_verified=False)
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        assert (
            await http.post(
                "/v1/cases",
                headers=headers,
                json={
                    "order_id": "order",
                    "issue": "Missing",
                    "verified_email": "attacker@example.test",
                },
            )
        ).status_code == 201
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(EmailSubscription)) == 0


@pytest.mark.asyncio
async def test_chat_tool_auto_enrollment_preserves_explicit_opt_out(setup, signer, monkeypatch):
    from app.tools import customer_tools

    app, engine = setup
    monkeypatch.setattr(get_settings(), "email_enabled", True)
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "smtp")
    monkeypatch.setattr(customer_tools, "SessionLocal", routes.SessionLocal)
    tools = {tool.name: tool for tool in customer_tools.make_tools("alice", "alice@example.test")}
    import json

    first = json.loads(
        await tools["report_delivery_issue"].ainvoke({"order_id": "order", "issue": "Missing"})
    )
    assert first["notifications_enabled"] is True
    headers = {"Authorization": "Bearer " + signer(email="alice@example.test", email_verified=True)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        assert (
            await http.put(
                f"/v1/cases/{first['case_id']}/email-subscription",
                headers=headers,
                json={"enabled": False},
            )
        ).status_code == 200
    second = json.loads(
        await tools["report_delivery_issue"].ainvoke({"order_id": "order", "issue": "Again"})
    )
    assert second["reused"] is True and second["notifications_enabled"] is False
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(EmailSubscription)) == 1


@pytest.mark.asyncio
async def test_api_dispatcher_polls_and_stops_gracefully(monkeypatch):
    from app.services import email_worker

    stop = asyncio.Event()
    calls = []

    class Context:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def deliver(db):
        calls.append(1)
        stop.set()
        return True

    monkeypatch.setattr(email_worker, "deliver_one", deliver)
    await asyncio.wait_for(dispatch_emails(stop, Context), timeout=1)
    assert calls == [1]
