"""Aggregation and rendering for Milestone 11's LLM-as-judge output —
parallels evaluation/report.py's Layer 1 shape, kept separate since a 1-5
score distribution is a different kind of thing to summarize than a
pass/fail/skip count.
"""

from typing import Any

from pydantic import BaseModel

from travel_ai_concierge.evaluation.judge import JudgmentResult


class CaseJudgment(BaseModel):
    case_id: str
    query_class: str
    judgments: list[JudgmentResult]


def summarize_judgments(case_judgments: list[CaseJudgment]) -> dict[str, Any]:
    scores_by_dimension: dict[str, list[int]] = {}
    for case_judgment in case_judgments:
        for judgment in case_judgment.judgments:
            scores_by_dimension.setdefault(judgment.dimension, []).append(judgment.score)

    return {
        "total_cases": len(case_judgments),
        "average_scores": {
            dimension: sum(scores) / len(scores)
            for dimension, scores in scores_by_dimension.items()
        },
        "counts": {dimension: len(scores) for dimension, scores in scores_by_dimension.items()},
    }


def to_machine_readable(
    case_judgments: list[CaseJudgment], summary: dict[str, Any]
) -> dict[str, Any]:
    return {
        "summary": summary,
        "cases": [case_judgment.model_dump() for case_judgment in case_judgments],
    }


def render_judge_summary(
    case_judgments: list[CaseJudgment], summary: dict[str, Any], *, judge_model: str
) -> str:
    lines = [
        "LLM-as-Judge Summary",
        "=" * 40,
        f"Judge model: {judge_model}",
        f"Cases judged: {summary['total_cases']}",
        "",
        "Average scores (1=poor .. 5=excellent):",
    ]
    for dimension, average in summary["average_scores"].items():
        count = summary["counts"][dimension]
        lines.append(f"  {dimension:<25} {average:.2f}  (n={count})")

    lines.append("")
    lines.append(
        "Do not treat these as ground truth — see docs/architecture.md's 'LLM-as-Judge' "
        "section for documented biases, stochasticity, and limitations."
    )
    return "\n".join(lines)
