"""Publish a comparison only from compatible recorded agent evaluation reports."""

import argparse
import json
from pathlib import Path


def comparison(paths, input_rate=None, output_rate=None):
    if any(value is not None and value < 0 for value in [input_rate, output_rate]):
        raise ValueError("Token prices cannot be negative")
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    if not reports or any(report.get("mode") != "agent" for report in reports):
        raise ValueError("Provide agent evaluation reports")
    provenance = {
        (
            r["dataset_sha256"],
            r["system_prompt_sha256"],
            r["scorer_version"],
            tuple(sorted(row["id"] for row in r["results"])),
            r.get("guardrails", {}).get("version"),
        )
        for r in reports
    }
    if len(provenance) != 1:
        raise ValueError(
            "Reports must share dataset, prompt, scorer, scenario IDs and guardrail version"
        )
    lines = [
        "# Recorded model comparison",
        "",
        "API fees exclude local hardware/electricity. Unknown hosted cost is not zero.",
        "",
        "| Provider / model | Pass rate | Raw completed pass rate | Mean latency | API cost | Claim violations before → after |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for report in reports:
        summary, guard = report["summary"], report.get("guardrails", {})
        cost = report.get("api_cost_usd")
        usage = report.get("token_usage")
        if cost is None and usage and input_rate is not None and output_rate is not None:
            cost = (
                usage["input_tokens"] * input_rate + usage["output_tokens"] * output_rate
            ) / 1_000_000
        rates = [guard.get("claim_violation_rate_before"), guard.get("claim_violation_rate_after")]
        formatted = " → ".join(
            f"{value:.1%}" if value is not None else "unavailable" for value in rates
        )
        raw = guard.get("raw_pass_rate")
        cells = [
            f"{report.get('provider', 'unknown')} / {report['model']}",
            f"{summary['passed']}/{summary['total']} ({summary['pass_rate']:.1%})",
            f"{raw:.1%}" if raw is not None else "unavailable",
            f"{summary['mean_latency_ms'] / 1000:.2f} s",
            f"USD {cost:.6f}" if cost is not None else "unknown",
            formatted,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines += [
        "",
        "Results use fixture tools, small datasets and heuristic scoring; failures/timeouts remain in overall pass rates.",
        "Raw pass rate and claim rates use completed scenarios only. No result is supplied for unrun models.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path(".local/evaluations/model-comparison.md")
    )
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        comparison(args.reports, args.input_usd_per_million, args.output_usd_per_million),
        encoding="utf-8",
    )
    print(f"Comparison: {args.output.resolve()}")


if __name__ == "__main__":
    main()
