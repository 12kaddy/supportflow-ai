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


async def evaluate_agent(benchmark):
    from app.agents.graph import build_model

    model = build_model()
    results = []
    for scenario in benchmark.agent_cases:
        print(f"Evaluating {scenario.id}", flush=True)
        results.append(await run_agent_case(scenario, model))
    return build_report(benchmark, "agent", results, model.model_name)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate SupportFlow policy rules or live model behavior"
    )
    parser.add_argument("--mode", choices=["policy", "agent"], default="policy")
    parser.add_argument(
        "--live", action="store_true", help="Allow hosted model calls in agent mode"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=Path(".local/evaluations"))
    parser.add_argument(
        "--scenario", action="append", help="Run only this scenario ID; may be repeated"
    )
    args = parser.parse_args()
    if args.mode == "agent" and not args.live:
        parser.error("Agent mode requires --live and uses your configured Groq account")
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
        asyncio.run(evaluate_agent(benchmark))
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
