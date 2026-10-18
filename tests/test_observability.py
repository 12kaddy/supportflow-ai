import asyncio
import json
import logging
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from groq import APIConnectionError, RateLimitError
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.api.v1 import routes
from app.core.customer_contact import customer_email
from app.core.security import identity
from app.observability.agent import AgentTelemetry
from app.observability.events import request_id
from app.observability.middleware import RequestTelemetryMiddleware
from tests.test_evaluation import FixtureModel


@pytest.fixture
def traced_app():
    app = FastAPI()
    app.include_router(routes.router)
    app.add_middleware(RequestTelemetryMiddleware)
    app.dependency_overrides[identity] = lambda: "private-customer"
    app.dependency_overrides[customer_email] = lambda: None
    app.state.checkpointer = None
    return app


def records(caplog):
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "supportflow.telemetry"
    ]


@pytest.mark.asyncio
async def test_request_ids_are_unique_and_private_data_is_not_logged(traced_app, caplog):
    caplog.set_level(logging.INFO, logger="supportflow.telemetry")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=traced_app), base_url="http://test"
    ) as client:
        responses = await asyncio.gather(
            *[
                client.get(
                    "/v1/health?secret=private-query",
                    headers={"X-API-Key": "private-key", "X-Request-ID": "injected"},
                )
                for _ in range(2)
            ]
        )
    identifiers = {r.headers["x-request-id"] for r in responses}
    assert len(identifiers) == 2 and "injected" not in identifiers
    entries = records(caplog)
    assert {entry["request_id"] for entry in entries} == identifiers
    assert all(e["route"] == "/v1/health" and e["status"] == 200 for e in entries)
    assert "private-" not in caplog.text
    assert request_id.get() is None


@pytest.mark.asyncio
async def test_chat_callbacks_emit_correlated_metrics_without_content(
    traced_app, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="supportflow.telemetry")

    class Graph:
        async def ainvoke(self, state, config):
            callback = config["callbacks"][0]
            run = uuid4()
            await callback.on_tool_start(
                {"name": "lookup_order"}, "private-order-argument", run_id=run
            )
            await callback.on_tool_end("private-order-result", run_id=run)
            message = AIMessage(
                content="private-answer",
                usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
            )
            await callback.on_llm_end(
                LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=uuid4()
            )
            return {"messages": [message]}

    monkeypatch.setattr(routes, "build_graph", lambda *args: Graph())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=traced_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/chat", json={"message": "private-message", "thread_id": "private-thread"}
        )
    assert response.status_code == 200
    entries = records(caplog)
    assert {entry["request_id"] for entry in entries} == {response.headers["x-request-id"]}
    summary = next(e for e in entries if e["event"] == "chat_completed")
    assert summary["token_usage"] == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    assert summary["tool_calls"] == 1 and summary["tool_errors"] == 0
    assert summary["outcome"] == "success"
    assert "private-" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status,retry", [("rate", 429, "12"), ("connection", 503, None), ("internal", 500, None)]
)
async def test_provider_errors_are_sanitized_and_not_retried(
    traced_app, monkeypatch, caplog, error, status, retry
):
    caplog.set_level(logging.INFO, logger="supportflow.telemetry")
    calls = []

    class Graph:
        async def ainvoke(self, state, config):
            calls.append(1)
            request = httpx.Request("POST", "https://provider.invalid")
            if error == "rate":
                raise RateLimitError(
                    "private-provider-error",
                    response=httpx.Response(429, request=request, headers={"retry-after": "12"}),
                    body={"key": "private-key"},
                )
            if error == "connection":
                raise APIConnectionError(request=request, message="private-provider-error")
            raise RuntimeError("private-provider-error")

    monkeypatch.setattr(routes, "build_graph", lambda *args: Graph())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=traced_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/chat", json={"message": "private-message", "thread_id": "private-thread"}
        )
    assert response.status_code == status
    assert response.headers.get("retry-after") == retry
    assert response.headers["x-request-id"]
    assert len(calls) == 1
    assert "private-" not in response.text and "private-" not in caplog.text
    summary = next(e for e in records(caplog) if e["event"] == "chat_completed")
    assert summary["outcome"] == "error" and summary["error_type"]
    assert summary["token_usage"] is None


@pytest.mark.asyncio
async def test_tool_domain_errors_are_counted_without_logging_output(caplog):
    caplog.set_level(logging.INFO, logger="supportflow.telemetry")
    telemetry = AgentTelemetry()
    run = uuid4()
    await telemetry.on_tool_start({"name": "lookup_order"}, "secret", run_id=run)
    await telemetry.on_tool_end(
        ToolMessage(content='{"error":"private-order-not-found"}', tool_call_id="1"), run_id=run
    )
    assert telemetry.tool_errors == 1
    assert "private-order-not-found" not in caplog.text
    assert records(caplog)[0]["outcome"] == "error"


@pytest.mark.asyncio
async def test_real_graph_callbacks_count_both_model_turns(traced_app, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="supportflow.telemetry")

    @tool
    def lookup_order(order_id: str) -> str:
        """Look up an order in a test fixture."""
        return "private-tool-result"

    model = FixtureModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "lookup_order",
                            "args": {"order_id": "private-order"},
                            "id": "call-1",
                        }
                    ],
                    usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                ),
                AIMessage(
                    content="private-answer",
                    usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                ),
            ]
        )
    )
    graph = create_react_agent(model, [lookup_order])
    monkeypatch.setattr(routes, "build_graph", lambda *args: graph)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=traced_app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/chat", json={"message": "private-query", "thread_id": "private-thread"}
        )
    assert response.status_code == 200
    entries = records(caplog)
    assert {e["request_id"] for e in entries} == {response.headers["x-request-id"]}
    summary = next(e for e in entries if e["event"] == "chat_completed")
    assert summary["llm_calls"] == 2
    assert summary["tool_calls"] == 1
    assert summary["token_usage"] == {"input_tokens": 20, "output_tokens": 9, "total_tokens": 29}
    assert "private-" not in caplog.text
