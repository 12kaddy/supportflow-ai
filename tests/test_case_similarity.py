from copy import deepcopy

import httpx
import pytest
from sqlalchemy.orm import Session

from app.models.entities import DeliveryEvidence, DisputeCase, Order
from app.services.case_similarity import compare_snapshots
from tests.helpers import CUSTOMER, REVIEWER, create_case


async def completed_case(http, engine, order_id, customer, amount=10000):
    with Session(engine) as db:
        db.add(
            Order(
                id=order_id,
                customer_id=customer,
                status="delivered",
                amount_cents=amount,
                days_since_delivery=2,
            )
        )
        db.commit()
        db.add(
            DeliveryEvidence(
                order_id=order_id,
                proof_status="mismatched",
                tracking_events=[],
                source="simulation",
            )
        )
        db.commit()
    response = await http.post(
        "/v1/cases",
        headers={**CUSTOMER, "X-Customer-ID": customer},
        json={"order_id": order_id, "issue": "private-historical-issue"},
    )
    assert response.status_code == 201
    case_id = response.json()["id"]
    base = f"/v1/reviewer/cases/{case_id}"
    assert (
        await http.post(
            base + "/review",
            headers=REVIEWER,
            json={
                "decision": "approve",
                "reason": "private-review-notes",
                "amount_cents": amount,
            },
        )
    ).status_code == 200
    assert (await http.post(base + "/execute", headers=REVIEWER)).status_code == 200
    return case_id


@pytest.mark.asyncio
async def test_similar_cases_are_ranked_advisory_and_reviewer_only(setup):
    app, engine = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        target = await create_case(http)
        closest = await completed_case(http, engine, "old-order-1", "private-customer-bob")
        different_amount = await completed_case(
            http, engine, "old-order-2", "private-customer-carol", 100000
        )
        path = f"/v1/reviewer/cases/{target}/similar"
        for headers in [{}, CUSTOMER]:
            assert (await http.get(path, headers=headers)).status_code == 403
        response = await http.get(path, headers=REVIEWER)
        assert response.status_code == 200
        payload = response.json()
        assert payload["advisory_only"] is True
        assert [item["reference_case_id"] for item in payload["items"]] == [
            closest,
            different_amount,
        ]
        assert payload["items"][0]["similarity_score"] == 1
        assert payload["items"][1]["differences"][0]["feature"] == "amount_band"
        assert "private-" not in response.text
        assert "amount_cents" not in response.text
        assert (
            len((await http.get(path, headers=REVIEWER, params={"limit": 1})).json()["items"]) == 1
        )
        assert (await http.get(path, headers=REVIEWER, params={"limit": 11})).status_code == 422
        assert (
            await http.get("/v1/reviewer/cases/missing/similar", headers=REVIEWER)
        ).status_code == 404
        assert (await http.get(f"/v1/cases/{target}", headers=CUSTOMER)).json()[
            "status"
        ] == "awaiting_review"


@pytest.mark.asyncio
async def test_obsolete_policy_and_incompatible_evidence_are_excluded(setup):
    app, engine = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        target = await create_case(http)
        old_policy = await completed_case(http, engine, "old-policy", "bob")
        changed_proof = await completed_case(http, engine, "other-proof", "carol")
        with Session(engine) as db:
            case = db.get(DisputeCase, old_policy)
            snapshot = deepcopy(case.investigation)
            snapshot["decision"]["policy_version"] = "obsolete-policy"
            case.investigation = snapshot
            case = db.get(DisputeCase, changed_proof)
            snapshot = deepcopy(case.investigation)
            snapshot["delivery"]["proof_status"] = "matched"
            case.investigation = snapshot
            db.commit()
        response = await http.get(f"/v1/reviewer/cases/{target}/similar", headers=REVIEWER)
        assert response.json()["items"] == []


def test_missing_proof_is_not_treated_as_a_similar_verified_resolution():
    snapshot = {
        "order": {"status": "delivered", "days_since_delivery": 2, "amount_cents": 100},
        "delivery": {"proof_status": "mismatched"},
        "decision": {"action": "refund_review"},
    }
    target = deepcopy(snapshot)
    target["delivery"] = None
    assert compare_snapshots(target, snapshot) is None
