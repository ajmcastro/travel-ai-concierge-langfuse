"""Tests for the LangGraph agent/tools loop (Milestone 5).

Offline via MockProvider's deterministic tool-trigger heuristic (see
providers/llm/mock.py) — no network, no credentials, no live Langfuse
required (span creation is local-only, same reasoning as every previous
milestone's tests).
"""

import pytest

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.agent.graph import build_graph
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.providers.llm import Message, get_llm_provider


@pytest.fixture(autouse=True)
def _clear_caches(monkeypatch: pytest.MonkeyPatch):
    # Pinned explicitly rather than relying on .env's own default — this
    # file's whole "offline, no credentials" promise (see module docstring)
    # only holds if LLM_PROVIDER actually resolves to mock, which stops
    # being true the moment a real LLM_PROVIDER=anthropic is configured for
    # live use elsewhere in this project (found live: these tests silently
    # started making real API calls once that happened).
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_agent_graph.cache_clear()
    yield
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_agent_graph.cache_clear()


def _initial_state(message: str) -> dict:
    return {
        "messages": [
            Message(role="system", content="You are a travel concierge."),
            Message(role="user", content=message),
        ],
        "iterations": 0,
    }


async def test_no_tool_needed_terminates_in_one_iteration():
    graph = get_agent_graph()
    result = await graph.ainvoke(_initial_state("hello there"))

    assert result["iterations"] == 1
    final = result["messages"][-1]
    assert final.role == "assistant"
    assert final.tool_calls == []
    assert "hello there" in final.content


async def test_tool_call_loops_back_and_terminates():
    graph = get_agent_graph()
    result = await graph.ainvoke(_initial_state("find me a hotel"))

    assert result["iterations"] == 2
    roles = [m.role for m in result["messages"]]
    # system, user, assistant(tool_call), tool(result), assistant(final)
    assert roles == ["system", "user", "assistant", "tool", "assistant"]

    tool_request = result["messages"][2]
    assert tool_request.tool_calls[0].name == "search_hotels"

    tool_result = result["messages"][3]
    assert tool_result.role == "tool"
    assert tool_result.tool_call_id == tool_request.tool_calls[0].id

    final = result["messages"][-1]
    assert final.tool_calls == []
    assert "tool result" in final.content.lower()


async def test_max_iterations_stops_an_agent_that_always_calls_tools(
    monkeypatch: pytest.MonkeyPatch,
):
    # A pathological provider that always requests the same tool, to prove
    # the safety limit actually stops the loop rather than running forever.
    from travel_ai_concierge.providers.llm.base import LLMResponse, ToolCall, Usage

    class AlwaysCallsToolProvider:
        model = "always-tool"

        async def complete(self, messages, tools=None):
            return LLMResponse(
                content="",
                model=self.model,
                usage=Usage(input_tokens=1, output_tokens=1),
                tool_calls=[
                    ToolCall(id="x", name="search_destinations", arguments={"tags": ["beach"]})
                ],
            )

    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider",
        lambda: AlwaysCallsToolProvider(),
    )
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "3")
    get_settings.cache_clear()

    graph = build_graph()
    result = await graph.ainvoke(_initial_state("anything"))

    assert result["iterations"] == 3
    # Stopped by the routing-level hard cap while still mid-tool-call, not
    # because the (pathological) provider ever produced a text-only
    # response — it ignores `tools=None` entirely, on purpose, to prove this
    # safeguard doesn't depend on well-behaved provider cooperation.
    assert result["messages"][-1].tool_calls != []


async def test_forced_final_call_withholds_tools_for_a_clean_answer(
    monkeypatch: pytest.MonkeyPatch,
):
    # Unlike the pathological provider above, this one genuinely respects
    # `tools=None` — proving agent_node's tools-withholding produces a real,
    # non-empty text answer at the cap, not just relying on routing's hard
    # stop (which alone would leave the user with an empty-content message).
    from travel_ai_concierge.providers.llm.base import LLMResponse, ToolCall, Usage

    class PersistentButWellBehavedProvider:
        model = "persistent-tool"

        async def complete(self, messages, tools=None):
            if tools is None:
                return LLMResponse(
                    content="Here is what I found so far.",
                    model=self.model,
                    usage=Usage(input_tokens=1, output_tokens=1),
                    tool_calls=[],
                )
            return LLMResponse(
                content="",
                model=self.model,
                usage=Usage(input_tokens=1, output_tokens=1),
                tool_calls=[
                    ToolCall(id="x", name="search_destinations", arguments={"tags": ["beach"]})
                ],
            )

    monkeypatch.setattr(
        "travel_ai_concierge.agent.nodes.get_llm_provider",
        lambda: PersistentButWellBehavedProvider(),
    )
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "2")
    get_settings.cache_clear()

    graph = build_graph()
    result = await graph.ainvoke(_initial_state("anything"))

    final = result["messages"][-1]
    assert final.tool_calls == []
    assert final.content == "Here is what I found so far."
