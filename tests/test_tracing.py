import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability.tracing import turn_trace


@pytest.mark.asyncio
async def test_phoenix_spans_show_calls_tokens_chunks_and_omit_customer_content():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with turn_trace(provider.get_tracer("test")) as trace:
        model, tool = uuid4(), uuid4()
        await trace.on_chat_model_start({}, ["private-message"], run_id=model)
        await trace.on_llm_end(
            LLMResult(
                generations=[
                    [
                        ChatGeneration(
                            message=AIMessage(
                                content="private-answer",
                                usage_metadata={
                                    "input_tokens": 10,
                                    "output_tokens": 5,
                                    "total_tokens": 15,
                                },
                            )
                        )
                    ]
                ]
            ),
            run_id=model,
        )
        await trace.on_tool_start({"name": "find_policy"}, "private-query", run_id=tool)
        await trace.on_tool_end(
            ToolMessage(
                content=json.dumps(
                    [
                        {
                            "chunk_id": "chunk-1",
                            "source": "refund.md",
                            "version": "v1",
                            "text": "not-exported-by-default",
                            "citation": "refund.md@v1#chunk-1",
                        }
                    ]
                ),
                tool_call_id="call",
            ),
            run_id=tool,
        )
    spans = exporter.get_finished_spans()
    assert {span.name for span in spans} == {"supportflow.turn", "model.call", "tool.find_policy"}
    root = next(span for span in spans if span.name == "supportflow.turn")
    assert all(span.parent.span_id == root.context.span_id for span in spans if span is not root)
    model_span = next(span for span in spans if span.name == "model.call")
    assert model_span.attributes["llm.token_count.total"] == 15
    values = json.dumps([dict(span.attributes) for span in spans])
    assert "chunk-1" in values and "refund.md" in values
    assert "private-" not in values and "not-exported" not in values
    assert all(span.end_time >= span.start_time for span in spans)
    provider.shutdown()


def test_exception_trace_does_not_export_provider_exception_text():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with pytest.raises(RuntimeError):
        with turn_trace(provider.get_tracer("test")):
            raise RuntimeError("private-provider-secret")
    span = exporter.get_finished_spans()[0]
    assert span.attributes["error.type"] == "RuntimeError"
    assert not span.events
    assert "private-provider-secret" not in json.dumps(dict(span.attributes))
    provider.shutdown()
