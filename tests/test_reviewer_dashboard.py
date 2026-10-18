"""Reviewer browsing permissions and Streamlit interactions."""

from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from tests.helpers import APPROVE, CUSTOMER, REVIEWER, create_case


@pytest.mark.asyncio
async def test_reviewer_queue_filter_pagination_and_details(setup):
    app, _ = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        first = await create_case(http)
        second = await create_case(http)
        path = "/v1/reviewer/cases"
        for headers in [{}, CUSTOMER]:
            assert (await http.get(path, headers=headers)).status_code == 403
            assert (await http.get(f"{path}/{first}", headers=headers)).status_code == 403
        page = (await http.get(path, headers=REVIEWER, params={"limit": 1})).json()
        assert page["has_more"] is True
        next_page = (
            await http.get(path, headers=REVIEWER, params={"limit": 1, "offset": 1})
        ).json()
        assert next_page["has_more"] is False
        assert {page["items"][0]["id"], next_page["items"][0]["id"]} == {first, second}
        assert (
            await http.post(f"{path}/{first}/review", headers=REVIEWER, json=APPROVE)
        ).status_code == 200
        approved = (await http.get(path, headers=REVIEWER, params={"status": "approved"})).json()
        assert [c["id"] for c in approved["items"]] == [first]
        detail = (await http.get(f"{path}/{first}", headers=REVIEWER)).json()
        assert detail["customer_id"] == "alice"
        assert detail["review"]["amount_cents"] == 10000
        assert detail["review"]["reviewer_id"] == "reviewer-1"
        assert (await http.get(f"{path}/missing", headers=REVIEWER)).status_code == 404
        assert (await http.get(path, headers=REVIEWER, params={"limit": 101})).status_code == 422
        assert (
            await http.get(path, headers=REVIEWER, params={"status": "unknown"})
        ).status_code == 422


@pytest.fixture
def dashboard(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "auth_mode", "demo")
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    monkeypatch.syspath_prepend(str(frontend))
    import reviewer_dashboard

    class FakeClient:
        calls = []
        state = "awaiting_review"

        def __init__(self, *args):
            pass

        def cases(self, *args):
            return {
                "items": [{"id": "case-1", "order_id": "order-1", "status": self.state}],
                "has_more": False,
            }

        def case(self, case_id):
            return {
                "id": case_id,
                "order_id": "order-1",
                "customer_id": "alice",
                "issue": "Not received",
                "status": self.state,
                "review": None,
                "investigation": {
                    "order": {"amount_cents": 100},
                    "delivery": None,
                    "previous_case_ids": [],
                    "decision": {
                        "action": "refund_review",
                        "reason": "Conflicting proof",
                        "policy_version": "v1",
                        "policy_source": "policy.md",
                        "missing_information": [],
                    },
                },
            }

        def audit(self, *args):
            return {"events": []}

        def similar(self, *args):
            return {
                "items": [],
                "notice": "Advisory simulations only",
                "candidate_pool_truncated": False,
            }

        def review(self, *args):
            self.calls.append(("review", args))
            FakeClient.state = "approved"

        def execute(self, *args):
            self.calls.append(("execute", args))
            FakeClient.state = "resolved"

    monkeypatch.setattr(reviewer_dashboard, "ReviewerClient", FakeClient)
    app = AppTest.from_file(str(frontend / "streamlit_app.py"))
    app.run()
    app.radio[0].set_value("Reviewer dashboard").run()
    return app, FakeClient


def test_dashboard_requires_key_and_reason(dashboard):
    app, client = dashboard
    assert not app.exception
    assert len(app.selectbox) == 0
    app.text_input(key="reviewer_key").set_value("secret").run()
    app.button[-1].click().run()
    assert "reason is required" in app.error[0].value
    assert client.calls == []


def test_dashboard_approval_and_execution_confirmation(dashboard):
    app, client = dashboard
    app.text_input(key="reviewer_key").set_value("secret").run()
    app.selectbox[2].set_value("approve")
    app.text_area[0].set_value("Verified proof")
    app.button[-1].click().run()
    assert not app.exception
    assert client.calls[0] == ("review", ("case-1", "approve", "Verified proof", 100))
    assert app.button[-1].disabled is True
    app.checkbox(key="confirm_case-1").check().run()
    app.button[-1].click().run()
    assert not app.exception
    assert client.calls[-1] == ("execute", ("case-1",))
    assert "No money was moved" in app.success[0].value


def test_dashboard_reports_expired_credentials_without_actions(dashboard, monkeypatch):
    app, client = dashboard
    from api_client import ApiError

    def denied(*args):
        raise ApiError("403: Valid reviewer credentials required")

    monkeypatch.setattr(client, "cases", denied)
    app.text_input(key="reviewer_key").set_value("invalid").run()
    assert not app.exception
    assert "403" in app.error[0].value
    assert client.calls == []


def test_reviewer_client_sends_only_reviewer_credentials(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "frontend"))
    from api_client import ApiError, ReviewerClient

    calls = []

    def respond(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(
            403, json={"detail": "Reviewer access denied"}, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx, "request", respond)
    with pytest.raises(ApiError, match="403: Reviewer access denied"):
        ReviewerClient("http://localhost:8000/", "review-secret").cases("approved")
    assert calls[0][2]["headers"] == {"X-Reviewer-Key": "review-secret"}
    assert calls[0][2]["params"]["status"] == "approved"


def test_dashboard_displays_advisory_similar_cases(dashboard, monkeypatch):
    app, client = dashboard

    def similar(*args):
        return {
            "items": [
                {
                    "reference_case_id": "historical-case",
                    "similarity_score": 0.889,
                    "policy_version": "delivery-dispute-v1",
                    "matching_features": ["proof_status"],
                    "differences": [
                        {
                            "feature": "amount_band",
                            "current": "up_to_10000",
                            "historical": "over_100000",
                        }
                    ],
                }
            ],
            "notice": "Advisory simulations only",
            "candidate_pool_truncated": False,
        }

    monkeypatch.setattr(client, "similar", similar)
    app.text_input(key="reviewer_key").set_value("secret").run()
    assert not app.exception
    assert any("historical-case" in item.value for item in app.markdown)
    assert any("not outcome probability" in item.value for item in app.caption)
