"""Chat invocation, telemetry, and provider error classification."""

from time import perf_counter

from groq import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.observability.agent import AgentTelemetry
from app.observability.events import emit


class ChatProviderError(Exception):
    def __init__(self, status, detail, retry_after=None):
        self.status = status
        self.detail = detail
        self.retry_after = retry_after
        super().__init__(detail)


async def invoke_chat(graph, message, thread):
    telemetry = AgentTelemetry()
    started = perf_counter()
    outcome = "success"
    error_type = None
    try:
        return await graph.ainvoke(
            {"messages": [{"role": "user", "content": message}]},
            config={"configurable": {"thread_id": thread}, "callbacks": [telemetry]},
        )
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
    except Exception as exc:
        outcome, error_type = "error", type(exc).__name__
        raise
    finally:
        emit(
            "chat_completed",
            outcome=outcome,
            error_type=error_type,
            latency_ms=round((perf_counter() - started) * 1000, 2),
            **telemetry.summary(),
        )
