"""Milestone 13: compares final-answer evaluation (Layer 1's text-quality
evaluators) against trajectory evaluation (trajectory.py) for the same
cases — parallels judge_report.py's shape (a separate module, not merged
into report.py, since this is a genuinely different kind of comparison,
not just another evaluator in the same pass/fail/skip list).

Layer 1's own EVALUATORS list (evaluators.py) mixes two different
questions under one flat list: "does the text look okay"
(`response_is_nonempty`, `response_references_tool_result`) and "did the
agent do the right thing" (`tool_usage_matches_expected`,
`tool_arguments_satisfy_constraints`, `clarifying_question_when_expected`).
The project spec's own framing — "compare final-answer evaluation with
trajectory evaluation... good answer != good trajectory" — requires telling
these apart, so FINAL_ANSWER_EVALUATORS below picks out only the first
group; the trajectory axis comes entirely from trajectory.py's
TrajectoryMetrics, not from Layer 1's tool-selection checks (which would
double-count the same signal on both axes).
"""

from typing import Any, Literal

from pydantic import BaseModel

from travel_ai_concierge.evaluation.models import CaseReport, EvaluatorResult
from travel_ai_concierge.evaluation.trajectory import TrajectoryMetrics, compute_trajectory_metrics

FINAL_ANSWER_EVALUATORS = {"response_is_nonempty", "response_references_tool_result"}

Divergence = Literal["aligned", "good_answer_poor_trajectory", "poor_answer_good_trajectory"]


def final_answer_is_healthy(evaluations: list[EvaluatorResult]) -> bool:
    """ "Healthy" means no FAIL among the text-quality evaluators — a SKIP
    (e.g. groundedness proxy skipping because no tool returned named
    results) is not a text-quality failure, same "skip isn't a failure"
    principle Layer 1 already uses throughout.
    """
    return not any(
        e.outcome == "fail" for e in evaluations if e.evaluator in FINAL_ANSWER_EVALUATORS
    )


def classify_divergence(
    evaluations: list[EvaluatorResult], trajectory: TrajectoryMetrics
) -> Divergence:
    answer_ok = final_answer_is_healthy(evaluations)
    trajectory_ok = trajectory.is_healthy
    if answer_ok and not trajectory_ok:
        return "good_answer_poor_trajectory"
    if not answer_ok and trajectory_ok:
        return "poor_answer_good_trajectory"
    return "aligned"


class TrajectoryCaseReport(BaseModel):
    case_id: str
    query_class: str
    trajectory: TrajectoryMetrics
    final_answer_ok: bool
    divergence: Divergence


def build_trajectory_reports(reports: list[CaseReport]) -> list[TrajectoryCaseReport]:
    built = []
    for report in reports:
        trajectory = compute_trajectory_metrics(report.case, report.result)
        built.append(
            TrajectoryCaseReport(
                case_id=report.case.id,
                query_class=report.case.query_class,
                trajectory=trajectory,
                final_answer_ok=final_answer_is_healthy(report.evaluations),
                divergence=classify_divergence(report.evaluations, trajectory),
            )
        )
    return built


def summarize_trajectories(trajectory_reports: list[TrajectoryCaseReport]) -> dict[str, Any]:
    divergence_counts = {
        "aligned": 0,
        "good_answer_poor_trajectory": 0,
        "poor_answer_good_trajectory": 0,
    }
    precisions = []
    recalls = []
    steps = []
    total_repeated = 0
    total_missing = 0
    total_unnecessary = 0

    for tr in trajectory_reports:
        divergence_counts[tr.divergence] += 1
        if tr.trajectory.tool_precision is not None:
            precisions.append(tr.trajectory.tool_precision)
        recalls.append(tr.trajectory.tool_recall)
        steps.append(tr.trajectory.agent_steps)
        total_repeated += len(tr.trajectory.repeated_tools)
        total_missing += len(tr.trajectory.missing_tools)
        total_unnecessary += len(tr.trajectory.unnecessary_tools)

    return {
        "total_cases": len(trajectory_reports),
        "divergence_counts": divergence_counts,
        "average_tool_precision": sum(precisions) / len(precisions) if precisions else None,
        "average_tool_recall": sum(recalls) / len(recalls) if recalls else None,
        "average_agent_steps": sum(steps) / len(steps) if steps else None,
        "total_repeated_tool_calls": total_repeated,
        "total_missing_tool_calls": total_missing,
        "total_unnecessary_tool_calls": total_unnecessary,
    }


