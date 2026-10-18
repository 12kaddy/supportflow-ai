"""python -m scripts.evaluate [--mode agent --live]"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.evaluation.runner import (
    DEFAULT_DATASET,
    build_report,
    load_benchmark,
    run_agent_case,
    run_policy_case,
)


async def evaluate_agent(benchmark, delay_seconds=0):
    from app.agents.graph import build_model
    from app.agents.models import model_identity

    model = build_model()
    results = []
    for scenario in benchmark.agent_cases:
        if results and delay_seconds:
            await asyncio.sleep(delay_seconds)
        print(f"Evaluating {scenario.id}", flush=True)
        results.append(await run_agent_case(scenario, model, guardrails=True))
    report = build_report(benchmark, "agent", results, model_identity()["model"])
    report["provider"] = model_identity()["provider"]
    completed = [row for row in results if "error_type" not in row]
    report["guardrails"] = {
        "version": "supportflow-guardrails-v1",
        "completed": len(completed),
        "claim_violation_rate_before": sum(bool(row["guardrails"]["before"]) for row in completed)
        / len(completed)
        if completed
        else None,
        "claim_violation_rate_after": sum(bool(row["guardrails"]["after"]) for row in completed)
        / len(completed)
        if completed
        else None,
        "raw_pass_rate": sum(row["raw_score"]["passed"] for row in completed) / len(completed)
        if completed
        else None,
        "scope": "Paired output checks on the same fixture-tool generations; regex rubric is not semantic proof",
    }
    usage = [item for row in completed for item in row.get("token_usage", [])]
    report["token_usage"] = (
        {
            "input_tokens": sum(item.get("input_tokens", 0) for item in usage),
            "output_tokens": sum(item.get("output_tokens", 0) for item in usage),
        }
        if usage
        else None
    )
    report["api_cost_usd"] = 0.0 if report["provider"] in {"ollama", "vllm"} else None
    report["cost_scope"] = (
        "API fees only; local compute/electricity excluded; hosted pricing unknown unless supplied in comparison"
    )
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate SupportFlow policy rules or live model behavior"
    )
    parser.add_argument("--mode", choices=["policy", "agent"], default="policy")
    parser.add_argument("--provider", choices=["groq", "ollama", "vllm"])
    parser.add_argument(
        "--delay-seconds", type=float, default=0, help="Optional pacing between scenarios"
    )
    parser.add_argument(
        "--model", help="Override model for the selected provider for this process only"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly allow configured inference calls in agent mode",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=Path(".local/evaluations"))
    parser.add_argument(
        "--scenario", action="append", help="Run only this scenario ID; may be repeated"
    )
    args = parser.parse_args()
    if not 0 <= args.delay_seconds <= 60:
        parser.error("--delay-seconds must be between 0 and 60")
    if args.mode == "agent" and not args.live:
        parser.error("Agent mode requires --live and uses the configured inference backend")
    from app.core.config import get_settings

    settings = get_settings()
    if args.provider:
        settings.llm_provider = args.provider
    if args.model:
        setattr(
            settings,
            {"groq": "groq_model", "ollama": "ollama_model", "vllm": "vllm_model"}[
                settings.llm_provider
            ],
            args.model,
        )
    benchmark = load_benchmark(args.dataset)
    if args.scenario:
        field = "agent_cases" if args.mode == "agent" else "policy_cases"
        cases = getattr(benchmark, field)
        unknown = set(args.scenario) - {case.id for case in cases}
        if unknown:
            parser.error("Unknown scenario IDs: " + ", ".join(sorted(unknown)))
        benchmark = benchmark.model_copy(
            update={field: [case for case in cases if case.id in args.scenario]}
        )
    report = (
        asyncio.run(evaluate_agent(benchmark, args.delay_seconds))
        if args.mode == "agent"
        else build_report(
            benchmark, "policy", [run_policy_case(case) for case in benchmark.policy_cases]
        )
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{args.mode}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}.json"
    output = args.output_dir / filename
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {output.resolve()}")
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
