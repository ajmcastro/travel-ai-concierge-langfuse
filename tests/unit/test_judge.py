"""Tests for evaluation/judge.py — Milestone 11.

FakeJudgeProvider tests are fully offline (it's a pure function of M9's own
evaluator outcomes). `_parse_judgments()` tests are also offline — pure
string-parsing logic, no network. The real AnthropicJudgeProvider is only
exercised in tests/integration/test_llm_judge.py (skip-by-default, no
offline fallback exists for a real LLM call).
"""

import pytest

from travel_ai_concierge.evaluation.judge import (
    FakeJudgeProvider,
    JudgeParseError,
    _applicable_dimensions,
    _parse_judgments,
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


# --- _applicable_dimensions ---


def test_itinerary_coherence_only_applies_to_itinerary_planning_cases():
    assert "itinerary_coherence" not in _applicable_dimensions(_case(query_class="budget"))
    assert "itinerary_coherence" in _applicable_dimensions(_case(query_class="itinerary_planning"))


def test_core_four_dimensions_always_apply():
    dims = set(_applicable_dimensions(_case(query_class="anything")))
    assert dims == {"relevance", "helpfulness", "groundedness", "constraint_satisfaction"}


# --- FakeJudgeProvider ---


async def test_fake_judge_returns_one_judgment_per_applicable_dimension():
    judge = FakeJudgeProvider()
    case = _case(query_class="budget", expected_tools=["search_hotels"])
    result = _result(tool_calls=["search_hotels"], final_response="here you go")

    judgments = await judge.judge(case, result)

    assert {j.dimension for j in judgments} == {
        "relevance",
        "helpfulness",
        "groundedness",
        "constraint_satisfaction",
    }
    assert all(1 <= j.score <= 5 for j in judgments)
    assert all("Deterministic fake judge" in j.rationale for j in judgments)


async def test_fake_judge_includes_itinerary_coherence_for_that_query_class():
    judge = FakeJudgeProvider()
    case = _case(query_class="itinerary_planning")
    result = _result()

    judgments = await judge.judge(case, result)

    dims = {j.dimension: j for j in judgments}
    assert "itinerary_coherence" in dims
    assert dims["itinerary_coherence"].score == 3


async def test_fake_judge_scores_low_when_tool_usage_and_response_both_fail():
    judge = FakeJudgeProvider()
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_calls=[], final_response="   ")  # no tool called, blank response

    judgments = await judge.judge(case, result)

    scores = {j.dimension: j.score for j in judgments}
    assert scores["relevance"] <= 2
    assert scores["helpfulness"] == 1


async def test_fake_judge_is_deterministic_across_repeated_calls():
    judge = FakeJudgeProvider()
    case = _case(expected_tools=["search_hotels"])
    result = _result(tool_calls=["search_hotels"], final_response="ok")

    first = await judge.judge(case, result)
    second = await judge.judge(case, result)

    assert [j.model_dump() for j in first] == [j.model_dump() for j in second]


# --- _parse_judgments ---


def test_parse_judgments_accepts_well_formed_json():
    text = '{"judgments": [{"dimension": "relevance", "score": 4, "rationale": "good"}]}'
    judgments = _parse_judgments(text, ["relevance"])
    assert len(judgments) == 1
    assert judgments[0].dimension == "relevance"
    assert judgments[0].score == 4


def test_parse_judgments_rejects_non_json():
    with pytest.raises(JudgeParseError):
        _parse_judgments("not json at all", ["relevance"])


def test_parse_judgments_rejects_missing_judgments_key():
    with pytest.raises(JudgeParseError):
        _parse_judgments('{"scores": []}', ["relevance"])


def test_parse_judgments_rejects_out_of_range_score():
    text = '{"judgments": [{"dimension": "relevance", "score": 9, "rationale": "x"}]}'
    with pytest.raises(JudgeParseError):
        _parse_judgments(text, ["relevance"])


def test_parse_judgments_rejects_missing_expected_dimension():
    text = '{"judgments": [{"dimension": "relevance", "score": 4, "rationale": "x"}]}'
    with pytest.raises(JudgeParseError):
        _parse_judgments(text, ["relevance", "helpfulness"])


def test_parse_judgments_ignores_hallucinated_extra_dimension():
    text = (
        '{"judgments": ['
        '{"dimension": "relevance", "score": 4, "rationale": "x"}, '
        '{"dimension": "made_up_dimension", "score": 5, "rationale": "y"}'
        "]}"
    )
    judgments = _parse_judgments(text, ["relevance"])
    assert [j.dimension for j in judgments] == ["relevance"]
