"""Layer 1 (deterministic) evaluators — Milestone 9.

No LLM judge here at all (that's Milestone 11's `JudgeProvider`). Each
evaluator is a plain function `(case, result) -> EvaluatorResult` returning
one of pass/fail/skip — "skip" for a case this evaluator's check simply
doesn't apply to (e.g. checking tool arguments when no tool was expected),
so a case that's out of scope for a check doesn't get counted as a failure.

Adapted from the project spec's own suggested Layer 1 metrics list to what
this agent can actually be evaluated on:
- "output JSON/schema validity" and "itinerary day count" are not
  applicable — this agent returns plain text, not structured itineraries
  (no `build_itinerary` tool exists yet).
- "response contains required citations/evidence" is reinterpreted as a
  concrete, fully deterministic groundedness *proxy*: does the final
  response mention something the tool actually returned. Real groundedness
  scoring is Layer 2 (LLM-as-judge, Milestone 11) — this is a substring
  check, not semantic evaluation.
- "unsupported destination avoided" isn't its own evaluator — an early
  design considered checking the response for fabricated destination
  names, but a legitimately helpful agent might reasonably suggest a real
  destination as an alternative when asked about one that doesn't exist,
  which that check would incorrectly flag as fabrication. Coverage for
  this query class comes from `tool_usage_matches_expected` and the
  groundedness proxy's natural `skip` when a tool call legitimately
  returns nothing, not a bespoke check.
"""

import json
from collections.abc import Callable

from travel_ai_concierge.evaluation.models import CaseResult, EvaluationCase, EvaluatorResult

Evaluator = Callable[[EvaluationCase, CaseResult], EvaluatorResult]


def _tags_overlap(expected: list[str], actual: object) -> bool:
    if not isinstance(actual, list):
        return False
    return bool(set(expected) & set(actual))


def evaluate_tool_usage(case: EvaluationCase, result: CaseResult) -> EvaluatorResult:
    name = "tool_usage_matches_expected"
    expected = set(case.expected_tools)
    actual = set(result.tool_calls)
    if expected == actual:
        return EvaluatorResult(evaluator=name, outcome="pass")
    return EvaluatorResult(
        evaluator=name,
        outcome="fail",
        detail=f"expected tools {sorted(expected)}, got {sorted(actual)}",
    )


def evaluate_tool_arguments(case: EvaluationCase, result: CaseResult) -> EvaluatorResult:
    name = "tool_arguments_satisfy_constraints"
    if not case.expected_tools or not case.expected_arguments:
        return EvaluatorResult(
            evaluator=name, outcome="skip", detail="no expected arguments for this case"
        )

    tool_name = case.expected_tools[0]
    actual_args = result.tool_arguments_by_name.get(tool_name)
    if actual_args is None:
        return EvaluatorResult(
            evaluator=name, outcome="skip", detail=f"{tool_name!r} was never called"
        )

    mismatches = []
    for key, expected_value in case.expected_arguments.items():
        actual_value = actual_args.get(key)
        if key == "tags":
            if not _tags_overlap(expected_value, actual_value):
                mismatches.append(
                    f"tags: expected overlap with {expected_value}, got {actual_value}"
                )
        elif actual_value != expected_value:
            mismatches.append(f"{key}: expected {expected_value!r}, got {actual_value!r}")

    if mismatches:
        return EvaluatorResult(evaluator=name, outcome="fail", detail="; ".join(mismatches))
    return EvaluatorResult(evaluator=name, outcome="pass")


def evaluate_response_nonempty(case: EvaluationCase, result: CaseResult) -> EvaluatorResult:
    name = "response_is_nonempty"
    if result.final_response and result.final_response.strip():
        return EvaluatorResult(evaluator=name, outcome="pass")
    return EvaluatorResult(evaluator=name, outcome="fail", detail="final response was empty")


def _extract_result_names(tool_result_texts: list[str]) -> list[str]:
    names: list[str] = []
    for text in tool_result_texts:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.append(item["name"])
    return names


def evaluate_groundedness_proxy(case: EvaluationCase, result: CaseResult) -> EvaluatorResult:
    name = "response_references_tool_result"
    if not case.expected_tools:
        return EvaluatorResult(
            evaluator=name, outcome="skip", detail="no tool expected for this case"
        )

    names = _extract_result_names(result.tool_result_texts)
    if not names:
        return EvaluatorResult(
            evaluator=name, outcome="skip", detail="tool call(s) returned no named results"
        )

    response_lower = result.final_response.lower()
    if any(n.lower() in response_lower for n in names):
        return EvaluatorResult(evaluator=name, outcome="pass")
    return EvaluatorResult(
        evaluator=name,
        outcome="fail",
        detail=f"final response mentions none of the tool's returned names: {names}",
    )


def evaluate_clarification(case: EvaluationCase, result: CaseResult) -> EvaluatorResult:
    name = "clarifying_question_when_expected"
    if not case.expects_clarification:
        return EvaluatorResult(
            evaluator=name, outcome="skip", detail="clarification not expected for this case"
        )

    looks_like_a_question = "?" in result.final_response
    no_tool_called = not result.tool_calls
    if looks_like_a_question and no_tool_called:
        return EvaluatorResult(evaluator=name, outcome="pass")
    return EvaluatorResult(
        evaluator=name,
        outcome="fail",
        detail=(
            "expected a clarifying question with no tool call; got "
            f"tool_calls={result.tool_calls}, response={result.final_response!r}"
        ),
    )


EVALUATORS: list[Evaluator] = [
    evaluate_tool_usage,
    evaluate_tool_arguments,
    evaluate_response_nonempty,
    evaluate_groundedness_proxy,
    evaluate_clarification,
]
