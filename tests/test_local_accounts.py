import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1 import routes
from app.core.config import get_settings
from app.core.local_tokens import issue_token
from app.models.accounts import Account
from app.models.notifications import EmailOutbox
from app.services.email_worker import deliver_one

BODY = {
    "name": "Test Customer",
    "email": "customer@example.test",
    "password": "long-test-password-123",
}


@pytest.fixture
def local(setup, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_mode", "local")
    monkeypatch.setattr(
        get_settings(), "local_auth_secret", "test-secret-for-local-accounts-at-least-32-characters"
    )
    monkeypatch.setattr(get_settings(), "email_enabled", True)
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "local")
    return setup


@pytest.mark.asyncio
async def test_registration_login_roles_and_password_hash(local):
    app, engine = local
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post("/v1/auth/register", json=BODY)
        assert response.status_code == 201, response.text
        user = response.json()
        assert user["role"] == "customer" and user["email_verified"] is False
        assert "password" not in response.text
        assert (
            await http.post("/v1/auth/register", json={**BODY, "role": "admin"})
        ).status_code == 422
        assert (await http.post("/v1/auth/register", json=BODY)).status_code == 409
        assert (
            await http.post("/v1/auth/login", json={"email": BODY["email"], "password": "wrong"})
        ).status_code == 401
        session = (
            await http.post(
                "/v1/auth/login", json={"email": BODY["email"], "password": BODY["password"]}
            )
        ).json()
        customer = {"Authorization": "Bearer " + session["access_token"]}
        assert (await http.get("/v1/me", headers=customer)).json()["customer_id"] == user["id"]
        assert (await http.get("/v1/reviewer/cases", headers=customer)).status_code == 403
        assert (await http.post("/v1/auth/admins", headers=customer, json=BODY)).status_code == 403
        assert (await http.post("/v1/auth/admins", json=BODY)).status_code == 401
        admin_token = issue_token(
            SimpleNamespace(
                id="admin-subject", role="admin", email="admin@example.test", email_verified=True
            )
        )
        admin = {"Authorization": "Bearer " + admin_token}
        assert (
            await http.post(
                "/v1/auth/admins", headers=admin, json={**BODY, "email": "new-admin@example.test"}
            )
        ).status_code == 201
        assert (await http.get("/v1/reviewer/cases", headers=admin)).status_code == 200
        assert (await http.get("/v1/auth/users", headers=customer)).status_code == 403
        listed = (await http.get("/v1/auth/users", headers=admin)).json()
        assert "password_hash" not in json.dumps(listed)
    with Session(engine) as db:
        account = db.get(Account, user["id"])
        assert account.password_hash.startswith("$argon2id$")
        assert account.password_hash != BODY["password"]


@pytest.mark.asyncio
async def test_email_verification_and_worker_share_existing_outbox(local):
    app, engine = local
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        assert (await http.post("/v1/auth/register", json=BODY)).status_code == 201
        with Session(engine) as db:
            queued = db.scalar(select(EmailOutbox))
            code = queued.verification_code
            assert queued.case_id is None and queued.kind == "verify_account"
            assert db.scalar(select(Account)).verification_hash != code
        sent = []
        async with routes.SessionLocal() as db:
            assert await deliver_one(db, sender=lambda row: sent.append(row.kind))
        assert sent == ["verify_account"]
        assert (
            await http.post("/v1/auth/verify-email", json={"email": BODY["email"], "code": code})
        ).status_code == 200
        assert (
            await http.post("/v1/auth/verify-email", json={"email": BODY["email"], "code": code})
        ).status_code == 400
        session = (
            await http.post(
                "/v1/auth/login", json={"email": BODY["email"], "password": BODY["password"]}
            )
        ).json()
        assert session["user"]["email_verified"] is True
        with Session(engine) as db:
            assert db.scalar(select(EmailOutbox)).verification_code is None


@pytest.mark.asyncio
async def test_verification_attempts_and_resend_are_bounded(local):
    app, engine = local
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        await http.post("/v1/auth/register", json=BODY)
        with Session(engine) as db:
            code = db.scalar(select(EmailOutbox)).verification_code
        bad = "000000" if code != "000000" else "111111"
        for _ in range(5):
            assert (
                await http.post("/v1/auth/verify-email", json={"email": BODY["email"], "code": bad})
            ).status_code == 400
        assert (
            await http.post("/v1/auth/verify-email", json={"email": BODY["email"], "code": code})
        ).status_code == 400
        assert (
            await http.post(
                "/v1/auth/resend-verification",
                json={"email": BODY["email"], "password": BODY["password"]},
            )
        ).status_code == 429


def test_frontend_customer_login_needs_no_pasted_token(local, monkeypatch):
    from streamlit.testing.v1 import AppTest

    frontend = Path(__file__).resolve().parents[1] / "frontend"
    monkeypatch.syspath_prepend(str(frontend))

    def respond(method, url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            json={
                "access_token": "session-token",
                "expires_in": 1800,
                "user": {
                    "id": "customer",
                    "name": "Customer",
                    "email": BODY["email"],
                    "role": "customer",
                    "email_verified": True,
                },
            },
        )

    monkeypatch.setattr(httpx, "request", respond)
    app = AppTest.from_file(str(frontend / "streamlit_app.py")).run()
    next(item for item in app.text_input if item.label == "Email").set_value(BODY["email"])
    next(item for item in app.text_input if item.label == "Password").set_value(BODY["password"])
    app.button[0].click().run()
    assert not app.exception
    assert len(app.chat_input) == 1
    assert not any("access token" in item.label.lower() for item in app.text_input)
