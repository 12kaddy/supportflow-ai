from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1 import routes
from app.core.config import get_settings
from app.models.entities import utcnow
from app.models.notifications import EmailOutbox
from app.services.email_worker import deliver_one
from tests.helpers import APPROVE, CUSTOMER, REVIEWER, create_case


@pytest.fixture
def enabled(setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_enabled", True)
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "local")
    return setup


@pytest.mark.asyncio
async def test_opt_in_queue_worker_and_duplicate_execution(enabled):
    app, engine = enabled
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        subscription = f"/v1/cases/{case}/email-subscription"
        assert (
            await http.put(
                subscription,
                headers=CUSTOMER,
                json={"enabled": True, "email": "customer@example.test"},
            )
        ).status_code == 200
        base = f"/v1/reviewer/cases/{case}"
        assert (
            await http.post(base + "/review", headers=REVIEWER, json=APPROVE)
        ).status_code == 200
        assert (await http.post(base + "/execute", headers=REVIEWER)).status_code == 200
        assert (await http.post(base + "/execute", headers=REVIEWER)).json()["duplicate"] is True
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(EmailOutbox)) == 2
    deliveries = []
    async with routes.SessionLocal() as db:
        assert await deliver_one(db, sender=lambda row: deliveries.append(row.kind)) is True
    async with routes.SessionLocal() as db:
        assert await deliver_one(db, sender=lambda row: deliveries.append(row.kind)) is True
    assert sorted(deliveries) == ["case_approved", "case_resolved"]
    with Session(engine) as db:
        assert set(db.scalars(select(EmailOutbox.status))) == {"sent"}


@pytest.mark.asyncio
async def test_preference_ownership_and_unsubscribe_before_send(enabled):
    app, engine = enabled
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        endpoint = f"/v1/cases/{case}/email-subscription"
        bob = {**CUSTOMER, "X-Customer-ID": "bob"}
        assert (
            await http.put(
                endpoint, headers=bob, json={"enabled": True, "email": "bob@example.test"}
            )
        ).status_code == 404
        assert (
            await http.put(
                endpoint,
                headers=CUSTOMER,
                json={"enabled": True, "email": "bad\r\nBcc: victim@example.test"},
            )
        ).status_code == 422
        await http.put(
            endpoint, headers=CUSTOMER, json={"enabled": True, "email": "alice@example.test"}
        )
        assert (
            await http.post(
                f"/v1/reviewer/cases/{case}/review",
                headers=REVIEWER,
                json={"decision": "reject", "reason": "Review complete"},
            )
        ).status_code == 200
        await http.put(endpoint, headers=CUSTOMER, json={"enabled": False})
    deliveries = []
    async with routes.SessionLocal() as db:
        assert await deliver_one(db, sender=lambda row: deliveries.append(row.id))
    assert deliveries == []
    with Session(engine) as db:
        assert db.scalar(select(EmailOutbox.status)) == "skipped"


@pytest.mark.asyncio
async def test_smtp_failures_retry_without_exposing_addresses(enabled):
    app, engine = enabled
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        await http.put(
            f"/v1/cases/{case}/email-subscription",
            headers=CUSTOMER,
            json={"enabled": True, "email": "alice@example.test"},
        )
        await http.post(f"/v1/reviewer/cases/{case}/review", headers=REVIEWER, json=APPROVE)

    def failed(row):
        raise OSError("private-smtp-address-and-secret")

    for attempt in range(5):
        with Session(engine) as db:
            row = db.scalar(select(EmailOutbox))
            row.next_attempt_at = utcnow() - timedelta(seconds=1)
            db.commit()
        async with routes.SessionLocal() as db:
            assert await deliver_one(db, sender=failed)
    with Session(engine) as db:
        row = db.scalar(select(EmailOutbox))
        assert row.status == "failed" and row.attempts == 5
        assert row.last_error_type == "OSError"


@pytest.mark.asyncio
async def test_external_email_cannot_use_unverified_demo_address(enabled, monkeypatch):
    app, _ = enabled
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "smtp")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        response = await http.put(
            f"/v1/cases/{case}/email-subscription",
            headers=CUSTOMER,
            json={"enabled": True, "email": "thirdparty@example.test"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_switching_to_real_smtp_never_sends_old_local_test_mail(enabled, monkeypatch):
    app, engine = enabled
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        await http.put(
            f"/v1/cases/{case}/email-subscription",
            headers=CUSTOMER,
            json={"enabled": True, "email": "alice@example.test"},
        )
        await http.post(f"/v1/reviewer/cases/{case}/review", headers=REVIEWER, json=APPROVE)
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "smtp")
    delivered = []
    async with routes.SessionLocal() as db:
        assert await deliver_one(db, sender=lambda row: delivered.append(row.id))
    assert delivered == []
    with Session(engine) as db:
        assert db.scalar(select(EmailOutbox.status)) == "skipped"


@pytest.mark.asyncio
async def test_queued_email_rolls_back_with_failed_review(enabled, monkeypatch):
    from app.models.entities import DisputeCase
    from app.models.resolutions import CaseReview
    from app.services import resolutions

    app, engine = enabled
    original = resolutions.enqueue_case_email

    async def fail_after_enqueue(db, case, kind):
        await original(db, case, kind)
        await db.flush()
        raise RuntimeError("Simulated transaction failure")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        await http.put(
            f"/v1/cases/{case}/email-subscription",
            headers=CUSTOMER,
            json={"enabled": True, "email": "alice@example.test"},
        )
        monkeypatch.setattr(resolutions, "enqueue_case_email", fail_after_enqueue)
        with pytest.raises(RuntimeError, match="transaction failure"):
            await http.post(f"/v1/reviewer/cases/{case}/review", headers=REVIEWER, json=APPROVE)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(EmailOutbox)) == 0
        assert db.get(CaseReview, case) is None
        assert db.get(DisputeCase, case).status == "awaiting_review"
