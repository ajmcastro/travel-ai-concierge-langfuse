"""Milestone 15: proves the asymmetry between tool-layer and LLM-layer
faults through the real `/chat` endpoint — not just faults.py's own unit
tests, but what actually happens to a real request.

Tool-layer faults (a scripted provider that requests a tool, then a second
scripted response after the tool "fails") are recovered by the agent's own
second LLM call: HTTP 200, a real answer, `execute_tools` marked ERROR.
LLM-layer faults (the provider itself raises) have no such second chance:
HTTP 500, the root span marked ERROR, but the process itself never hangs or
crashes — a clean failure, not a graceful one, and this file is explicit
about that distinction rather than claiming uniform "graceful degradation."

Same InMemorySpanExporter pattern as test_trace_design.py (Milestone 6) —
verifies actual exported span attributes, not just HTTP status codes.
"""

import pytest
from fastapi.testclient import TestClient
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.api.app import create_app
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.conversation import get_conversation_store
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.prompts import SYSTEM_PROMPT_FALLBACK
from travel_ai_concierge.providers.llm import get_llm_provider
from travel_ai_concierge.providers.llm.base import LLMResponse, ToolCall, Usage
from travel_ai_concierge.providers.llm.mock import MockProvider
from travel_ai_concierge.providers.travel_search import get_travel_search_provider


def _memory_client(public_key: str) -> tuple[Langfuse, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=public_key, secret_key="sk-test", span_exporter=exporter, tracing_enabled=True
    )
    return client, exporter


def _clear_all_caches() -> None:
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_langfuse_client.cache_clear()
    get_agent_graph.cache_clear()
    get_conversation_store.cache_clear()
    get_travel_search_provider.cache_clear()


@pytest.fixture(autouse=True)
def _clear_caches():
    _clear_all_caches()
    yield
    _clear_all_caches()


class _StubPrompt:
    name = "travel-concierge-system"
    version = 1
    is_fallback = False

    def compile(self, **kwargs: object) -> str:
        return SYSTEM_PROMPT_FALLBACK


def _attrs_by_name(exporter: InMemorySpanExporter) -> dict:
    return {s.name: dict(s.attributes) for s in exporter.get_finished_spans()}


def _chat_test_client(monkeypatch: pytest.MonkeyPatch, client: Langfuse) -> TestClient:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr("travel_ai_concierge.api.routes.chat.get_langfuse_client", lambda: client)
    # agent/nodes.py imports get_langfuse_client separately (its own module
    # binding) — patching only chat.py's leaves "agent"/"execute_tools"
    # spans landing on the real, unrelated cached client instead of this
    # test's exporter. test_trace_design.py's pure-agent-graph tests patch
    # this same site directly; /chat-level tests there never assert on
    # these child spans for exactly this reason — this file does, so it
    # needs the patch test_trace_design.py's chat-level tests could skip.
    monkeypatch.setattr("travel_ai_concierge.agent.nodes.get_langfuse_client", lambda: client)
    monkeypatch.setattr(
        "travel_ai_concierge.api.routes.chat.get_system_prompt", lambda: _StubPrompt()
    )
    return TestClient(create_app())


class _FailingToolThenRecoversProvider:
    """Requests search_hotels, which will fail (via a fault-injected
    TOOL_REGISTRY entry) — then, seeing the tool's own error message as the
    next "tool" turn, answers anyway. Mirrors what a real reasoning model
    would plausibly do: acknowledge the failure and respond helpfully.
    """

    model = "scripted"

    async def complete(self, messages, tools=None):
        if messages and messages[-1].role == "tool":
            return LLMResponse(
                content="I couldn't check live availability, but Algarve is a great choice.",
                model=self.model,
                usage=Usage(input_tokens=5, output_tokens=5),
            )
        return LLMResponse(
            content="",
            model=self.model,
            usage=Usage(input_tokens=5, output_tokens=5),
            tool_calls=[
                ToolCall(id="c1", name="search_hotels", arguments={"destination_id": "algarve"})
            ],
        )


class _AlwaysRaisesProvider:
    model = "scripted"

    async def complete(self, messages, tools=None):
        raise TimeoutError("simulated llm timeout")


def test_a_tool_layer_fault_is_recovered_http_200(monkeypatch: pytest.MonkeyPatch):
    from travel_ai_concierge.tools import TOOL_REGISTRY

    client, exporter = _memory_client("pk-test-resilience-tool-fault")
    http_client = _chat_test_client(monkeypatch, client)
    monkeypatch.setattr(
        "travel_ai_concierge.api.routes.chat.get_llm_provider",
        lambda: _FailingToolThenRecoversProvider(),
    )
    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider",
        lambda: _FailingToolThenRecoversProvider(),
    )

    original_tool = TOOL_REGISTRY["search_hotels"]

    def _failing_search_hotels(**kwargs: object) -> None:
        raise ConnectionError("simulated travel provider error")

    TOOL_REGISTRY["search_hotels"] = _failing_search_hotels
    try:
        response = http_client.post("/chat", json={"message": "find me a hotel"})
    finally:
        TOOL_REGISTRY["search_hotels"] = original_tool

    assert response.status_code == 200
    assert "algarve" in response.json()["message"].lower()

    client.flush()
    spans = _attrs_by_name(exporter)
    assert spans["execute_tools"]["langfuse.observation.level"] == "ERROR"
    assert "search_hotels" in spans["execute_tools"]["langfuse.observation.status_message"]
    assert "langfuse.observation.level" not in spans["travel_concierge_turn"]


def test_an_llm_layer_fault_fails_cleanly_http_500_not_a_hang(monkeypatch: pytest.MonkeyPatch):
    client, exporter = _memory_client("pk-test-resilience-llm-fault")
    monkeypatch.setenv("AGENT_ENABLED", "false")
    http_client = _chat_test_client(monkeypatch, client)
    monkeypatch.setattr(
        "travel_ai_concierge.api.routes.chat.get_llm_provider", lambda: _AlwaysRaisesProvider()
    )

    with pytest.raises(TimeoutError):
        http_client.post("/chat", json={"message": "find me a hotel"})

    client.flush()
    root = _attrs_by_name(exporter)["travel_concierge_turn"]
    assert root["langfuse.observation.level"] == "ERROR"
    assert "simulated llm timeout" in root["langfuse.observation.status_message"]


def test_langfuse_unavailable_does_not_prevent_a_successful_chat_response(
    monkeypatch: pytest.MonkeyPatch,
):
    # Points this test's own client at Settings.langfuse_enabled=False, the
    # documented ADR-004 mechanism — tracing_enabled is passed straight
    # through, so span creation becomes a local no-op rather than a network
    # call. A *real* unreachable-host round trip is covered separately by
    # tests/integration/test_langfuse_unavailable.py, which needs real
    # (if failing) network I/O and so isn't appropriate for tests/unit/.
    client = Langfuse(public_key="pk-test-disabled", secret_key="sk-test", tracing_enabled=False)
    http_client = _chat_test_client(monkeypatch, client)
    monkeypatch.setattr(
        "travel_ai_concierge.api.routes.chat.get_llm_provider", lambda: MockProvider()
    )

    response = http_client.post("/chat", json={"message": "hello"})

    assert response.status_code == 200
    assert response.json()["message"]
