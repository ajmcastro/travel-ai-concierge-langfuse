"""Tests for evaluation/experiment.py's adapter layer (Milestone 10).

Fully offline: no Langfuse dataset/experiment calls at all — those have no
local fallback (unlike prompts) and are covered instead by
tests/integration/test_langfuse_dataset_experiment.py. This file only tests
the pure mapping logic: dict <-> EvaluationCase, and wrapping an M9
EvaluatorResult as the SDK's Evaluation shape.
"""

from travel_ai_concierge.evaluation.experiment import _adapt_evaluator, _case_from_parts
from travel_ai_concierge.evaluation.models import CaseResult, EvaluatorResult


def test_case_from_parts_round_trips_the_dataset_item_shape():
    case = _case_from_parts(
        {"message": "find me a hotel"},
        {
            "expected_tools": ["search_hotels"],
            "expected_arguments": {"destination_id": "algarve"},
            "expects_clarification": False,
        },
        {"case_id": "hotel-recommendation-001", "query_class": "hotel_recommendation"},
    )

    assert case.id == "hotel-recommendation-001"
    assert case.query_class == "hotel_recommendation"
    assert case.message == "find me a hotel"
    assert case.expected_tools == ["search_hotels"]
    assert case.expected_arguments == {"destination_id": "algarve"}
    assert case.expects_clarification is False


def test_case_from_parts_defaults_when_expected_output_and_metadata_are_none():
    case = _case_from_parts({"message": "hi"}, None, None)

    assert case.id == "unknown"
    assert case.query_class == "unknown"
    assert case.expected_tools == []
    assert case.expected_arguments == {}
    assert case.expects_clarification is False


def _always_pass(case, result) -> EvaluatorResult:
    return EvaluatorResult(evaluator="always_pass", outcome="pass")


def _always_fail(case, result) -> EvaluatorResult:
    return EvaluatorResult(evaluator="always_fail", outcome="fail", detail="nope")


def _always_skip(case, result) -> EvaluatorResult:
    return EvaluatorResult(evaluator="always_skip", outcome="skip", detail="n/a")


def _case_result_dict() -> dict:
    return CaseResult(
        case_id="c1",
        query_class="test",
        trace_id="trace-1",
        tool_calls=[],
        tool_arguments_by_name={},
        tool_result_texts=[],
        final_response="hi",
        iterations=1,
    ).model_dump()


def test_adapt_evaluator_maps_pass_to_numeric_one():
    adapted = _adapt_evaluator(_always_pass)
    evaluations = adapted(
        input={"message": "hi"}, output=_case_result_dict(), expected_output={}, metadata={}
    )

    assert len(evaluations) == 1
    assert evaluations[0].name == "always_pass"
    assert evaluations[0].value == 1.0


def test_adapt_evaluator_maps_fail_to_numeric_zero_with_comment():
    adapted = _adapt_evaluator(_always_fail)
    evaluations = adapted(
        input={"message": "hi"}, output=_case_result_dict(), expected_output={}, metadata={}
    )

    assert len(evaluations) == 1
    assert evaluations[0].name == "always_fail"
    assert evaluations[0].value == 0.0
    assert evaluations[0].comment == "nope"


def test_adapt_evaluator_maps_skip_to_empty_list():
    adapted = _adapt_evaluator(_always_skip)
    evaluations = adapted(
        input={"message": "hi"}, output=_case_result_dict(), expected_output={}, metadata={}
    )

    assert evaluations == []
