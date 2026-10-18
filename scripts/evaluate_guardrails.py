"""Paired claim checks on a labeled adversarial-response fixture set."""

import argparse
import hashlib
import json
from pathlib import Path

from app.guardrails.output import verify_answer


def evaluate(path):
    source = Path(path).read_bytes()
    dataset = json.loads(source)
    rows = []
    for case in dataset["cases"]:
        fact = {
            "case_id": "CASE-FIXTURE",
            "order_id": "ORD-FIXTURE",
            "status": case["status"],
            "approved_amount_cents": 10000 if case["status"] in {"approved", "resolved"} else None,
            "policy_version": "delivery-dispute-v1",
            "policy_source": "delivery_dispute_policy.md",
        }
        answer, verdict = verify_answer(case["answer"], [("lookup_dispute", fact)])
        rows.append({"id": case["id"], "unsafe_label": case["unsafe"], **verdict, "answer": answer})
    return {
        "dataset_version": dataset["version"],
        "dataset_sha256": hashlib.sha256(source).hexdigest(),
        "scope": dataset["source"],
        "results": rows,
        "summary": {
            "total": len(rows),
            "claim_violation_rate_before": sum(bool(row["before"]) for row in rows) / len(rows),
            "claim_violation_rate_after": sum(bool(row["after"]) for row in rows) / len(rows),
            "label_detection_accuracy": sum(
                bool(row["before"]) == row["unsafe_label"] for row in rows
            )
            / len(rows),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/evaluations/guardrails_v1.json"))
    parser.add_argument("--output", type=Path, default=Path(".local/evaluations/guardrails.json"))
    args = parser.parse_args()
    report = evaluate(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {args.output.resolve()}")
    return int(
        report["summary"]["claim_violation_rate_after"] != 0
        or report["summary"]["label_detection_accuracy"] != 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
