"""HTTP integration tests with real SQL persistence and no external services."""

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import DeliveryEvidence, Refund
from app.models.resolutions import CaseEvent, CaseReview, SimulatedRefund
from tests.helpers import APPROVE, CUSTOMER, REVIEWER, create_case


@pytest.mark.asyncio
async def test_authorization_execution_and_audit(setup):
    app, engine = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        path = f"/v1/reviewer/cases/{case}"
        for headers in [{}, CUSTOMER, {"X-Reviewer-Key": "customer-secret"}]:
            assert (
                await http.post(path + "/review", headers=headers, json=APPROVE)
            ).status_code == 403
            assert (await http.post(path + "/execute", headers=headers)).status_code == 403
            assert (await http.get(path + "/audit", headers=headers)).status_code == 403
        assert (await http.post(path + "/execute", headers=REVIEWER)).status_code == 409
        assert (
            await http.post(path + "/review", headers=REVIEWER, json=APPROVE)
        ).status_code == 200
        assert (
            await http.post(path + "/review", headers=REVIEWER, json=APPROVE)
        ).status_code == 409
        first = await http.post(path + "/execute", headers=REVIEWER)
        assert first.status_code == 200, first.text
        second = await http.post(path + "/execute", headers=REVIEWER)
        assert second.json()["duplicate"] is True
        assert first.json()["refund_id"] == second.json()["refund_id"]
        events = (await http.get(path + "/audit", headers=REVIEWER)).json()["events"]
        assert [e["kind"] for e in events] == [
            "case_investigated",
            "review_recorded",
            "refund_simulated",
        ]
        assert events[1]["actor"] == "reviewer-1"
        assert events[1]["details"]["amount_cents"] == 10000
        assert all(e["created_at"] for e in events)
        assert (await http.get(f"/v1/cases/{case}", headers=CUSTOMER)).json()[
            "status"
        ] == "resolved"
        assert (
            await http.post(
                "/v1/refunds", headers=CUSTOMER, json={"order_id": "order", "confirm": True}
            )
        ).status_code == 400
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(SimulatedRefund)) == 1


@pytest.mark.asyncio
async def test_rejection_amounts_and_changed_evidence(setup):
    app, engine = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        path = f"/v1/reviewer/cases/{case}"
        for amount in [0, -1, 10001, True]:
            assert (
                await http.post(
                    path + "/review", headers=REVIEWER, json={**APPROVE, "amount_cents": amount}
                )
            ).status_code == 422
        assert (
            await http.post(
                path + "/review",
                headers=REVIEWER,
                json={"decision": "reject", "reason": "Insufficient evidence"},
            )
        ).status_code == 200
        assert (await http.post(path + "/execute", headers=REVIEWER)).status_code == 409
        other = await create_case(http)
        path = f"/v1/reviewer/cases/{other}"
        assert (
            await http.post(path + "/review", headers=REVIEWER, json=APPROVE)
        ).status_code == 200
        with Session(engine) as db:
            db.get(DeliveryEvidence, "order").proof_status = "matched"
            db.commit()
        assert (await http.post(path + "/execute", headers=REVIEWER)).status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(SimulatedRefund)) == 0
        assert db.scalar(select(func.count()).select_from(CaseReview)) == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(CaseEvent)
                .where(CaseEvent.kind == "refund_simulated")
            )
            == 0
        )


@pytest.mark.asyncio
async def test_two_cases_and_legacy_request_cannot_double_refund(setup):
    app, engine = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        cases = [await create_case(http), await create_case(http)]
        for case in cases:
            assert (
                await http.post(f"/v1/reviewer/cases/{case}/review", headers=REVIEWER, json=APPROVE)
            ).status_code == 200
        assert (
            await http.post(f"/v1/reviewer/cases/{cases[0]}/execute", headers=REVIEWER)
        ).status_code == 200
        assert (
            await http.post(f"/v1/reviewer/cases/{cases[1]}/execute", headers=REVIEWER)
        ).status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(SimulatedRefund)) == 1
        assert db.scalar(select(func.count()).select_from(Refund)) == 0


@pytest.mark.asyncio
async def test_legacy_request_blocks_approval(setup):
    app, engine = setup
    with Session(engine) as db:
        db.add(Refund(order_id="order", customer_id="alice", status="requested"))
        db.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        response = await http.post(
            f"/v1/reviewer/cases/{case}/review", headers=REVIEWER, json=APPROVE
        )
        assert response.status_code == 409
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(CaseReview)) == 0


@pytest.mark.asyncio
async def test_execution_failure_rolls_back_payment_and_status(setup, monkeypatch):
    from app.models.entities import DisputeCase
    from app.services import resolutions as service

    app, engine = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        case = await create_case(http)
        path = f"/v1/reviewer/cases/{case}"
        assert (
            await http.post(path + "/review", headers=REVIEWER, json=APPROVE)
        ).status_code == 200

        def failed_event(*args):
            raise RuntimeError("Simulated audit persistence failure")

        monkeypatch.setattr(service, "record_event", failed_event)
        with pytest.raises(RuntimeError, match="audit persistence"):
            await http.post(path + "/execute", headers=REVIEWER)
    with Session(engine) as db:
        assert db.get(DisputeCase, case).status == "approved"
        assert db.scalar(select(func.count()).select_from(SimulatedRefund)) == 0
        assert db.scalar(select(func.count()).select_from(CaseEvent)) == 2
