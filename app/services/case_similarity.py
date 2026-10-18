"""Explainable case comparisons. Historical outcomes never authorize actions."""

from app.observability.events import emit
from app.repositories.case_history import resolved_candidates
from app.services.disputes import POLICY_VERSION, evaluate_dispute

WEIGHTS = {
    "proof_status": 3,
    "proposed_action": 3,
    "order_status": 1,
    "delivery_window": 1,
    "amount_band": 1,
}


def features(snapshot):
    order = snapshot.get("order") or {}
    delivery = snapshot.get("delivery") or {}
    age = order.get("days_since_delivery")
    amount = order.get("amount_cents")
    return {
        "proof_status": delivery.get("proof_status"),
        "proposed_action": (snapshot.get("decision") or {}).get("action"),
        "order_status": order.get("status"),
        "delivery_window": (
            "within_7_days" if 0 <= age <= 7 else "outside_7_days" if age > 7 else None
        )
        if isinstance(age, int)
        else None,
        "amount_band": (
            "up_to_10000"
            if amount <= 10000
            else "10001_to_100000"
            if amount <= 100000
            else "over_100000"
        )
        if isinstance(amount, int) and amount > 0
        else None,
    }


def compare_snapshots(target, historical):
    current, prior = features(target), features(historical)
    # Missing proof and conflicting proof are never treated as interchangeable.
    if current["proof_status"] is None or current["proof_status"] != prior["proof_status"]:
        return None
    if current["proposed_action"] != prior["proposed_action"]:
        return None
    matches = [
        name for name in WEIGHTS if current[name] is not None and current[name] == prior[name]
    ]
    differences = [
        {"feature": name, "current": current[name], "historical": prior[name]}
        for name in WEIGHTS
        if name not in matches
    ]
    return {
        "similarity_score": round(
            sum(WEIGHTS[name] for name in matches) / sum(WEIGHTS.values()), 3
        ),
        "matching_features": matches,
        "differences": differences,
    }


async def similar_resolutions(db, target, limit=3):
    candidates, truncated = await resolved_candidates(db, target, POLICY_VERSION)
    items = []
    for candidate in candidates:
        snapshot = candidate.investigation
        order = snapshot.get("order") or {}
        if "status" not in order or "days_since_delivery" not in order:
            continue
        # Reevaluate the historical evidence under today's deterministic rules.
        decision = evaluate_dispute(order, snapshot.get("delivery"))
        if decision["action"] != "refund_review":
            continue
        comparison = compare_snapshots(target.investigation, snapshot)
        if comparison is not None:
            items.append(
                {
                    "reference_case_id": candidate.id,
                    **comparison,
                    "outcome": "simulated_refund",
                    "policy_version": POLICY_VERSION,
                }
            )
    items.sort(key=lambda item: (-item["similarity_score"], item["reference_case_id"]))
    emit(
        "similar_cases_completed",
        candidate_count=len(candidates),
        result_count=min(limit, len(items)),
        candidate_pool_truncated=truncated,
    )
    return {
        "case_id": target.id,
        "items": items[:limit],
        "candidate_pool_truncated": truncated,
        "policy_version": POLICY_VERSION,
        "ranking_version": "structured-similarity-v1",
        "advisory_only": True,
        "notice": "Historical simulated refunds are examples, not proof of customer satisfaction "
        "or authorization. Current evidence and policy must be checked independently.",
    }
