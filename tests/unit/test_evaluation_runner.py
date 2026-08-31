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
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

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


def _memory_client(public_key: str) -> tuple[Langfuse, InMemorySpanExporter]:
    # Same pattern as test_trace_design.py: a fresh public_key per test
    # guarantees a fresh in-memory exporter, and reading real exported OTel
    # attributes verifies what propagate_attributes() actually did, not
    # just that run_case() didn't raise.
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=public_key, secret_key="sk-test", span_exporter=exporter, tracing_enabled=True
    )
    return client, exporter


async def test_run_case_extra_tags_and_metadata_are_additive_not_replacing(
    monkeypatch: pytest.MonkeyPatch,
):
    # Milestone 14: extra_tags/extra_metadata let a caller (cost_latency.py)
    # attach config-identifying data without losing the base "evaluation" +
    # query_class tagging every other caller (run_evaluation.py,
    # experiment.py) still relies on.
    client, exporter = _memory_client("pk-test-run-case-extra-tags")
    monkeypatch.setattr("travel_ai_concierge.evaluation.runner.get_langfuse_client", lambda: client)
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: NoToolProvider()
    )
    case = EvaluationCase(id="c4", query_class="demo", message="hi")

    await run_case(
        case,
        extra_tags=["cost-latency-experiment", "single-step"],
        extra_metadata={"cost_latency_config": "single-step"},
    )

    client.flush()
    root = next(s for s in exporter.get_finished_spans() if s.name == "travel_concierge_turn")
    tags = root.attributes["langfuse.trace.tags"]
    assert set(tags) == {"evaluation", "demo", "cost-latency-experiment", "single-step"}
    assert root.attributes["langfuse.trace.metadata.cost_latency_config"] == "single-step"
    assert root.attributes["langfuse.trace.metadata.case_id"] == "c4"
    assert root.attributes["langfuse.trace.metadata.query_class"] == "demo"


async def test_run_case_without_extras_behaves_exactly_as_before(monkeypatch: pytest.MonkeyPatch):
    # Regression guard: every existing caller omits extra_tags/extra_metadata
    # entirely — the base tagging must be byte-for-byte what it was before
    # Milestone 14 added the parameters.
    client, exporter = _memory_client("pk-test-run-case-no-extras")
    monkeypatch.setattr("travel_ai_concierge.evaluation.runner.get_langfuse_client", lambda: client)
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: NoToolProvider()
    )
    case = EvaluationCase(id="c5", query_class="demo", message="hi")

    await run_case(case)

    client.flush()
    root = next(s for s in exporter.get_finished_spans() if s.name == "travel_concierge_turn")
    assert set(root.attributes["langfuse.trace.tags"]) == {"evaluation", "demo"}
    assert "langfuse.trace.metadata.cost_latency_config" not in root.attributes
