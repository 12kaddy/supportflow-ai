"""Chat invocation, telemetry, and provider error classification."""

import asyncio
from time import perf_counter

import httpx
from groq import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from langchain_core.messages import AIMessage

from app.agents.models import model_identity
from app.core.config import get_settings
from app.guardrails.input import inspect_input
from app.guardrails.output import enforce_result
from app.observability.agent import AgentTelemetry
from app.observability.events import emit, request_id
from app.observability.tracing import turn_trace


class ChatProviderError(Exception):
    def __init__(self, status, detail, retry_after=None):
        self.status = status
        self.detail = detail
        self.retry_after = retry_after
        super().__init__(detail)


async def invoke_chat(graph, message, thread, *, language="en"):
    telemetry = AgentTelemetry()
    started = perf_counter()
    outcome = "success"
    error_type = None
    guard_report = {}
    trace = None
    try:
        with turn_trace() as trace:
            if trace:
                if request_id.get():
                    trace.root.set_attribute("supportflow.request_id", request_id.get())
                for key, value in model_identity().items():
                    trace.root.set_attribute("supportflow." + key, value)
            if get_settings().guardrails_enabled:
                verdict = inspect_input(message)
                guard_report = {
                    "input_blocked": verdict.blocked,
                    "input_redactions": verdict.redactions,
                }
                if trace:
                    trace.root.set_attribute("supportflow.input_blocked", verdict.blocked)
                    trace.root.set_attribute("supportflow.pii_redactions", len(verdict.redactions))
                if verdict.blocked:
                    outcome = "blocked"
                    if trace:
                        trace.root.set_attribute("supportflow.outcome", "blocked")
                    answer = "I cannot bypass support rules or reviewer approval. Please describe your order issue normally."
                    return {"messages": [AIMessage(content=answer)], "guardrails": guard_report}
                message = verdict.text
            callbacks = [telemetry] + ([trace] if trace else [])
            result = await graph.ainvoke(
                {"messages": [{"role": "user", "content": message}]},
                config={
                    "configurable": {"thread_id": thread},
                    "callbacks": callbacks,
                    "recursion_limit": 24,
                },
            )
            if get_settings().guardrails_enabled:
                result = await enforce_result(graph, result, thread, language)
                guard_report.update(result["guardrails"])
                result["guardrails"] = guard_report
                if trace:
                    trace.root.set_attribute(
                        "supportflow.claim_violations_before", len(guard_report["before"])
                    )
                    trace.root.set_attribute(
                        "supportflow.claim_violations_after", len(guard_report["after"])
                    )
                    trace.root.set_attribute(
                        "supportflow.answer_rewritten", guard_report["rewritten"]
                    )
            if trace:
                trace.root.set_attribute("supportflow.outcome", "success")
            return result
    except asyncio.CancelledError:
        outcome = "interrupted"
        raise
    except RateLimitError as exc:
        outcome, error_type = "error", type(exc).__name__
        header = exc.response.headers.get("retry-after", "30")
        retry_after = (
            header if header.isascii() and header.isdigit() and 0 < int(header) <= 3600 else "30"
        )
        raise ChatProviderError(
            429, "AI provider rate limit reached. Try again later.", retry_after
        ) from None
    except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
        outcome, error_type = "error", type(exc).__name__
        raise ChatProviderError(503, "AI provider is unavailable. Try again later.") from None
    except httpx.HTTPError as exc:
        outcome, error_type = "error", type(exc).__name__
        raise ChatProviderError(503, "AI provider is unavailable. Try again later.") from None
    except Exception as exc:
        outcome, error_type = "error", type(exc).__name__
        if type(exc).__module__.split(".")[0] in {"openai", "ollama"}:
            status = 429 if getattr(exc, "status_code", None) == 429 else 503
            raise ChatProviderError(
                status, "AI provider is unavailable. Try again later."
            ) from None
        raise
    finally:
        emit(
            "chat_completed",
            outcome=outcome,
            error_type=error_type,
            latency_ms=round((perf_counter() - started) * 1000, 2),
            guardrails=guard_report,
            **telemetry.summary(),
        )
