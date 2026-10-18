"""Shared integration fixtures for isolated workflow and identity tests."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1 import accounts, email_notifications, resolutions, routes
from app.core import oidc
from app.core.config import get_settings
from app.db.base import Base
from app.models.entities import DeliveryEvidence, Order


@pytest.fixture(autouse=True)
def offline_tracing(monkeypatch):
    # A developer's .env must not cause ordinary fixture tests to export real traces.
    monkeypatch.setattr(get_settings(), "tracing_enabled", False)


def pytest_addoption(parser):
    parser.addoption(
        "--postgres",
        action="store_true",
        default=False,
        help="Run PostgreSQL tests in disposable schemas on the configured database",
    )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'workflow.db'}")
    Base.metadata.create_all(engine)

    class LocalSession:
        async def __aenter__(self):
            self.db = Session(engine, expire_on_commit=False)
            return self

        async def __aexit__(self, *args):
            self.db.close()

        @asynccontextmanager
        async def begin(self):
            with self.db.begin():
                yield

        async def get(self, *args):
            return self.db.get(*args)

        async def scalar(self, statement):
            return self.db.scalar(statement)

        async def scalars(self, statement):
            return self.db.scalars(statement)

        def add(self, value):
            self.db.add(value)

        async def flush(self):
            self.db.flush()

        async def commit(self):
            self.db.commit()

        async def refresh(self, value):
            self.db.refresh(value)

    monkeypatch.setattr(routes, "SessionLocal", LocalSession)
    monkeypatch.setattr(resolutions, "SessionLocal", LocalSession)
    monkeypatch.setattr(email_notifications, "SessionLocal", LocalSession)
    monkeypatch.setattr(accounts, "SessionLocal", LocalSession)
    monkeypatch.setattr(get_settings(), "api_key", "customer-secret")
    monkeypatch.setattr(get_settings(), "auth_mode", "demo")
    monkeypatch.setattr(get_settings(), "email_enabled", False)
    monkeypatch.setattr(get_settings(), "reviewer_api_keys", {"reviewer-1": "reviewer-secret"})
    with Session(engine) as db:
        db.add(
            Order(
                id="order",
                customer_id="alice",
                status="delivered",
                amount_cents=10000,
                days_since_delivery=2,
            )
        )
        db.commit()
        db.add(
            DeliveryEvidence(
                order_id="order", proof_status="mismatched", tracking_events=[], source="simulated"
            )
        )
        db.commit()
    app = FastAPI()
    app.include_router(routes.router)
    yield app, engine
    engine.dispose()


@pytest.fixture
def signer(setup, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    monkeypatch.setattr(settings, "oidc_issuer", "https://identity.example/realms/supportflow")
    monkeypatch.setattr(settings, "oidc_jwks_url", "https://identity.example/certs")
    monkeypatch.setattr(settings, "oidc_audience", "supportflow-api")

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=key.public_key())

    monkeypatch.setattr(oidc, "jwks_client", lambda url: Keys())

    def sign(subject="alice", roles=None, **overrides):
        now = datetime.now(timezone.utc)
        claims = {
            "sub": subject,
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "typ": "Bearer",
            "realm_access": {"roles": ["customer"] if roles is None else roles},
        }
        claims.update(overrides)
        claims = {name: value for name, value in claims.items() if value is not None}
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})

    return sign
