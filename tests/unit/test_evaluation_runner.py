"""Tests for evaluation/runner.py — Milestone 9.

Uses a scripted fake provider (same pattern as test_agent.py's
AlwaysCallsToolProvider), not MockProvider's real keyword-trigger table —
this tests that run_case() correctly *extracts* tool_calls/arguments/tool
results/final_response from whatever the agent graph actually produced,
independent of what any specific provider would produce. get_system_prompt
is monkeypatched to a stub for the same offline-by-default reason
established in Milestone 8 (get_prompt() makes a real network call).
"""

import pytest

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.evaluation.models import EvaluationCase
from travel_ai_concierge.evaluation.runner import run_case
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import get_llm_provider
from travel_ai_concierge.providers.llm.base import LLMResponse, ToolCall, Usage


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


class OneToolThenAnswerProvider:
    model = "scripted"

    async def complete(self, messages, tools=None):
        if messages and messages[-1].role == "tool":
            return LLMResponse(
                content="Based on that, the Algarve Beach Resort looks great.",
                model=self.model,
                usage=Usage(input_tokens=1, output_tokens=1),
            )
        return LLMResponse(
            content="",
            model=self.model,
            usage=Usage(input_tokens=1, output_tokens=1),
            tool_calls=[
                ToolCall(
                    id="call-1",
                    name="search_hotels",
                    arguments={"destination_id": "algarve", "family_friendly": True},
                )
            ],
        )


class NoToolProvider:
    model = "scripted-no-tool"

    async def complete(self, messages, tools=None):
        return LLMResponse(
            content="What's your budget and travel month?",
            model=self.model,
            usage=Usage(input_tokens=1, output_tokens=1),
        )


async def test_run_case_extracts_tool_call_and_arguments(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: OneToolThenAnswerProvider()
    )
    case = EvaluationCase(
        id="c1", query_class="test", message="find me a hotel", expected_tools=["search_hotels"]
    )

    result = await run_case(case)

    assert result.tool_calls == ["search_hotels"]
    assert result.tool_arguments_by_name["search_hotels"] == {
        "destination_id": "algarve",
        "family_friendly": True,
    }
    assert "Algarve Beach Resort" in result.final_response
    assert result.trace_id is not None
    assert len(result.tool_result_texts) == 1


async def test_run_case_with_no_tool_call(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: NoToolProvider()
    )
    case = EvaluationCase(
        id="c2", query_class="test", message="plan me a trip", expects_clarification=True
    )

    result = await run_case(case)

    assert result.tool_calls == []
    assert result.tool_result_texts == []
    assert "?" in result.final_response


async def test_run_case_isolates_trace_ids_across_cases(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: NoToolProvider()
    )
    case_a = EvaluationCase(id="a", query_class="test", message="one")
    case_b = EvaluationCase(id="b", query_class="test", message="two")

    result_a = await run_case(case_a)
    result_b = await run_case(case_b)

    assert result_a.trace_id != result_b.trace_id
