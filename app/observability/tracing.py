"""Optional OpenInference-compatible Phoenix spans with private content omitted."""

import json
from contextlib import contextmanager
from functools import lru_cache

from langchain_core.callbacks import AsyncCallbackHandler

from app.core.config import get_settings


@lru_cache(maxsize=1)
def provider():
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    settings = get_settings()
    value = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "supportflow",
                "openinference.project.name": settings.tracing_project,
            }
        )
    )
    value.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=settings.tracing_endpoint,
                timeout=2,
            )
        )
    )
    return value


@contextmanager
def turn_trace(tracer=None):
    if tracer is None and not get_settings().tracing_enabled:
        yield None
        return
    if tracer is None:
        tracer = provider().get_tracer("supportflow")
    with tracer.start_as_current_span(
        "supportflow.turn",
        record_exception=False,
        set_status_on_exception=False,
        attributes={
            "openinference.span.kind": "AGENT",
        },
    ) as root:
        callback = TraceCallbacks(tracer, root)
        try:
            yield callback
        except BaseException as exc:
            from opentelemetry.trace import Status, StatusCode

            root.set_attribute("error.type", type(exc).__name__)
            root.set_status(Status(StatusCode.ERROR))
            raise
        finally:
            callback.close()


class TraceCallbacks(AsyncCallbackHandler):
    def __init__(self, tracer, root):
        self.tracer, self.root = tracer, root
        self.spans = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        from opentelemetry.trace import set_span_in_context

        self.spans[run_id] = self.tracer.start_span(
            "model.call",
            context=set_span_in_context(self.root),
            attributes={"openinference.span.kind": "LLM"},
        )
        from app.agents.models import model_identity

        self.spans[run_id].set_attribute("llm.model_name", model_identity()["model"])

    async def on_llm_end(self, response, *, run_id, **kwargs):
        span = self.spans.pop(run_id, None)
        if span:
            usage = next(
                (
                    getattr(generation.message, "usage_metadata", None)
                    for group in response.generations
                    for generation in group
                    if hasattr(generation, "message")
                    and getattr(generation.message, "usage_metadata", None)
                ),
                None,
            )
            if not usage:
                legacy = (response.llm_output or {}).get("token_usage", {})
                usage = {
                    "input_tokens": legacy.get("prompt_tokens"),
                    "output_tokens": legacy.get("completion_tokens"),
                    "total_tokens": legacy.get("total_tokens"),
                }
            for source, target in [
                ("input_tokens", "prompt"),
                ("output_tokens", "completion"),
                ("total_tokens", "total"),
            ]:
                count = usage.get(source)
                if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                    span.set_attribute("llm.token_count." + target, count)
            span.end()

    async def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        from opentelemetry.trace import set_span_in_context

        from app.observability.agent import TOOL_NAMES

        name = (serialized or {}).get("name", "unknown")
        name = name if name in TOOL_NAMES else "unknown"
        self.spans[run_id] = self.tracer.start_span(
            "tool." + name,
            context=set_span_in_context(self.root),
            attributes={
                "openinference.span.kind": "RETRIEVER" if name == "find_policy" else "TOOL",
                "tool.name": name,
            },
        )

    async def on_tool_end(self, output, *, run_id, **kwargs):
        span = self.spans.pop(run_id, None)
        if span is None:
            return
        content = getattr(output, "content", output)
        try:
            data = json.loads(content) if isinstance(content, str) else None
        except (ValueError, TypeError):
            data = None
        if span.attributes.get("tool.name") == "find_policy" and isinstance(data, list):
            for index, chunk in enumerate(data[:10]):
                prefix = f"retrieval.documents.{index}.document."
                span.set_attribute(prefix + "id", str(chunk.get("chunk_id", "")))
                span.set_attribute(
                    prefix + "metadata",
                    json.dumps(
                        {
                            key: chunk.get(key)
                            for key in [
                                "source",
                                "version",
                                "citation",
                                "rank_score",
                                "retrieval_methods",
                                "vector_status",
                            ]
                        }
                    ),
                )
                if get_settings().tracing_policy_text:
                    span.set_attribute(prefix + "content", str(chunk.get("text", ""))[:1000])
        elif isinstance(data, dict) and data.get("error"):
            span.set_attribute("supportflow.tool_domain_error", True)
        span.end()

    async def fail(self, error, run_id):
        from opentelemetry.trace import Status, StatusCode

        span = self.spans.pop(run_id, None)
        if span:
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            span.end()

    async def on_tool_error(self, error, *, run_id, **kwargs):
        await self.fail(error, run_id)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        await self.fail(error, run_id)

    def close(self):
        for span in self.spans.values():
            span.set_attribute("supportflow.interrupted", True)
            span.end()
        self.spans.clear()
