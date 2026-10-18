"""Offline policy and API integration tests using a real SQLite database."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.v1 import routes
from app.core.config import get_settings
from app.core.customer_contact import customer_email
from app.core.security import identity
from app.db.base import Base
from app.models.entities import DeliveryEvidence, Order
from app.services.disputes import evaluate_dispute


@pytest.mark.parametrize(
    "status,age,proof,action",
    [
        ("shipped", None, None, "shipping_review"),
        ("delivered", None, "matched", "investigate"),
        ("delivered", -1, "matched", "investigate"),
        ("delivered", 8, "mismatched", "escalate"),
        ("delivered", 7, "mismatched", "refund_review"),
        ("delivered", 0, "matched", "carrier_review"),
        ("delivered", 3, None, "investigate"),
        ("delivered", 3, "unknown", "investigate"),
    ],
)
def test_policy(status, age, proof, action):
    result = evaluate_dispute(
        {"status": status, "days_since_delivery": age},
        {"proof_status": proof} if proof else None,
    )
    assert result["action"] == action
    assert result["requires_human_review"] is True
    assert result["payment_authorized"] is False
    assert result["policy_version"] == "delivery-dispute-v1"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(get_settings(), "email_enabled", False)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            Order(
                id="owned",
                customer_id="alice",
                status="delivered",
                amount_cents=1200000,
                days_since_delivery=2,
            )
        )
        db.add(
            Order(
                id="foreign",
                customer_id="bob",
                status="delivered",
                amount_cents=100,
                days_since_delivery=2,
            )
        )
        db.commit()
        db.add(
            DeliveryEvidence(
                order_id="owned",
                tracking_events=[{"event": "delivered"}],
                proof_status="mismatched",
                source="test-carrier",
            )
        )
        db.commit()

    # Adapt synchronous SQLite calls to the service's async session interface.
    class TestSession:
        async def __aenter__(self):
            self.db = Session(engine, expire_on_commit=False)
            return self

        async def __aexit__(self, *args):
            self.db.close()

        async def scalar(self, statement):
            return self.db.scalar(statement)

        async def scalars(self, statement):
            return self.db.scalars(statement)

        async def get(self, model, key):
            return self.db.get(model, key)

        def add(self, entity):
            self.db.add(entity)

        async def commit(self):
            self.db.commit()

        async def flush(self):
            self.db.flush()

        async def refresh(self, entity):
            self.db.refresh(entity)

    monkeypatch.setattr(routes, "SessionLocal", TestSession)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[identity] = lambda: "alice"
    app.dependency_overrides[customer_email] = lambda: None
    with TestClient(app) as test_client:
        yield test_client, app
    engine.dispose()


def test_case_persistence_history_and_isolation(client):
    http, app = client
    body = {"order_id": "owned", "issue": "Delivered but not received"}
    response = http.post("/v1/cases", json=body)
    assert response.status_code == 201
    case = response.json()
    assert case["investigation"]["decision"]["action"] == "refund_review"
    assert case["investigation"]["delivery"]["source"] == "test-carrier"
    assert http.get(f"/v1/cases/{case['id']}").json() == case
    second = http.post("/v1/cases", json=body).json()
    assert second["investigation"]["previous_case_ids"] == [case["id"]]
    assert http.post("/v1/cases", json={**body, "order_id": "foreign"}).status_code == 404
    app.dependency_overrides[identity] = lambda: "bob"
    assert http.get(f"/v1/cases/{case['id']}").status_code == 404


def test_invalid_case_and_missing_evidence(client):
    http, app = client
    assert http.post("/v1/cases", json={"order_id": "owned", "issue": " "}).status_code == 422
    assert http.get("/v1/cases/missing").status_code == 404
    app.dependency_overrides[identity] = lambda: "bob"
    response = http.post("/v1/cases", json={"order_id": "foreign", "issue": "Refund me now"})
    case = response.json()
    assert case["status"] == "awaiting_investigation"
    assert case["investigation"]["decision"]["payment_authorized"] is False
