"""Tests for evaluation/report.py — Milestone 9. Fully offline: synthetic
CaseReport fixtures, no agent/provider/network involved.
"""

from travel_ai_concierge.evaluation.models import (
    CaseReport,
    CaseResult,
    EvaluationCase,
    EvaluatorResult,
)
from travel_ai_concierge.evaluation.report import (
    render_human_readable,
    summarize,
    to_machine_readable,
)


def _report(case_id: str, outcomes: list[str]) -> CaseReport:
    case = EvaluationCase(id=case_id, query_class="test", message="hi")
    result = CaseResult(
        case_id=case_id,
        query_class="test",
        trace_id="trace-x",
        tool_calls=[],
        tool_arguments_by_name={},
        tool_result_texts=[],
        final_response="a response",
        iterations=1,
    )
    evaluations = [
        EvaluatorResult(
            evaluator=f"evaluator_{i}", outcome=outcome, detail="" if outcome != "fail" else "boom"
        )
        for i, outcome in enumerate(outcomes)
    ]
    return CaseReport(case=case, result=result, evaluations=evaluations)


def test_summarize_counts_outcomes_per_evaluator_and_overall():
    reports = [
        _report("c1", ["pass", "fail"]),
        _report("c2", ["pass", "skip"]),
    ]

    summary = summarize(reports)

    assert summary["total_cases"] == 2
    assert summary["evaluators"]["evaluator_0"] == {"pass": 2, "fail": 0, "skip": 0}
    assert summary["evaluators"]["evaluator_1"] == {"pass": 0, "fail": 1, "skip": 1}
    assert summary["overall"] == {"pass": 2, "fail": 1, "skip": 1}


def test_summarize_handles_empty_reports():
    summary = summarize([])
    assert summary["total_cases"] == 0
    assert summary["overall"] == {"pass": 0, "fail": 0, "skip": 0}


def test_to_machine_readable_includes_case_detail():
    reports = [_report("c1", ["pass"])]
    summary = summarize(reports)

    payload = to_machine_readable(reports, summary)

    assert payload["summary"] == summary
    assert payload["cases"][0]["case_id"] == "c1"
    assert payload["cases"][0]["evaluations"][0]["outcome"] == "pass"


def test_human_readable_report_includes_summary_and_failures():
    reports = [_report("c1", ["fail"])]
    summary = summarize(reports)

    text = render_human_readable(
        reports,
        summary,
        provider_model="mock-echo-v1",
        prompt_label="production",
        is_mock_provider=False,
    )

    assert "Cases: 1" in text
    assert "mock-echo-v1" in text
    assert "[c1] evaluator_0: boom" in text


def test_human_readable_report_notes_mock_provider_limitation_only_when_mock():
    reports = [_report("c1", ["pass"])]
    summary = summarize(reports)

    with_note = render_human_readable(
        reports,
        summary,
        provider_model="mock-echo-v1",
        prompt_label="production",
        is_mock_provider=True,
    )
    without_note = render_human_readable(
        reports,
        summary,
        provider_model="claude-x",
        prompt_label="production",
        is_mock_provider=False,
    )

    assert "MockProvider" in with_note
    assert "MockProvider" not in without_note
