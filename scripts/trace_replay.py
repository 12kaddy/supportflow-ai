"""Reproduce a premature-refund claim and its fix; synthetic failure, no hosted LLM calls."""

import asyncio
import json
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent

from app.core.config import get_settings
from app.evaluation.environment import make_fixture_tools
from app.evaluation.runner import load_benchmark
from app.services.chat_runtime import invoke_chat


class ReplayModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


async def replay():
    settings = get_settings()
    settings.guardrails_enabled = True
    # Label this project/model explicitly: this is a regression replay, not model inference.
    settings.tracing_enabled = True
    settings.tracing_project = "supportflow-debug-replay"
    settings.groq_model = "scripted-regression-replay-not-a-hosted-model"
    case = next(
        item for item in load_benchmark().agent_cases if item.id == "approved-is-not-executed"
    )
    model = ReplayModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "replay-call",
                            "name": "lookup_order_dispute",
                            "args": {"order_id": "ORD-1001"},
                        }
                    ],
                ),
                AIMessage(content="Your refund has been issued."),
            ]
        )
    )
    saver = InMemorySaver()
    graph = create_react_agent(model, tools=make_fixture_tools(case), checkpointer=saver)
    result = await invoke_chat(graph, case.prompt, "fictional:debug-replay")
    state = await graph.aget_state({"configurable": {"thread_id": "fictional:debug-replay"}})
    report = {
        "source": "Injected scripted failure, not a spontaneous production/model discovery",
        "failure": "Approved proposal incorrectly described as an issued refund",
        "guardrails": result["guardrails"],
        "corrected_answer": result["messages"][-1].content,
        "checkpoint_matches_correction": state.values["messages"][-1].content
        == result["messages"][-1].content,
        "fix": "Evidence-rendered case reply and same-message checkpoint replacement; no tool replay",
    }
    from app.observability.tracing import provider

    provider().force_flush(timeout_millis=10000)
    target = Path(".local/evaluations/guardrail-trace-replay.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Replay report: {target.resolve()}")
    print(json.dumps(result["guardrails"], indent=2))


if __name__ == "__main__":
    asyncio.run(replay())