def compute_quality_metrics(reports: list[CaseReport]) -> tuple[float | None, float]:
    """(quality_pass_rate, trajectory_healthy_rate) — the two-metric quality
    signal reused by Milestone 14 (cost/latency config comparison) and
    Milestone 17 (regression detection against a committed baseline).

    Deliberately two numbers, not one: Milestone 16 found a real regression
    where the aggregate Layer 1 pass rate moved in the *improving* direction
    while `trajectory_healthy_rate` caught the actual damage — a gate
    watching only the first would have missed it.

    `quality_pass_rate` is Layer 1's pass / (pass + fail), skips excluded
    (skips are "not applicable," not evidence either way); `None` if there's
    nothing to compare (every evaluation skipped). `trajectory_healthy_rate`
    is the fraction of cases with `TrajectoryMetrics.is_healthy` — `0.0`,
    not `None`, when there are no cases, since an empty run has no health at
    all to report as "unknown."
    """
    total_cases = len(reports)
    pass_count = sum(1 for r in reports for e in r.evaluations if e.outcome == "pass")
    fail_count = sum(1 for r in reports for e in r.evaluations if e.outcome == "fail")
    quality_pass_rate = (
        pass_count / (pass_count + fail_count) if (pass_count + fail_count) else None
    )

    trajectory_reports = build_trajectory_reports(reports)
    healthy_count = sum(1 for tr in trajectory_reports if tr.trajectory.is_healthy)
    trajectory_healthy_rate = healthy_count / total_cases if total_cases else 0.0

    return quality_pass_rate, trajectory_healthy_rate


def to_machine_readable(
    trajectory_reports: list[TrajectoryCaseReport], summary: dict[str, Any]
) -> dict[str, Any]:
    return {
        "summary": summary,
        "cases": [tr.model_dump() for tr in trajectory_reports],
    }


def render_trajectory_summary(
    trajectory_reports: list[TrajectoryCaseReport], summary: dict[str, Any]
) -> str:
    lines = [
        "Agent Trajectory Evaluation (Milestone 13)",
        "=" * 40,
        f"Cases: {summary['total_cases']}",
        "",
        f"Average tool precision: {_fmt(summary['average_tool_precision'])}",
        f"Average tool recall:    {_fmt(summary['average_tool_recall'])}",
        f"Average agent steps:    {_fmt(summary['average_agent_steps'])}",
        f"Repeated tool calls (total): {summary['total_repeated_tool_calls']}",
        f"Missing tool calls (total):  {summary['total_missing_tool_calls']}",
        f"Unnecessary tool calls (total): {summary['total_unnecessary_tool_calls']}",
        "",
        "Divergence between final-answer and trajectory evaluation:",
        f"  aligned                        {summary['divergence_counts']['aligned']}",
        f"  good answer, poor trajectory   {summary['divergence_counts']['good_answer_poor_trajectory']}",
        f"  poor answer, good trajectory   {summary['divergence_counts']['poor_answer_good_trajectory']}",
    ]

    divergent = [tr for tr in trajectory_reports if tr.divergence != "aligned"]
    if divergent:
        lines.append("")
        lines.append(f"Divergent cases ({len(divergent)}):")
        for tr in divergent:
            lines.append(
                f"  [{tr.case_id}] {tr.divergence}: "
                f"missing={tr.trajectory.missing_tools}, "
                f"unnecessary={tr.trajectory.unnecessary_tools}, "
                f"repeated={tr.trajectory.repeated_tools}"
            )

    lines.append("")
    lines.append(
        "NOTE: MockProvider (the default) can only ever call at most one tool and never "
        "repeats a call, so 'good answer, poor trajectory' cases above come from a missing "
        "or unnecessary tool call, never a repeat. It also always derives its final text "
        "directly from whatever it did, so it cannot produce 'poor answer, good trajectory' "
        "at all — see docs/RATIONALE_PER_MILESTONE.md (Milestone 13) for a hand-built "
        "example of that case instead."
    )
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"
