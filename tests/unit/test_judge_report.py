"""Tests for evaluation/judge_report.py — Milestone 11. Fully offline:
synthetic CaseJudgment fixtures, no judge/network involved.
"""

from travel_ai_concierge.evaluation.judge import JudgmentResult
from travel_ai_concierge.evaluation.judge_report import (
    CaseJudgment,
    render_judge_summary,
    summarize_judgments,
    to_machine_readable,
)


def _case_judgment(case_id: str, scores: dict[str, int]) -> CaseJudgment:
    return CaseJudgment(
        case_id=case_id,
        query_class="test",
        judgments=[
            JudgmentResult(dimension=dim, score=score, rationale="because")
            for dim, score in scores.items()
        ],
    )


def test_summarize_averages_scores_per_dimension():
    case_judgments = [
        _case_judgment("c1", {"relevance": 4, "helpfulness": 2}),
        _case_judgment("c2", {"relevance": 2}),
    ]

    summary = summarize_judgments(case_judgments)

    assert summary["total_cases"] == 2
    assert summary["average_scores"]["relevance"] == 3.0
    assert summary["average_scores"]["helpfulness"] == 2.0
    assert summary["counts"] == {"relevance": 2, "helpfulness": 1}


def test_summarize_handles_no_cases():
    summary = summarize_judgments([])
    assert summary == {"total_cases": 0, "average_scores": {}, "counts": {}}


def test_to_machine_readable_includes_case_detail():
    case_judgments = [_case_judgment("c1", {"relevance": 5})]
    summary = summarize_judgments(case_judgments)

    payload = to_machine_readable(case_judgments, summary)

    assert payload["summary"] == summary
    assert payload["cases"][0]["case_id"] == "c1"
    assert payload["cases"][0]["judgments"][0]["score"] == 5


def test_render_judge_summary_includes_model_and_limitations_pointer():
    case_judgments = [_case_judgment("c1", {"relevance": 5})]
    summary = summarize_judgments(case_judgments)

    text = render_judge_summary(case_judgments, summary, judge_model="fake-judge-v1")

    assert "fake-judge-v1" in text
    assert "relevance" in text
    assert "5.00" in text
    assert "Do not treat these as ground truth" in text
