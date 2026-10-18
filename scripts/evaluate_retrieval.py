"""Offline keyword benchmark; --vectors enables local hybrid embedding retrieval."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.rag.store import search_policy

DATASET = Path(__file__).resolve().parents[1] / "data/evaluations/retrieval_v1.json"


def evaluate(use_vectors=False):
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    rows = []
    for case in dataset["cases"]:
        hits = search_policy(case["query"], use_vectors=use_vectors)
        sources = list(dict.fromkeys(hit["source"] for hit in hits))
        relevant = set(case["relevant_sources"])
        first = next((rank for rank, source in enumerate(sources, 1) if source in relevant), None)
        rows.append(
            {
                "id": case["id"],
                "sources": sources,
                "hit_at_1": bool(sources and sources[0] in relevant),
                "recall_at_3": len(set(sources) & relevant) / len(relevant),
                "reciprocal_rank": 1 / first if first else 0,
                "vector_contributed": any("vector" in hit["retrieval_methods"] for hit in hits),
                "vector_status": sorted({hit["vector_status"] for hit in hits}),
            }
        )
    return {
        "dataset_version": dataset["version"],
        "mode": "hybrid" if use_vectors else "keyword",
        "summary": {
            name: sum(row[name] for row in rows) / len(rows)
            for name in ["hit_at_1", "recall_at_3", "reciprocal_rank"]
        },
        "limitations": "Small fixture corpus; source-level ranking only, not answer grounding quality.",
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vectors",
        action="store_true",
        help="Use local Chroma/embedding model; may download model files",
    )
    args = parser.parse_args()
    report = evaluate(args.vectors)
    output = Path(".local/evaluations")
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"retrieval-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"Report: {path.resolve()}")
    return 0 if report["summary"]["recall_at_3"] == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
