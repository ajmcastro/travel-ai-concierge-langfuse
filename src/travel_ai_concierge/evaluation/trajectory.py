"""Milestone 13: agent trajectory evaluation.

Layer 1's evaluators (evaluators.py) mostly ask "is the final text okay" —
only `evaluate_tool_usage`/`evaluate_tool_arguments` look at *what the agent
did* at all, and even those only check via a single pass/fail, not a metric
that degrades gracefully. This module is the metrics half of the project
spec's own trajectory-evaluation list (`tool_precision`, `tool_recall`,
`unnecessary_tool_calls`, `repeated_tool_calls`, `total_tool_calls`,
`agent_steps`), computed purely from data `run_case()` already collects —
no LLM call, no extra cost, safe to compute unconditionally.

Precision/recall conventions (IR-standard, not invented here): both are
computed over the *unique* tool-name sets, so calling the right tool twice
doesn't itself hurt either score — that's what `repeated_tools` is for.
`tool_precision` is `None` (not 0.0) when no tool was called at all, since
"precision of zero calls" is undefined, not zero; `tool_recall` is `1.0`
when no tool was expected, since nothing could have been missed (vacuously
true) — mirrors Layer 1's own `skip` philosophy for "this check doesn't
apply here" rather than silently counting it as a failure.

The two clarification checks reuse `evaluate_clarification`'s exact "?" in
the response, with no tool called" heuristic (evaluators.py) in both
directions: Layer 1 only ever checks "clarified when expected"; trajectory
evaluation adds the missing direction, "did NOT ask unnecessarily when no
clarification was expected." Both are the same crude proxy, deliberately
kept consistent rather than inventing a second, different heuristic.
"""

from pydantic import BaseModel

from travel_ai_concierge.evaluation.models import CaseResult, EvaluationCase


class TrajectoryMetrics(BaseModel):
    total_tool_calls: int
    unique_tools_called: list[str]
    missing_tools: list[str]
    unnecessary_tools: list[str]
    repeated_tools: list[str]
    tool_precision: float | None
    tool_recall: float
    agent_steps: int
    asked_unnecessary_clarification: bool
    failed_to_clarify_when_expected: bool

    @property
    def correct_tool_selection(self) -> bool:
        return not self.missing_tools and not self.unnecessary_tools

    @property
    def is_healthy(self) -> bool:
        """No trajectory defect at all — the bar used to classify a case as
        having a "reasonable trajectory" when compared against the
        final-answer evaluators (see trajectory_report.py).
        """
        return (
            self.correct_tool_selection
            and not self.repeated_tools
            and not self.asked_unnecessary_clarification
            and not self.failed_to_clarify_when_expected
        )


def compute_trajectory_metrics(case: EvaluationCase, result: CaseResult) -> TrajectoryMetrics:
    expected = set(case.expected_tools)
    actual_calls = result.tool_calls
    actual_unique = list(dict.fromkeys(actual_calls))
    actual_set = set(actual_calls)

    missing = sorted(expected - actual_set)
    unnecessary = sorted(actual_set - expected)
    repeated = sorted(name for name in actual_set if actual_calls.count(name) > 1)

    true_positives = len(expected & actual_set)
    precision = (true_positives / len(actual_set)) if actual_set else None
    recall = (true_positives / len(expected)) if expected else 1.0

    looks_like_a_clarifying_question = "?" in result.final_response and not result.tool_calls
    asked_unnecessary = not case.expects_clarification and looks_like_a_clarifying_question
    failed_to_clarify = case.expects_clarification and not looks_like_a_clarifying_question

    return TrajectoryMetrics(
        total_tool_calls=len(actual_calls),
        unique_tools_called=actual_unique,
        missing_tools=missing,
        unnecessary_tools=unnecessary,
        repeated_tools=repeated,
        tool_precision=precision,
        tool_recall=recall,
        agent_steps=result.iterations,
        asked_unnecessary_clarification=asked_unnecessary,
        failed_to_clarify_when_expected=failed_to_clarify,
    )
