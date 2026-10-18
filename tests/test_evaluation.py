import json
import sys

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.evaluation.environment import make_fixture_tools
from app.evaluation.runner import build_report, load_benchmark, run_agent_case, run_policy_case
from app.evaluation.scoring import score_response
from app.tools.customer_tools import make_tools


class FixtureModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_versioned_policy_benchmark():
    benchmark = load_benchmark()
    results = [run_policy_case(case) for case in benchmark.policy_cases]
    assert len(results) == 10
    assert all(r["passed"] for r in results)
    report = build_report(benchmark, "policy", results)
    assert report["summary"]["pass_rate"] == 1
    assert report["summary"]["check_pass_rates"]["no_payment_authorization"] == 1
    json.dumps(report)


def test_tool_fixture_surface_matches_customer_tools():
    case = load_benchmark().agent_cases[0]
    real_tools = {t.name: t for t in make_tools("customer")}
    fixtures = {t.name: t for t in make_fixture_tools(case)}
    assert real_tools.keys() == fixtures.keys()
    for name in real_tools:
        assert real_tools[name].args.keys() == fixtures[name].args.keys()


def test_scoring_catches_unsupported_claims_and_wrong_arguments():
    case = load_benchmark().agent_cases[0]
    score = score_response(
        case,
        "You will be notified. Your refund is approved.",
        [
            {
                "name": "report_delivery_issue",
                "args": {"order_id": "invented"},
                "id": "1",
            }
        ],
        [],
    )
    assert score["passed"] is False
    assert score["checks"]["forbidden_claims"] is False
    assert score["checks"]["required_response_facts"] is False
    assert score["checks"]["tool_arguments"] is False


def test_status_request_cannot_score_a_new_case_as_correct():
    case = next(c for c in load_benchmark().agent_cases if c.id == "status-by-order")
    score = score_response(
        case,
        "CASE-EVAL-1001 is awaiting review",
        [
            {
                "name": "report_delivery_issue",
                "args": {"order_id": "ORD-1001"},
                "id": "1",
            }
        ],
        [],
    )
    assert score["passed"] is False
    assert score["unexpected_tools"] == ["report_delivery_issue"]


@pytest.mark.asyncio
async def test_agent_evaluation_records_real_graph_tool_trace():
    case = load_benchmark().agent_cases[0]
    model = FixtureModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "report_delivery_issue",
                            "args": {"order_id": "ORD-1001", "issue": "Missing"},
                            "id": "test-call",
                        }
                    ],
                ),
                AIMessage(
                    content="CASE-EVAL-1001 is awaiting_review under delivery-dispute-v1. "
                    "A reviewer must assess the proposal. Ask for status here."
                ),
            ]
        )
    )
    result = await run_agent_case(case, model)
    assert result["passed"] is True
    assert result["tool_calls"][0]["name"] == "report_delivery_issue"
    assert result["token_usage"] == []  # Fake model provides no token usage.
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_agent_errors_are_recorded_without_exception_secrets():
    case = load_benchmark().agent_cases[0]
    result = await run_agent_case(case, FixtureModel(messages=iter([])))
    assert result["passed"] is False
    assert result["error_type"]
    assert "answer" not in result


def test_cli_writes_report_and_requires_opt_in_for_hosted_calls(tmp_path, monkeypatch):
    from scripts.evaluate import main

    monkeypatch.setattr(sys, "argv", ["evaluate", "--output-dir", str(tmp_path)])
    assert main() == 0
    reports = list(tmp_path.glob("policy-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["summary"]["passed"] == 10
    assert len(report["dataset_sha256"]) == 64
    monkeypatch.setattr(sys, "argv", ["evaluate", "--mode", "agent"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_cli_returns_failure_when_a_scenario_fails(tmp_path, monkeypatch):
    from scripts.evaluate import main

    benchmark = load_benchmark()
    benchmark.policy_cases[0].expected_action = "incorrect-expectation"
    dataset = tmp_path / "scenarios.json"
    dataset.write_text(benchmark.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate", "--dataset", str(dataset), "--output-dir", str(tmp_path / "reports")],
    )
    assert main() == 1


def test_unicode_typography_does_not_change_identifier_score():
    case = load_benchmark().agent_cases[0]
    answer = "CASE\u2011EVAL\u20111001 is awaiting_review under delivery\u2011dispute\u2011v1. A reviewer must assess it."
    calls = [{"name": "report_delivery_issue", "args": {"order_id": "ORD-1001"}}]
    assert score_response(case, answer, calls, [])["passed"] is True
    wrong_id = answer.replace("1001", "1002")
    assert score_response(case, wrong_id, calls, [])["passed"] is False


def test_safe_existing_case_lookup_is_accepted_but_status_creation_is_not():
    benchmark = load_benchmark()
    case = next(c for c in benchmark.agent_cases if c.id == "reuse-active-case")
    calls = [{"name": "lookup_order_dispute", "args": {"order_id": "ORD-1001"}}]
    answer = "Existing case CASE-EVAL-1001 was found."
    assert score_response(case, answer, calls, [])["passed"] is True


@pytest.mark.parametrize(
    "answer",
    [
        "Our team will investigate and keep you updated on the outcome.",
        "The approved simulated refund is $100.00.",
    ],
)
def test_additional_unsupported_claims_are_detected(answer):
    case = load_benchmark().agent_cases[0]
    result = score_response(case, answer, [], [])
    assert result["checks"]["forbidden_claims"] is False


def test_proposal_reason_is_not_a_rejection_reason():
    case = next(c for c in load_benchmark().agent_cases if c.id == "rejected-case")
    result = score_response(
        case, "Rejected. **Reason:** Delivery proof conflicts with the destination.", [], []
    )
    assert result["checks"]["forbidden_claims"] is False
    for label in ["Proposal reason", "Investigation reason"]:
        safe = score_response(
            case, f"Rejected. **{label}:** Delivery proof conflicts with the destination.", [], []
        )
        assert safe["checks"]["forbidden_claims"] is True


def test_rescore_preserves_inference_provenance_and_source():
    from copy import deepcopy

    from scripts.rescore import rescore

    benchmark = load_benchmark()
    rows = [
        {"id": case.id, "passed": False, "error_type": "TimeoutError", "latency_ms": 1}
        for case in benchmark.agent_cases
    ]
    source = build_report(benchmark, "agent", rows, "old-model")
    source["system_prompt_sha256"] = "original-inference-prompt"
    before = deepcopy(source)
    report = rescore(source, benchmark)
    assert source == before
    assert report["system_prompt_sha256"] == "original-inference-prompt"
    assert report["rescore"]["new_inference"] is False
    assert report["summary"]["passed"] == 0


def test_execution_errors_are_separate_from_behavioral_failures():
    report = build_report(
        load_benchmark(),
        "agent",
        [
            {"id": "a", "passed": True, "checks": {"tool_selection": True}, "latency_ms": 1},
            {"id": "b", "passed": False, "error_type": "RateLimitError", "latency_ms": 1},
        ],
    )
    summary = report["summary"]
    assert summary["execution_errors"] == 1
    assert summary["behavioral_failures"] == 0
    assert summary["completed_pass_rate"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["check_pass_rates"]["tool_selection"] == 1


def test_cli_can_select_one_scenario(tmp_path, monkeypatch):
    from scripts.evaluate import main

    monkeypatch.setattr(
        sys, "argv", ["evaluate", "--scenario", "conflicting-proof", "--output-dir", str(tmp_path)]
    )
    assert main() == 0
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["summary"]["total"] == 1
    assert report["results"][0]["id"] == "conflicting-proof"
