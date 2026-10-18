from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import router


def test_health():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/v1/health").json() == {"status": "ok"}
