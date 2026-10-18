"""Rescore saved model output without calling a provider or altering the source."""

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from app.evaluation.runner import DEFAULT_DATASET, build_report, load_benchmark
from app.evaluation.scoring import score_response


def rescore(source, benchmark):
    if source.get("mode") != "agent":
        raise ValueError("Only agent reports can be rescored")
    cases = {case.id: case for case in benchmark.agent_cases}
    rows = source["results"]
    if len(rows) != len(cases) or {row["id"] for row in rows} != set(cases):
        raise ValueError("Report scenario IDs must match the target benchmark exactly")
    results = []
    for row in rows:
        if "error_type" in row:
            results.append({**row, "passed": False})
            continue
        updated = score_response(
            cases[row["id"]], row["answer"], row["tool_calls"], row["tool_errors"]
        )
        results.append({**row, **updated})
    report = build_report(benchmark, "agent", results, source.get("model"))
    # Retain the original inference prompt fingerprint; this is not a new model run.
    report["system_prompt_sha256"] = source.get("system_prompt_sha256")
    report["rescore"] = {
        "new_inference": False,
        "source_created_at": source.get("created_at"),
        "source_dataset_sha256": source.get("dataset_sha256"),
        "source_passed": source["summary"]["passed"],
        "source_report_sha256": hashlib.sha256(
            json.dumps(source, sort_keys=True).encode()
        ).hexdigest(),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    source = json.loads(args.report.read_text(encoding="utf-8"))
    report = rescore(source, load_benchmark(args.dataset))
    output = args.report.with_name(args.report.stem + f"-rescored-{uuid4().hex[:8]}.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    for row in report["results"]:
        if not row["passed"]:
            detail = row.get("error_type") or row.get("forbidden_matches", [])
            print(f"FAIL {row['id']}: " + json.dumps(detail, ensure_ascii=True))
    print(f"Rescored report: {output.resolve()}")
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
