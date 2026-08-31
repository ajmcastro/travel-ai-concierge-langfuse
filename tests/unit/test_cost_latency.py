"""Tests for evaluation/cost_latency.py — Milestone 14.

Uses scripted fake providers, not MockProvider, same discipline as
test_evaluation_runner.py: this tests that UsageTrackingProvider/
run_case_with_metrics correctly capture whatever a provider actually
returns, independent of any specific provider's own behavior.
"""

import pytest

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation.cost_latency import (
    MODEL_PRICING,
    UsageTrackingProvider,
    estimate_cost_usd,
    run_case_with_metrics,
)
from travel_ai_concierge.evaluation.models import EvaluationCase
from travel_ai_concierge.evaluation.runner import run_case as real_run_case
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import get_llm_provider
from travel_ai_concierge.providers.llm.base import LLMResponse, Message, ToolCall, Usage


class _StubPrompt:
    name = "travel-concierge-system"
    version = 1
    is_fallback = False

    def compile(self, **kwargs: object) -> str:
        return "You are a travel concierge."


@pytest.fixture(autouse=True)
def _clear_caches(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "travel_ai_concierge.evaluation.runner.get_system_prompt", lambda: _StubPrompt()
    )
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_langfuse_client.cache_clear()
    get_agent_graph.cache_clear()
    yield
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_langfuse_client.cache_clear()
    get_agent_graph.cache_clear()


# --- estimate_cost_usd ---


def test_estimate_cost_usd_matches_a_known_tier():
    input_rate, output_rate = MODEL_PRICING["sonnet"]
    cost = estimate_cost_usd("claude-sonnet-4-5", input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == pytest.approx(input_rate + output_rate)


def test_estimate_cost_usd_is_case_insensitive():
    assert estimate_cost_usd("CLAUDE-HAIKU-4-5", 1000, 1000) is not None


def test_estimate_cost_usd_returns_none_for_an_unpriced_model():
    assert estimate_cost_usd("mock-echo-v1", 1000, 1000) is None


def test_estimate_cost_usd_scales_with_token_count():
    small = estimate_cost_usd("claude-sonnet-4-5", 1000, 1000)
    large = estimate_cost_usd("claude-sonnet-4-5", 2000, 2000)
    assert large == pytest.approx(small * 2)


# --- UsageTrackingProvider ---


class _ScriptedProvider:
    model = "scripted-model"

    async def complete(self, messages, tools=None):
        return LLMResponse(
            content="an answer", model=self.model, usage=Usage(input_tokens=10, output_tokens=5)
        )


async def test_usage_tracking_provider_records_each_call():
    tracker = UsageTrackingProvider(_ScriptedProvider())

    await tracker.complete([Message(role="user", content="hi")])
    await tracker.complete([Message(role="user", content="again")])

    assert len(tracker.calls) == 2
    assert all(c.input_tokens == 10 and c.output_tokens == 5 for c in tracker.calls)
    assert all(c.latency_ms >= 0 for c in tracker.calls)


async def test_usage_tracking_provider_delegates_the_response_unchanged():
    tracker = UsageTrackingProvider(_ScriptedProvider())
    response = await tracker.complete([Message(role="user", content="hi")])
    assert response.content == "an answer"


def test_usage_tracking_provider_exposes_the_wrapped_models_name():
    tracker = UsageTrackingProvider(_ScriptedProvider())
    assert tracker.model == "scripted-model"


# --- run_case_with_metrics ---


class OneToolThenAnswerProvider:
    model = "scripted"

    async def complete(self, messages, tools=None):
        if messages and messages[-1].role == "tool":
            return LLMResponse(
                content="Based on that, it looks great.",
                model=self.model,
                usage=Usage(input_tokens=20, output_tokens=8),
            )
        return LLMResponse(
            content="",
            model=self.model,
            usage=Usage(input_tokens=15, output_tokens=3),
            tool_calls=[
                ToolCall(id="call-1", name="search_hotels", arguments={"destination_id": "algarve"})
            ],
        )


class NoToolProvider:
    model = "scripted-no-tool"

    async def complete(self, messages, tools=None):
        return LLMResponse(
            content="Here you go.", model=self.model, usage=Usage(input_tokens=12, output_tokens=4)
        )


async def test_run_case_with_metrics_sums_usage_across_llm_calls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: OneToolThenAnswerProvider()
    )
    case = EvaluationCase(
        id="c1", query_class="test", message="find me a hotel", expected_tools=["search_hotels"]
    )

    result, cost_latency = await run_case_with_metrics(case)

    assert result.tool_calls == ["search_hotels"]  # run_case()'s own extraction, unaffected
    assert cost_latency.case_id == "c1"
    assert cost_latency.llm_call_count == 2  # tool request + final answer
    assert cost_latency.total_input_tokens == 15 + 20
    assert cost_latency.total_output_tokens == 3 + 8
    assert cost_latency.total_latency_ms >= 0
    assert cost_latency.estimated_cost_usd is None  # "scripted" isn't in MODEL_PRICING


async def test_run_case_with_metrics_single_llm_call_when_no_tool_needed(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: NoToolProvider()
    )
    case = EvaluationCase(id="c2", query_class="test", message="plan me a trip")

    _, cost_latency = await run_case_with_metrics(case)

    assert cost_latency.llm_call_count == 1
    assert cost_latency.total_input_tokens == 12
    assert cost_latency.total_output_tokens == 4


async def test_run_case_with_metrics_restores_the_real_provider_afterward(
    monkeypatch: pytest.MonkeyPatch,
):
    # Regression guard: run_case_with_metrics patches agent.nodes.get_llm_provider
    # for the duration of one case only — a later call to the *real*
    # get_llm_provider() (or another test) must not still see the tracker.
    fake = NoToolProvider()
    monkeypatch.setattr("travel_ai_concierge.agent.nodes.get_llm_provider", lambda: fake)

    case = EvaluationCase(id="c3", query_class="test", message="hi")
    await run_case_with_metrics(case)

    import travel_ai_concierge.agent.nodes as agent_nodes

    assert agent_nodes.get_llm_provider() is fake


async def test_run_case_with_metrics_passes_config_name_as_tag_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    # Milestone 14 follow-up: config_name must reach run_case()'s own
    # extra_tags/extra_metadata unchanged, so the resulting trace is
    # filterable in Langfuse by which configuration produced it (see
    # test_evaluation_runner.py for the corresponding real-trace-attribute
    # check on run_case() itself).
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: NoToolProvider()
    )

    calls: list[dict] = []

    async def _spy(case, **kwargs):
        calls.append(kwargs)
        return await real_run_case(case, **kwargs)

    monkeypatch.setattr("travel_ai_concierge.evaluation.cost_latency.run_case", _spy)

    case = EvaluationCase(id="c6", query_class="test", message="hi")
    await run_case_with_metrics(case, config_name="single-step")

    assert calls == [
        {
            "extra_tags": ["cost-latency-experiment", "single-step"],
            "extra_metadata": {"cost_latency_config": "single-step"},
        }
    ]


async def test_run_case_with_metrics_passes_nothing_extra_without_a_config_name(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: NoToolProvider()
    )

    calls: list[dict] = []

    async def _spy(case, **kwargs):
        calls.append(kwargs)
        return await real_run_case(case, **kwargs)

    monkeypatch.setattr("travel_ai_concierge.evaluation.cost_latency.run_case", _spy)

    case = EvaluationCase(id="c7", query_class="test", message="hi")
    await run_case_with_metrics(case)

    assert calls == [{"extra_tags": None, "extra_metadata": None}]
