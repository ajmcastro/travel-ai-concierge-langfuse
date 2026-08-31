"""Tests for faults.py — Milestone 15. Uses a scripted fake provider, not
MockProvider directly, same discipline as test_evaluation_runner.py: this
tests FaultInjectingProvider/make_failing_tool's own logic in isolation.
"""

import pytest

from travel_ai_concierge.faults import FaultInjectingProvider, make_failing_tool
from travel_ai_concierge.providers.llm.base import LLMResponse, Message, ToolCall, Usage


class _AlwaysAnswersProvider:
    model = "scripted"

    async def complete(self, messages, tools=None):
        return LLMResponse(
            content="a plain answer", model=self.model, usage=Usage(input_tokens=5, output_tokens=3)
        )


class _AlwaysCallsToolProvider:
    model = "scripted"

    async def complete(self, messages, tools=None):
        return LLMResponse(
            content="",
            model=self.model,
            usage=Usage(input_tokens=5, output_tokens=3),
            tool_calls=[
                ToolCall(id="c1", name="search_hotels", arguments={"destination_id": "algarve"})
            ],
        )


# --- FaultInjectingProvider construction ---


def test_rejects_a_tool_layer_fault():
    with pytest.raises(ValueError, match="tool_exception"):
        FaultInjectingProvider(_AlwaysAnswersProvider(), fault="tool_exception")


def test_exposes_the_wrapped_models_name():
    provider = FaultInjectingProvider(_AlwaysAnswersProvider(), fault="llm_timeout")
    assert provider.model == "scripted"


# --- llm_timeout / llm_provider_unavailable ---


async def test_llm_timeout_raises_timeout_error_without_calling_the_wrapped_provider():
    calls = []

    class _Spy(_AlwaysAnswersProvider):
        async def complete(self, messages, tools=None):
            calls.append(1)
            return await super().complete(messages, tools=tools)

    provider = FaultInjectingProvider(_Spy(), fault="llm_timeout")
    with pytest.raises(TimeoutError, match="simulated llm timeout"):
        await provider.complete([Message(role="user", content="hi")])
    assert calls == []


async def test_llm_provider_unavailable_raises_connection_error():
    provider = FaultInjectingProvider(_AlwaysAnswersProvider(), fault="llm_provider_unavailable")
    with pytest.raises(ConnectionError, match="simulated llm provider unavailable"):
        await provider.complete([Message(role="user", content="hi")])


# --- llm_malformed_output ---


async def test_malformed_output_strips_arguments_from_a_real_tool_call():
    provider = FaultInjectingProvider(_AlwaysCallsToolProvider(), fault="llm_malformed_output")
    response = await provider.complete([Message(role="user", content="find me a hotel")])

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search_hotels"  # unchanged
    assert response.tool_calls[0].arguments == {}  # corrupted


async def test_malformed_output_passes_through_unchanged_when_no_tool_was_requested():
    provider = FaultInjectingProvider(_AlwaysAnswersProvider(), fault="llm_malformed_output")
    response = await provider.complete([Message(role="user", content="hi")])

    assert response.content == "a plain answer"
    assert response.tool_calls == []


# --- make_failing_tool ---


def test_make_failing_tool_exception_raises_connection_error():
    tool = make_failing_tool("tool_exception", tool_name="search_hotels")
    with pytest.raises(ConnectionError, match="search_hotels"):
        tool(destination_id="algarve")


def test_make_failing_tool_timeout_raises_timeout_error():
    tool = make_failing_tool("tool_timeout", tool_name="search_hotels")
    with pytest.raises(TimeoutError, match="search_hotels"):
        tool(destination_id="algarve")


def test_make_failing_tool_accepts_arbitrary_kwargs_matching_the_real_tool_signature():
    tool = make_failing_tool("tool_exception", tool_name="search_hotels")
    with pytest.raises(ConnectionError):
        tool(destination_id="algarve", family_friendly=True, max_price_band="budget", limit=3)
