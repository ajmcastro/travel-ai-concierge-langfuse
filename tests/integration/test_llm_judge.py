"""Integration test: real Anthropic-backed LLM-as-judge (Milestone 11).

Excluded from `make test` (see `not integration` marker filter in
pyproject.toml). Skips itself when no ANTHROPIC_API_KEY is configured, same
reasoning as test_anthropic_provider.py — a fresh clone has Langfuse for
free but not a paid Anthropic key.

    ANTHROPIC_API_KEY=sk-ant-... JUDGE_MODEL=claude-sonnet-4-5 make test-integration

Also empirically demonstrates the module's own documented stochasticity
limitation rather than just asserting a hypothetical: judges the same case
twice and prints (does not assert equal) both score sets.
"""

import pytest

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation.judge import AnthropicJudgeProvider
from travel_ai_concierge.evaluation.models import CaseResult, EvaluationCase

pytestmark = pytest.mark.integration


def _judge_or_skip() -> AnthropicJudgeProvider:
    settings = get_settings()
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not configured")
    model = settings.judge_model if settings.judge_model != "mock" else settings.llm_model
    if model == "mock":
        pytest.skip("Neither JUDGE_MODEL nor LLM_MODEL is set to a real Anthropic model id")
    return AnthropicJudgeProvider(
        api_key=settings.anthropic_api_key, model=model, max_tokens=512, timeout=30.0
    )


def _case_and_result() -> tuple[EvaluationCase, CaseResult]:
    case = EvaluationCase(
        id="integration-case",
        query_class="hotel_recommendation",
        message="Find me a family-friendly hotel in the Algarve.",
        expected_tools=["search_hotels"],
    )
    result = CaseResult(
        case_id=case.id,
        query_class=case.query_class,
        trace_id=None,
        tool_calls=["search_hotels"],
        tool_arguments_by_name={
            "search_hotels": {"destination_id": "algarve", "family_friendly": True}
        },
        tool_result_texts=[
            '[{"name": "Algarve Beach Resort", "family_friendly": true, "price_band": "luxury"}]'
        ],
        final_response="I found the Algarve Beach Resort, a family-friendly luxury option in the Algarve.",
        iterations=1,
    )
    return case, result


async def test_real_judge_returns_valid_scores_for_all_core_dimensions():
    judge = _judge_or_skip()
    case, result = _case_and_result()

    judgments = await judge.judge(case, result)

    dims = {j.dimension for j in judgments}
    assert dims == {"relevance", "helpfulness", "groundedness", "constraint_satisfaction"}
    for judgment in judgments:
        assert 1 <= judgment.score <= 5
        assert judgment.rationale


async def test_real_judge_scores_may_vary_across_repeated_calls():
    judge = _judge_or_skip()
    case, result = _case_and_result()

    first = await judge.judge(case, result)
    second = await judge.judge(case, result)

    first_scores = {j.dimension: j.score for j in first}
    second_scores = {j.dimension: j.score for j in second}
    print(f"Judge run 1: {first_scores}")
    print(f"Judge run 2: {second_scores}")

    # No equality assertion on the scores themselves — that's the point.
    assert set(first_scores) == set(second_scores)
