"""Aggregation and rendering — machine-readable (JSON) and human-readable
(console text) output, per the Milestone 9 spec's explicit requirement for
both.
"""

from typing import Any

from travel_ai_concierge.evaluation.models import CaseReport, EvaluatorOutcome

_OUTCOMES: tuple[EvaluatorOutcome, ...] = ("pass", "fail", "skip")


def summarize(reports: list[CaseReport]) -> dict[str, Any]:
    per_evaluator: dict[str, dict[str, int]] = {}
    overall = {"pass": 0, "fail": 0, "skip": 0}

    for report in reports:
        for evaluation in report.evaluations:
            bucket = per_evaluator.setdefault(evaluation.evaluator, {o: 0 for o in _OUTCOMES})
            bucket[evaluation.outcome] += 1
            overall[evaluation.outcome] += 1

    return {
        "total_cases": len(reports),
        "evaluators": per_evaluator,
        "overall": overall,
    }


def to_machine_readable(reports: list[CaseReport], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": summary,
        "cases": [
            {
                "case_id": report.case.id,
                "query_class": report.case.query_class,
                "message": report.case.message,
                "trace_id": report.result.trace_id,
                "final_response": report.result.final_response,
                "tool_calls": report.result.tool_calls,
                "evaluations": [e.model_dump() for e in report.evaluations],
            }
            for report in reports
        ],
    }


def render_human_readable(
    reports: list[CaseReport],
    summary: dict[str, Any],
    *,
    provider_model: str,
    prompt_label: str,
    is_mock_provider: bool,
) -> str:
    lines = [
        "Travel AI Concierge — Evaluation Report",
        "=" * 40,
        f"Provider model: {provider_model}  |  Prompt label: {prompt_label}",
        f"Cases: {summary['total_cases']}",
        "",
        "Per-evaluator results (pass / fail / skip / total):",
    ]
    for name, counts in summary["evaluators"].items():
        total = counts["pass"] + counts["fail"] + counts["skip"]
        lines.append(
            f"  {name:<38} {counts['pass']:>3} / {counts['fail']:>3} / {counts['skip']:>3} / {total:>3}"
        )

    overall = summary["overall"]
    total_evaluations = overall["pass"] + overall["fail"] + overall["skip"]
    lines.append("")
    lines.append(
        f"Overall: {overall['pass']} pass, {overall['fail']} fail, {overall['skip']} skip "
        f"(out of {total_evaluations} evaluator runs across {summary['total_cases']} cases)"
    )

    if is_mock_provider:
        lines.append("")
        lines.append(
            "NOTE: running against MockProvider (LLM_PROVIDER=mock, the default). "
            "MockProvider is a fixed keyword-trigger table, not a reasoning system — "
            "it never asks a clarifying question and only ever makes one of two "
            "hardcoded tool calls, regardless of the message (see providers/llm/mock.py). "
            "Tool-usage, constraint, and clarification failures above are therefore "
            "expected, not evidence of a broken agent. Set LLM_PROVIDER=anthropic for "
            "a meaningful quality signal."
        )

    failed = [
        (report.case.id, evaluation)
        for report in reports
        for evaluation in report.evaluations
        if evaluation.outcome == "fail"
    ]
    if failed:
        lines.append("")
        lines.append(f"Failed evaluations ({len(failed)}):")
        for case_id, evaluation in failed:
            lines.append(f"  [{case_id}] {evaluation.evaluator}: {evaluation.detail}")

    return "\n".join(lines)
