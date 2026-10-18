"""Real PostgreSQL row-lock tests, opted in with pytest --postgres.

Each test creates and drops only its own randomly named schema. Application data
and migration state in public are never modified.
"""

import asyncio
import json
import os
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.v1 import email_notifications, resolutions, routes
from app.core.config import get_settings
from app.db.base import Base
from app.models.entities import DeliveryEvidence, DisputeCase, Order
from app.models.notifications import EmailOutbox
from app.models.resolutions import CaseEvent, SimulatedRefund
from app.services.email_worker import deliver_one
from app.tools import customer_tools

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def postgres(request, monkeypatch):
    if not request.config.getoption("--postgres"):
        pytest.skip("Use --postgres to run real PostgreSQL concurrency tests")
    url = os.environ.get("SUPPORTFLOW_TEST_DATABASE_URL", get_settings().database_url)
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("PostgreSQL tests require a postgresql+asyncpg:// URL")
    schema = "test_concurrency_" + uuid4().hex
    engine = create_async_engine(
        url,
        connect_args={
            "timeout": 5,
            "server_settings": {
                "application_name": schema,
                "lock_timeout": "10000",
                "statement_timeout": "15000",
            },
        },
        execution_options={"schema_translate_map": {None: schema}},
    )
    created = False
    try:
        async with engine.begin() as connection:
            await connection.execute(CreateSchema(schema))
            created = True
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(routes, "SessionLocal", sessions)
        monkeypatch.setattr(resolutions, "SessionLocal", sessions)
        monkeypatch.setattr(customer_tools, "SessionLocal", sessions)
        monkeypatch.setattr(email_notifications, "SessionLocal", sessions)
        monkeypatch.setattr(get_settings(), "api_key", "test-customer-key")
        monkeypatch.setattr(get_settings(), "auth_mode", "demo")
        monkeypatch.setattr(get_settings(), "email_enabled", False)
        monkeypatch.setattr(
            get_settings(), "reviewer_api_keys", {"test-reviewer": "test-reviewer-key"}
        )
        async with sessions.begin() as db:
            db.add(
                Order(
                    id="order",
                    customer_id="test-customer",
                    status="delivered",
                    amount_cents=10000,
                    days_since_delivery=2,
                )
            )
            await db.flush()
            db.add(
                DeliveryEvidence(
                    order_id="order",
                    proof_status="mismatched",
                    tracking_events=[],
                    source="concurrency-test",
                )
            )
        app = FastAPI()
        app.include_router(routes.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=20
        ) as client:
            yield client, sessions, schema
    finally:
        try:
            if created:
                # Only this generated schema is removed, including its test records.
                async with engine.begin() as connection:
                    await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await engine.dispose()


async def approved_case(client):
    response = await client.post(
        "/v1/cases",
        headers={
            "X-API-Key": "test-customer-key",
            "X-Customer-ID": "test-customer",
        },
        json={"order_id": "order", "issue": "Delivered but not received"},
    )
    assert response.status_code == 201, response.text
    case_id = response.json()["id"]
    response = await client.post(
        f"/v1/reviewer/cases/{case_id}/review",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={"decision": "approve", "reason": "Verified proof", "amount_cents": 10000},
    )
    assert response.status_code == 200, response.text
    return case_id


async def execute_under_contention(client, sessions, schema, case_ids):
    requests = [
        client.post(
            f"/v1/reviewer/cases/{case_id}/execute",
            headers={"X-Reviewer-Key": "test-reviewer-key"},
        )
        for case_id in case_ids
    ]
    return await contend_for_order(sessions, schema, requests)


async def contend_for_order(sessions, schema, requests):
    """Hold the real order lock until every HTTP request is blocked on PostgreSQL."""
    tasks = []
    try:
        async with sessions.begin() as blocker:
            await blocker.scalar(select(Order).where(Order.id == "order").with_for_update())
            tasks = [asyncio.create_task(request) for request in requests]
            async with asyncio.timeout(8):
                while True:
                    # PostgreSQL caches statistics within the blocker's transaction.
                    await blocker.execute(text("SELECT pg_stat_clear_snapshot()"))
                    waiting = await blocker.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE application_name = :name AND wait_event_type = 'Lock'"
                        ),
                        {"name": schema},
                    )
                    if waiting == len(tasks):
                        break
                    for task in tasks:
                        if task.done():
                            task.result()
                            pytest.fail("Request finished before lock contention")
                    await asyncio.sleep(0.02)
        # Committing the blocker releases all contenders to the real lock protocol.
        return await asyncio.wait_for(asyncio.gather(*tasks), timeout=15)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("same_case", [True, False], ids=["same-case", "different-cases"])
