import json
from time import perf_counter

from langchain_core.callbacks import AsyncCallbackHandler

from app.observability.events import emit

TOOL_NAMES = {
    "lookup_order",
    "find_policy",
    "report_delivery_issue",
    "lookup_dispute",
    "lookup_order_dispute",
}


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class AgentTelemetry(AsyncCallbackHandler):
    """LangChain callbacks intentionally ignore messages, arguments, and outputs."""

    def __init__(self):
        self.tools = {}
        self.tool_calls = 0
        self.tool_errors = 0
        self.llm_calls = 0
        self.llm_errors = 0
        self.tokens = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        self.usage_available = False

    async def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        name = (serialized or {}).get("name", "unknown_tool")
        name = name if name in TOOL_NAMES else "unknown_tool"
        self.tools[run_id] = (name, perf_counter())
        self.tool_calls += 1

    def finish_tool(self, run_id, failed, error_type=None):
        name, started = self.tools.pop(run_id, ("unknown_tool", perf_counter()))
        self.tool_errors += int(failed)
        emit(
            "agent_tool_completed",
            tool=name,
            outcome="error" if failed else "success",
            latency_ms=round((perf_counter() - started) * 1000, 2),
            error_type=error_type,
        )

    async def on_tool_end(self, output, *, run_id, **kwargs):
        failed = getattr(output, "status", None) == "error"
        content = getattr(output, "content", output)
        if isinstance(content, str) and content.startswith("{") and len(content) <= 10000:
            try:
                payload = json.loads(content)
                failed = failed or (isinstance(payload, dict) and "error" in payload)
            except ValueError:
                pass
        self.finish_tool(run_id, failed)

    async def on_tool_error(self, error, *, run_id, **kwargs):
        self.finish_tool(run_id, True, type(error).__name__)

    async def on_llm_end(self, response, *, run_id, **kwargs):
        self.llm_calls += 1
        usages = [
            getattr(generation.message, "usage_metadata", None)
            for group in response.generations
            for generation in group
            if hasattr(generation, "message")
        ]
        usages = [usage for usage in usages if usage]
        if not usages:
            legacy = (response.llm_output or {}).get("token_usage", {})
            if legacy:
                usages = [
                    {
                        "input_tokens": legacy.get("prompt_tokens"),
                        "output_tokens": legacy.get("completion_tokens"),
                        "total_tokens": legacy.get("total_tokens"),
                    }
                ]
        for usage in usages:
            self.usage_available = True
            for name in self.tokens:
                self.tokens[name] += count(usage.get(name))

    async def on_llm_error(self, error, *, run_id, **kwargs):
        self.llm_calls += 1
        self.llm_errors += 1

    def summary(self):
        return {
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "llm_calls": self.llm_calls,
            "llm_errors": self.llm_errors,
            "token_usage": self.tokens.copy() if self.usage_available else None,
        }
