import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.tools import tool

from app.agents.models import build_model, model_identity
from app.core.config import get_settings
from app.evaluation.runner import build_report, load_benchmark
from scripts.compare_models import comparison


@pytest.mark.parametrize(
    "provider,module,constructor",
    [
        ("groq", "langchain_groq", "ChatGroq"),
        ("ollama", "langchain_ollama", "ChatOllama"),
        ("vllm", "langchain_openai", "ChatOpenAI"),
    ],
)
def test_provider_factory_shares_configuration_without_cloud_fallback(
    monkeypatch, provider, module, constructor
):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(settings, "groq_api_key", "test-only-key" if provider == "groq" else "")
    monkeypatch.setitem(
        sys.modules, module, SimpleNamespace(**{constructor: lambda **kwargs: kwargs})
    )
    model = build_model()
    assert model["model"] == model_identity()["model"]
    assert model["temperature"] == 0
    if provider == "ollama":
        assert model["base_url"] == settings.ollama_base_url
        assert "api_key" not in model
    elif provider == "vllm":
        assert model["base_url"] == settings.vllm_base_url
    else:
        assert model["max_retries"] == 0


def test_comparison_requires_matching_provenance_and_preserves_unknown_cost(tmp_path):
    report = build_report(
        load_benchmark(), "agent", [{"id": "same", "passed": True, "latency_ms": 50}], "fixture"
    )
    report.update(
        provider="groq",
        guardrails={
            "version": "v1",
            "raw_pass_rate": 1,
            "claim_violation_rate_before": 0.5,
            "claim_violation_rate_after": 0,
        },
    )
    first, second = tmp_path / "one.json", tmp_path / "two.json"
    first.write_text(json.dumps(report), encoding="utf-8")
    text = comparison([first])
    assert "unknown" in text and "50.00 s" not in text
    report["system_prompt_sha256"] = "different"
    second.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="Reports must share"):
        comparison([first, second])


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["ollama", "vllm"])
async def test_real_local_adapter_tool_call_protocol(monkeypatch, provider):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", provider)

    @tool
    def lookup_order(order_id: str) -> str:
        """Look up an owned order."""
        return order_id

    requests = []

    def respond(request):
        data = json.loads(request.content)
        requests.append(data)
        assert data["tools"][0]["function"]["name"] == "lookup_order"
        if provider == "ollama":
            return httpx.Response(
                200,
                headers={"content-type": "application/x-ndjson"},
                content=json.dumps(
                    {
                        "model": settings.ollama_model,
                        "done": True,
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "lookup_order",
                                        "arguments": {"order_id": "ORD-1001"},
                                    }
                                }
                            ],
                        },
                        "prompt_eval_count": 20,
                        "eval_count": 5,
                    }
                )
                + "\n",
            )
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "object": "chat.completion",
                "created": 1,
                "model": settings.vllm_model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call",
                                    "type": "function",
                                    "function": {
                                        "name": "lookup_order",
                                        "arguments": '{"order_id":"ORD-1001"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            },
        )

    transport = httpx.MockTransport(respond)
    if provider == "ollama":
        import langchain_ollama

        actual = langchain_ollama.ChatOllama

        def constructor(**kwargs):
            kwargs["client_kwargs"]["transport"] = transport
            return actual(**kwargs)

        monkeypatch.setattr(langchain_ollama, "ChatOllama", constructor)
        result = await build_model().bind_tools([lookup_order]).ainvoke("Find ORD-1001")
    else:
        import langchain_openai

        actual = langchain_openai.ChatOpenAI
        async with httpx.AsyncClient(transport=transport) as client:
            monkeypatch.setattr(
                langchain_openai,
                "ChatOpenAI",
                lambda **kwargs: actual(http_async_client=client, **kwargs),
            )
            result = await build_model().bind_tools([lookup_order]).ainvoke("Find ORD-1001")
    assert result.tool_calls[0]["name"] == "lookup_order"
    assert result.tool_calls[0]["args"] == {"order_id": "ORD-1001"}
    assert result.usage_metadata["total_tokens"] == 25
    assert len(requests) == 1