async def test_concurrent_execution_creates_exactly_one_refund(postgres, same_case):
    client, sessions, schema = postgres
    first = await approved_case(client)
    second = first if same_case else await approved_case(client)
    responses = await execute_under_contention(client, sessions, schema, [first, second])
    assert sorted(r.status_code for r in responses) == ([200, 200] if same_case else [200, 409])
    successful = [r.json() for r in responses if r.status_code == 200]
    assert sum(not r["duplicate"] for r in successful) == 1
    if same_case:
        assert successful[0]["refund_id"] == successful[1]["refund_id"]
        assert sorted(r["duplicate"] for r in successful) == [False, True]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(SimulatedRefund)) == 1
        payment = await db.scalar(select(SimulatedRefund))
        assert payment.amount_cents == 10000
        events = (
            await db.scalars(select(CaseEvent).where(CaseEvent.kind == "refund_simulated"))
        ).all()
        assert len(events) == 1
        assert events[0].case_id == payment.case_id
        assert events[0].details["refund_id"] == payment.id
        states = (await db.scalars(select(DisputeCase.status))).all()
        assert sorted(states) == (["resolved"] if same_case else ["approved", "resolved"])


async def test_concurrent_chat_reports_reuse_one_active_case(postgres):
    _, sessions, schema = postgres
    tool = next(
        t for t in customer_tools.make_tools("test-customer") if t.name == "report_delivery_issue"
    )
    results = await contend_for_order(
        sessions,
        schema,
        [
            tool.ainvoke(
                {
                    "order_id": "order",
                    "issue": "Missing delivery",
                }
            )
            for _ in range(2)
        ],
    )
    cases = [json.loads(result) for result in results]
    assert cases[0]["case_id"] == cases[1]["case_id"]
    assert sorted(case["reused"] for case in cases) == [False, True]
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(DisputeCase)) == 1
        assert await db.scalar(select(func.count()).select_from(CaseEvent)) == 1


async def test_similar_case_query_uses_current_policy_on_postgres(postgres):
    client, sessions, _ = postgres
    target = await approved_case(client)
    async with sessions.begin() as db:
        db.add(
            Order(
                id="historical-order",
                customer_id="historical-customer",
                status="delivered",
                amount_cents=10000,
                days_since_delivery=2,
            )
        )
        await db.flush()
        db.add(
            DeliveryEvidence(
                order_id="historical-order",
                proof_status="mismatched",
                tracking_events=[],
                source="simulation",
            )
        )
    response = await client.post(
        "/v1/cases",
        headers={
            "X-API-Key": "test-customer-key",
            "X-Customer-ID": "historical-customer",
        },
        json={"order_id": "historical-order", "issue": "Not received"},
    )
    assert response.status_code == 201
    historical = response.json()["id"]
    path = f"/v1/reviewer/cases/{historical}"
    headers = {"X-Reviewer-Key": "test-reviewer-key"}
    assert (
        await client.post(
            path + "/review",
            headers=headers,
            json={
                "decision": "approve",
                "reason": "Evidence checked",
                "amount_cents": 10000,
            },
        )
    ).status_code == 200
    assert (await client.post(path + "/execute", headers=headers)).status_code == 200
    result = await client.get(f"/v1/reviewer/cases/{target}/similar", headers=headers)
    assert result.status_code == 200
    assert [item["reference_case_id"] for item in result.json()["items"]] == [historical]


async def test_email_workers_claim_a_queued_event_only_once(postgres, monkeypatch):
    client, sessions, _ = postgres
    monkeypatch.setattr(get_settings(), "email_enabled", True)
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "local")
    response = await client.post(
        "/v1/cases",
        headers={
            "X-API-Key": "test-customer-key",
            "X-Customer-ID": "test-customer",
        },
        json={"order_id": "order", "issue": "Not received"},
    )
    case_id = response.json()["id"]
    subscription = await client.put(
        f"/v1/cases/{case_id}/email-subscription",
        headers={
            "X-API-Key": "test-customer-key",
            "X-Customer-ID": "test-customer",
        },
        json={"enabled": True, "email": "test@example.test"},
    )
    assert subscription.status_code == 200
    assert (
        await client.post(
            f"/v1/reviewer/cases/{case_id}/review",
            headers={"X-Reviewer-Key": "test-reviewer-key"},
            json={"decision": "approve", "reason": "Verified", "amount_cents": 10000},
        )
    ).status_code == 200
    sent = []
    import threading

    entered, release = threading.Event(), threading.Event()

    def sender(row):
        entered.set()
        assert release.wait(5)
        sent.append(row.id)

    async def worker():
        async with sessions() as db:
            return await deliver_one(db, sender=sender)

    first = asyncio.create_task(worker())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert await worker() is False  # SKIP LOCKED: another worker owns the row.
    finally:
        release.set()
        await first
    assert len(sent) == 1
    async with sessions() as db:
        assert await db.scalar(select(EmailOutbox.status)) == "sent"
