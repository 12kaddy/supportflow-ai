from fastapi import HTTPException

from app.core.config import get_settings
from app.core.security import identity


def test_invalid_key_rejected(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_mode", "demo")
    try:
        identity(x_api_key="invalid", x_customer_id="demo-customer")
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("Expected 401")
