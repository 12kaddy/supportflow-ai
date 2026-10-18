import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import oidc
from app.core.config import get_settings
from tests.helpers import APPROVE, CUSTOMER, REVIEWER


@pytest.mark.asyncio
async def test_verified_subject_cannot_be_overridden_and_review_requires_role(setup, signer):
    app, _ = setup
    customer = {"Authorization": "Bearer " + signer(customer_id="bob"), "X-Customer-ID": "bob"}
    reviewer = {"Authorization": "Bearer " + signer("reviewer-123", ["reviewer"])}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        assert (await http.get("/v1/me", headers=customer)).json()["customer_id"] == "alice"
        response = await http.post(
            "/v1/cases", headers=customer, json={"order_id": "order", "issue": "Not received"}
        )
        assert response.status_code == 201
        case = response.json()["id"]
        path = f"/v1/reviewer/cases/{case}"
        assert (
            await http.post(path + "/review", headers=customer, json=APPROVE)
        ).status_code == 403
        assert (
            await http.post(path + "/review", headers=reviewer, json=APPROVE)
        ).status_code == 200
        details = (await http.get(path, headers=reviewer)).json()
        assert details["review"]["reviewer_id"] == "reviewer-123"
        assert (await http.get("/v1/me", headers=reviewer)).status_code == 403
        bob = {"Authorization": "Bearer " + signer("bob")}
        assert (await http.get(f"/v1/cases/{case}", headers=bob)).status_code == 404
        assert (await http.get("/v1/orders/order", headers=bob)).status_code == 404
        assert (await http.get("/v1/me", headers=CUSTOMER)).status_code == 401
        assert (await http.get(path, headers=REVIEWER)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims",
    [
        {"exp": 1},
        {"iss": "https://attacker.example"},
        {"aud": "wrong-api"},
        {"nbf": 9999999999},
        {"sub": ""},
        {"typ": "ID"},
        {"exp": None},
        {"iat": None},
    ],
)
async def test_invalid_tokens_fail_closed(setup, signer, claims):
    app, _ = setup
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.get("/v1/me", headers={"Authorization": "Bearer " + signer(**claims)})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_wrong_signature_and_algorithm_are_rejected(setup, signer):
    app, _ = setup
    valid = signer()
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_signature = jwt.encode(
        jwt.decode(valid, options={"verify_signature": False}),
        other_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    wrong_algorithm = jwt.encode(
        {"sub": "alice"}, "untrusted-secret-at-least-32-characters", algorithm="HS256"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        for token in [wrong_signature, wrong_algorithm, "malformed"]:
            assert (
                await http.get("/v1/me", headers={"Authorization": "Bearer " + token})
            ).status_code == 401


def test_oidc_requires_expiry_and_issuer_availability(setup, signer, monkeypatch):
    from fastapi import HTTPException

    valid = signer()

    def offline(url):
        raise jwt.PyJWKClientConnectionError("private-network-details")

    monkeypatch.setattr(oidc, "jwks_client", offline)
    with pytest.raises(HTTPException) as exc:
        oidc.token_identity("Bearer " + valid, "customer")
    assert exc.value.status_code == 503
    assert "private" not in exc.value.detail


@pytest.mark.asyncio
async def test_real_email_subscription_uses_only_verified_token_email(setup, signer, monkeypatch):
    app, _ = setup
    monkeypatch.setattr(get_settings(), "email_enabled", True)
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "smtp")
    verified = {
        "Authorization": "Bearer " + signer(email="alice@example.test", email_verified=True)
    }
    unverified = {
        "Authorization": "Bearer " + signer(email="alice@example.test", email_verified=False)
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        result = await http.post(
            "/v1/cases", headers=verified, json={"order_id": "order", "issue": "Missing"}
        )
        endpoint = f"/v1/cases/{result.json()['id']}/email-subscription"
        assert (
            await http.put(endpoint, headers=unverified, json={"enabled": True})
        ).status_code == 403
        assert (
            await http.put(
                endpoint,
                headers=verified,
                json={"enabled": True, "email": "someoneelse@example.test"},
            )
        ).status_code == 403
        assert (
            await http.put(endpoint, headers=verified, json={"enabled": True})
        ).status_code == 200
        preference = (await http.get(endpoint, headers=verified)).json()
        assert preference["email"] == "alice@example.test" and preference["enabled"] is True
