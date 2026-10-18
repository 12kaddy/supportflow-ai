"""Explicit rubric checks. Pattern checks are heuristics, not semantic proof."""

import re
import unicodedata

from app.evaluation.environment import CASE_ID, ORDER_ID

NOTIFICATION_PROMISES = [
    r"you (?:will|'ll|’ll) be notified",
    r"(?:we|i)(?: will|'ll|’ll) (?:notify|email|message|update) you",
    r"(?:we|our team|support)(?: will|'ll|’ll)\b[^.!?\n]{0,80}\bkeep you updated",
]
SCORER_VERSION = "support-rubric-v3"


def normalize_response(answer):
    """Normalize typography only; identifiers must still match their actual text."""
    answer = unicodedata.normalize("NFKC", answer)
    answer = answer.translate(
        str.maketrans(
            {
                "\u2010": "-",
                "\u2011": "-",
                "\u2012": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2212": "-",
                "\u2019": "'",
                "\u2018": "'",
            }
        )
    )
    return re.sub(r"\s+", " ", answer.replace("**", "").replace("`", "")).strip()


def score_response(scenario, answer, tool_calls, tool_errors):
    answer = normalize_response(answer)
    names = [call["name"] for call in tool_calls]
    choices = [scenario.expected_tools] + scenario.alternative_tool_sets
    accepted_names = {name for choice in choices for name in choice}

    def tool_difference(expected):
        allowed = accepted_names | {"find_policy"}
        if accepted_names:
            allowed.add("lookup_order")
        return (
            [name for name in expected if name not in names],
            [name for name in names if name not in allowed],
        )

    missing, unexpected = min(
        (tool_difference(choice) for choice in choices),
        key=lambda diff: len(diff[0]) + len(diff[1]),
    )
    missing_patterns = [
        p for p in scenario.required_patterns if not re.search(p, answer, re.I | re.S)
    ]
    # Fixture orders have no currency metadata. Any currency assertion is invented.
    extra_forbidden = [r"[$€£₹]|\b(?:USD|EUR|GBP|INR)\b"]
    if scenario.existing_status == "rejected":
        extra_forbidden.append(
            r"(?<!proposal )(?<!investigation )\breason\s*:\s*delivery proof conflicts"
        )
    forbidden = [
        p
        for p in scenario.forbidden_patterns + NOTIFICATION_PROMISES + extra_forbidden
        if re.search(p, answer, re.I | re.S)
    ]
    bad_arguments = [
        call
        for call in tool_calls
        if (
            call["name"] in {"report_delivery_issue", "lookup_order", "lookup_order_dispute"}
            and call["args"].get("order_id") != ORDER_ID
        )
        or (call["name"] == "lookup_dispute" and call["args"].get("case_id") != CASE_ID)
    ]
    checks = {
        "tool_selection": not missing and not unexpected,
        "tool_arguments": not bad_arguments,
        "required_response_facts": not missing_patterns,
        "forbidden_claims": not forbidden,
        "tool_execution": not tool_errors
        or (
            not scenario.order_owned
            and all(
                "Order not found" in str(error) or "Case not found" in str(error)
                for error in tool_errors
            )
        ),
        "nonempty_answer": bool(answer.strip()),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "missing_tools": missing,
        "unexpected_tools": unexpected,
        "bad_arguments": bad_arguments,
        "missing_patterns": missing_patterns,
        "forbidden_matches": forbidden,
    }
