"""Tests for Milestone 6 trace-design attributes: tags, metadata, version,
and error-level recording.

Fully offline: a Langfuse client backed by an in-memory OTel span exporter
(`InMemorySpanExporter`) never makes a network call, so we can assert on the
*actual* exported span attributes (via Langfuse's own OTel attribute keys —
verified by introspecting `langfuse._client.attributes`) rather than trusting
that our `propagate_attributes(...)`/`.update(...)` calls did what we think.
"""

import pytest
from fastapi.testclient import TestClient
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.agent.graph import build_graph
from travel_ai_concierge.api.app import create_app
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import Message, get_llm_provider
from travel_ai_concierge.providers.llm.base import LLMResponse, ToolCall, Usage


def _memory_client(public_key: str) -> tuple[Langfuse, InMemorySpanExporter]:
    # Langfuse's client registry is keyed by public_key (LangfuseResourceManager
    # is a singleton per key) — a fresh, unique key per test client guarantees
    # a fresh in-memory exporter rather than reusing another test's instance.
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=public_key,
        secret_key="sk-test",
        span_exporter=exporter,
        tracing_enabled=True,
        environment="test",
        release="test-release",
    )
    return client, exporter


def _clear_all_caches() -> None:
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_langfuse_client.cache_clear()
    get_agent_graph.cache_clear()


@pytest.fixture(autouse=True)
def _clear_caches():
    _clear_all_caches()
    yield
    _clear_all_caches()


def _initial_state(message: str) -> dict:
    return {
        "messages": [
            Message(role="system", content="You are a travel concierge."),
            Message(role="user", content=message),
        ],
        "iterations": 0,
    }


def _attrs_by_name(exporter: InMemorySpanExporter) -> dict:
    return {s.name: dict(s.attributes) for s in exporter.get_finished_spans()}


class UnknownToolProvider:
    """Requests a tool name that was never registered."""

    model = "unknown-tool"

    async def complete(self, messages, tools=None):
        if messages and messages[-1].role == "tool":
            return LLMResponse(
                content="done", model=self.model, usage=Usage(input_tokens=1, output_tokens=1)
            )
        return LLMResponse(
            content="",
            model=self.model,
            usage=Usage(input_tokens=1, output_tokens=1),
            tool_calls=[ToolCall(id="x", name="not_a_real_tool", arguments={})],
        )


class MissingArgsToolProvider:
    """Requests a real tool but omits its required argument.

    This fails during `func(**call.arguments)`'s own argument binding —
    before `search_hotels` ever opens its own `tool` observation — which is
    exactly the silent-failure gap Milestone 6 closes at the `execute_tools`
    level.
    """

    model = "missing-args"

    async def complete(self, messages, tools=None):
        if messages and messages[-1].role == "tool":
            return LLMResponse(
                content="done", model=self.model, usage=Usage(input_tokens=1, output_tokens=1)
            )
        return LLMResponse(
            content="",
            model=self.model,
            usage=Usage(input_tokens=1, output_tokens=1),
            tool_calls=[ToolCall(id="x", name="search_hotels", arguments={})],
        )


async def test_unknown_tool_call_marks_execute_tools_span_as_error(
    monkeypatch: pytest.MonkeyPatch,
):
    client, exporter = _memory_client("pk-test-unknown-tool")
    monkeypatch.setattr("travel_ai_concierge.agent.nodes.get_langfuse_client", lambda: client)
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: UnknownToolProvider()
    )

    result = await build_graph().ainvoke(_initial_state("anything"))
    assert result["messages"][-1].content == "done"

    client.flush()
    spans = _attrs_by_name(exporter)
    execute_tools = spans["execute_tools"]
    assert execute_tools["langfuse.observation.level"] == "ERROR"
    assert "not_a_real_tool" in execute_tools["langfuse.observation.status_message"]


async def test_missing_required_argument_marks_execute_tools_span_as_error(
    monkeypatch: pytest.MonkeyPatch,
):
    client, exporter = _memory_client("pk-test-missing-args")
    monkeypatch.setattr("travel_ai_concierge.agent.nodes.get_langfuse_client", lambda: client)
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider", lambda: MissingArgsToolProvider()
    )

    result = await build_graph().ainvoke(_initial_state("anything"))
    assert result["messages"][-1].content == "done"

    client.flush()
    execute_tools = _attrs_by_name(exporter)["execute_tools"]
    assert execute_tools["langfuse.observation.level"] == "ERROR"
    assert "search_hotels" in execute_tools["langfuse.observation.status_message"]


async def test_successful_tool_call_does_not_set_error_level(monkeypatch: pytest.MonkeyPatch):
    client, exporter = _memory_client("pk-test-successful-tool")
    monkeypatch.setattr("travel_ai_concierge.agent.nodes.get_langfuse_client", lambda: client)

    graph = get_agent_graph()
    await graph.ainvoke(_initial_state("find me a hotel"))

    client.flush()
    execute_tools = _attrs_by_name(exporter)["execute_tools"]
    assert "langfuse.observation.level" not in execute_tools


def _chat_test_client(monkeypatch: pytest.MonkeyPatch, client: Langfuse) -> TestClient:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr("travel_ai_concierge.api.routes.chat.get_langfuse_client", lambda: client)
    return TestClient(create_app())


def test_chat_trace_carries_tags_metadata_and_agent_version(monkeypatch: pytest.MonkeyPatch):
    client, exporter = _memory_client("pk-test-chat-attrs")
    http_client = _chat_test_client(monkeypatch, client)

    response = http_client.post("/chat", json={"message": "hello there"})
    assert response.status_code == 200

    client.flush()
    root = _attrs_by_name(exporter)["travel_concierge_turn"]
    assert set(root["langfuse.trace.tags"]) == {"agent", "provider:mock"}
    assert root["langfuse.trace.metadata.agent_enabled"] == "True"
    assert root["langfuse.trace.metadata.llm_provider"] == "mock"
    assert root["langfuse.version"] == get_settings().agent_version


def test_chat_direct_llm_path_is_tagged_differently_and_has_no_agent_version(
    monkeypatch: pytest.MonkeyPatch,
):
    client, exporter = _memory_client("pk-test-chat-direct")
    monkeypatch.setenv("AGENT_ENABLED", "false")
    http_client = _chat_test_client(monkeypatch, client)

    response = http_client.post("/chat", json={"message": "hello there"})
    assert response.status_code == 200

    client.flush()
    root = _attrs_by_name(exporter)["travel_concierge_turn"]
    assert set(root["langfuse.trace.tags"]) == {"direct-llm", "provider:mock"}
    assert "langfuse.version" not in root


class RaisingProvider:
    model = "raising"

    async def complete(self, messages, tools=None):
        raise RuntimeError("upstream provider exploded")


def test_chat_exception_records_error_level_and_status_message(monkeypatch: pytest.MonkeyPatch):
    client, exporter = _memory_client("pk-test-chat-error")
    monkeypatch.setenv("AGENT_ENABLED", "false")
    http_client = _chat_test_client(monkeypatch, client)
    monkeypatch.setattr(
        "travel_ai_concierge.api.routes.chat.get_llm_provider", lambda: RaisingProvider()
    )

    with pytest.raises(RuntimeError, match="upstream provider exploded"):
        http_client.post("/chat", json={"message": "hello there"})

    client.flush()
    root = _attrs_by_name(exporter)["travel_concierge_turn"]
    assert root["langfuse.observation.level"] == "ERROR"
    assert "upstream provider exploded" in root["langfuse.observation.status_message"]
