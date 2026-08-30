"""Unit tests for each Layer 1 evaluator (Milestone 9), fully offline.

Every test builds its own EvaluationCase/CaseResult by hand — no agent or
provider invocation at all — so these test the evaluators' own logic in
isolation, independent of what MockProvider or a real provider would
actually produce (that's tests/unit/test_evaluation_runner.py's job).
"""

from travel_ai_concierge.evaluation.evaluators import (
    evaluate_clarification,
    evaluate_groundedness_proxy,
    evaluate_response_nonempty,
    evaluate_tool_arguments,
    evaluate_tool_usage,
)
from travel_ai_concierge.evaluation.models import CaseResult, EvaluationCase


def _case(**kwargs) -> EvaluationCase:
    defaults = {"id": "case-1", "query_class": "test", "message": "hello"}
    return EvaluationCase(**{**defaults, **kwargs})


def _result(**kwargs) -> CaseResult:
    defaults = {
        "case_id": "case-1",
        "query_class": "test",
        "trace_id": "trace-1",
        "tool_calls": [],
        "tool_arguments_by_name": {},
        "tool_result_texts": [],
        "final_response": "some response",
        "iterations": 1,
    }
    return CaseResult(**{**defaults, **kwargs})


# --- evaluate_tool_usage ---


def test_tool_usage_passes_on_exact_match():
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_calls=["search_hotels"])
    assert evaluate_tool_usage(case, result).outcome == "pass"


def test_tool_usage_passes_when_neither_expects_nor_calls_a_tool():
    case = _case(expected_tools=[])
    result = _result(tool_calls=[])
    assert evaluate_tool_usage(case, result).outcome == "pass"


def test_tool_usage_fails_on_mismatch():
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_calls=["search_destinations"])
    evaluation = evaluate_tool_usage(case, result)
    assert evaluation.outcome == "fail"
    assert "search_hotels" in evaluation.detail
    assert "search_destinations" in evaluation.detail


def test_tool_usage_ignores_call_order():
    case = _case(expected_tools=["search_hotels", "get_destination_information"])
    result = _result(tool_calls=["get_destination_information", "search_hotels"])
    assert evaluate_tool_usage(case, result).outcome == "pass"


# --- evaluate_tool_arguments ---


def test_tool_arguments_skips_when_no_expected_arguments():
    case = _case(expected_tools=["search_hotels"], expected_arguments={})
    result = _result(tool_calls=["search_hotels"], tool_arguments_by_name={"search_hotels": {}})
    assert evaluate_tool_arguments(case, result).outcome == "skip"


def test_tool_arguments_skips_when_expected_tool_never_called():
    case = _case(expected_tools=["search_hotels"], expected_arguments={"destination_id": "algarve"})
    result = _result(tool_calls=[], tool_arguments_by_name={})
    evaluation = evaluate_tool_arguments(case, result)
    assert evaluation.outcome == "skip"


def test_tool_arguments_passes_on_exact_scalar_match():
    case = _case(
        expected_tools=["search_hotels"],
        expected_arguments={"destination_id": "algarve", "family_friendly": True},
    )
    result = _result(
        tool_calls=["search_hotels"],
        tool_arguments_by_name={
            "search_hotels": {"destination_id": "algarve", "family_friendly": True}
        },
    )
    assert evaluate_tool_arguments(case, result).outcome == "pass"


def test_tool_arguments_fails_on_scalar_mismatch():
    case = _case(expected_tools=["search_hotels"], expected_arguments={"destination_id": "algarve"})
    result = _result(
        tool_calls=["search_hotels"],
        tool_arguments_by_name={"search_hotels": {"destination_id": "lisbon"}},
    )
    evaluation = evaluate_tool_arguments(case, result)
    assert evaluation.outcome == "fail"
    assert "algarve" in evaluation.detail
    assert "lisbon" in evaluation.detail


def test_tool_arguments_tags_pass_on_any_overlap_not_exact_match():
    case = _case(
        expected_tools=["search_destinations"], expected_arguments={"tags": ["beach", "quiet"]}
    )
    result = _result(
        tool_calls=["search_destinations"],
        tool_arguments_by_name={"search_destinations": {"tags": ["beach", "family"]}},
    )
    # Only "beach" overlaps — that's enough; exact-set equality is not required.
    assert evaluate_tool_arguments(case, result).outcome == "pass"


def test_tool_arguments_tags_fail_on_zero_overlap():
    case = _case(expected_tools=["search_destinations"], expected_arguments={"tags": ["beach"]})
    result = _result(
        tool_calls=["search_destinations"],
        tool_arguments_by_name={"search_destinations": {"tags": ["culture"]}},
    )
    assert evaluate_tool_arguments(case, result).outcome == "fail"


# --- evaluate_response_nonempty ---


def test_response_nonempty_passes_on_real_content():
    assert (
        evaluate_response_nonempty(_case(), _result(final_response="a real answer")).outcome
        == "pass"
    )


def test_response_nonempty_fails_on_blank_string():
    assert evaluate_response_nonempty(_case(), _result(final_response="   ")).outcome == "fail"


# --- evaluate_groundedness_proxy ---


def test_groundedness_proxy_skips_when_no_tool_expected():
    case = _case(expected_tools=[])
    result = _result(tool_result_texts=[])
    assert evaluate_groundedness_proxy(case, result).outcome == "skip"


def test_groundedness_proxy_skips_when_tool_result_has_no_names():
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_result_texts=["[]"])
    assert evaluate_groundedness_proxy(case, result).outcome == "skip"


def test_groundedness_proxy_passes_when_response_mentions_a_returned_name():
    case = _case(expected_tools=["search_hotels"])
    result = _result(
        tool_result_texts=['[{"name": "Algarve Beach Resort", "price_band": "luxury"}]'],
        final_response="I'd recommend the Algarve Beach Resort for your trip.",
    )
    assert evaluate_groundedness_proxy(case, result).outcome == "pass"


def test_groundedness_proxy_fails_when_response_ignores_returned_names():
    case = _case(expected_tools=["search_hotels"])
    result = _result(
        tool_result_texts=['[{"name": "Algarve Beach Resort"}]'],
        final_response="Here are some generic travel tips.",
    )
    assert evaluate_groundedness_proxy(case, result).outcome == "fail"


def test_groundedness_proxy_handles_malformed_json_gracefully():
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_result_texts=["Error: unknown tool 'search_hotels'"])
    # Not valid JSON — no names extractable, so nothing to check against.
    assert evaluate_groundedness_proxy(case, result).outcome == "skip"


# --- evaluate_clarification ---


def test_clarification_skips_when_not_expected():
    case = _case(expects_clarification=False)
    result = _result(final_response="Here's a hotel.")
    assert evaluate_clarification(case, result).outcome == "skip"


def test_clarification_passes_on_a_real_question_with_no_tool_call():
    case = _case(expects_clarification=True)
    result = _result(tool_calls=[], final_response="What's your budget and travel month?")
    assert evaluate_clarification(case, result).outcome == "pass"


def test_clarification_fails_when_a_tool_was_called_instead():
    case = _case(expects_clarification=True)
    result = _result(tool_calls=["search_hotels"], final_response="Here's a hotel?")
    assert evaluate_clarification(case, result).outcome == "fail"


def test_clarification_fails_when_response_has_no_question_mark():
    case = _case(expects_clarification=True)
    result = _result(tool_calls=[], final_response="Tell me more about your trip.")
    assert evaluate_clarification(case, result).outcome == "fail"
