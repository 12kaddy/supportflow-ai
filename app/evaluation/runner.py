import asyncio
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from app.agents.graph import SYSTEM_PROMPT
from app.evaluation.environment import make_fixture_tools
from app.evaluation.schemas import Benchmark
from app.evaluation.scoring import SCORER_VERSION, score_response
from app.guardrails.output import current_tool_facts, verify_answer
from app.observability.tracing import turn_trace
from app.services.disputes import evaluate_dispute

DEFAULT_DATASET = Path(__file__).resolve().parents[2] / "data/evaluations/support_v2.json"


def load_benchmark(path=DEFAULT_DATASET):
    benchmark = Benchmark.model_validate_json(Path(path).read_text(encoding="utf-8"))
    for cases in [benchmark.policy_cases, benchmark.agent_cases]:
        if len({case.id for case in cases}) != len(cases):
            raise ValueError("Scenario IDs must be unique within each evaluation mode")
    return benchmark


def run_policy_case(scenario):
    started = perf_counter()
    decision = evaluate_dispute(
        {"status": scenario.order_status, "days_since_delivery": scenario.delivery_age},
        {"proof_status": scenario.proof_status} if scenario.proof_status else None,
    )
    checks = {
        "action": decision["action"] == scenario.expected_action,
        "missing_information": sorted(decision["missing_information"])
        == sorted(scenario.expected_missing),
        "human_review_required": decision["requires_human_review"] is True,
        "no_payment_authorization": decision["payment_authorized"] is False,
    }
    return {
        "id": scenario.id,
        "passed": all(checks.values()),
        "checks": checks,
        "decision": decision,
        "latency_ms": round((perf_counter() - started) * 1000, 2),
    }


async def run_agent_case(scenario, model, timeout=45, guardrails=False):
    with turn_trace() as trace:
        result = await _run_agent_case(scenario, model, timeout, guardrails, trace)
        if trace:
            trace.root.set_attribute("supportflow.evaluation_scenario", scenario.id)
            trace.root.set_attribute("supportflow.evaluation_passed", result["passed"])
            report = result.get("guardrails")
            if report:
                trace.root.set_attribute(
                    "supportflow.claim_violations_before", len(report["before"])
                )
                trace.root.set_attribute("supportflow.claim_violations_after", len(report["after"]))
        return result


async def _run_agent_case(scenario, model, timeout, guardrails, trace):
    started = perf_counter()
    try:
        graph = create_react_agent(model, tools=make_fixture_tools(scenario), prompt=SYSTEM_PROMPT)
        result = await asyncio.wait_for(
            graph.ainvoke(
                {"messages": [{"role": "user", "content": scenario.prompt}]},
                config={"recursion_limit": 12, "callbacks": [trace] if trace else []},
            ),
            timeout=timeout,
        )
        messages = result["messages"]
        calls = [
            call
            for message in messages
            if isinstance(message, AIMessage)
            for call in message.tool_calls
        ]
        tool_errors = [
            message.content
            for message in messages
            if isinstance(message, ToolMessage)
            and (message.status == "error" or '"error":' in str(message.content))
        ]
        raw_answer = str(messages[-1].content)
        answer = raw_answer
        guard_report = None
        if guardrails:
            answer, guard_report = verify_answer(raw_answer, current_tool_facts(messages))
        score = score_response(scenario, answer, calls, tool_errors)
        usage = [
            message.usage_metadata
            for message in messages
            if isinstance(message, AIMessage) and message.usage_metadata
        ]
        return {
            "id": scenario.id,
            **score,
            "answer": answer,
            "raw_answer": raw_answer,
            "guardrails": guard_report,
            "raw_score": score_response(scenario, raw_answer, calls, tool_errors),
            "tool_calls": calls,
            "tool_errors": tool_errors,
            "token_usage": usage,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:
        # Provider exceptions can contain request details. Persist only the type.
        return {
            "id": scenario.id,
            "passed": False,
            "error_type": type(exc).__name__,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
        }


def build_report(benchmark, mode, results, model_name=None):
    passed = sum(result["passed"] for result in results)
    completed = [result for result in results if "error_type" not in result]
    errors = len(results) - len(completed)
    check_names = sorted({name for result in results for name in result.get("checks", {})})
    return {
        "dataset_version": benchmark.version,
        "mode": mode,
        "model": model_name,
        "scorer_version": SCORER_VERSION,
        "dataset_sha256": hashlib.sha256(benchmark.model_dump_json().encode()).hexdigest(),
        "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
        if mode == "agent"
        else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "execution_errors": errors,
            "behavioral_failures": len(completed) - passed,
            "completed": len(completed),
            "completed_pass_rate": passed / len(completed) if completed else None,
            "pass_rate": passed / len(results) if results else 0,
            "check_pass_rates": {
                name: sum(r.get("checks", {}).get(name, False) for r in completed) / len(completed)
                for name in check_names
            },
            "mean_latency_ms": round(sum(r["latency_ms"] for r in results) / len(results), 2)
            if results
            else 0,
        },
        "limitations": "Policy mode tests deterministic rules. Agent mode uses fixture tools; "
        "response pattern checks are heuristic. Neither measures production task success.",
        "results": results,
    }
