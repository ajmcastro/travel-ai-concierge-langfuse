"""Tests for AnthropicProvider's error-marking on the `llm_call` generation
span itself — Milestone 15.

A real, previously-undetected gap: reading Langfuse's own
start_as_current_observation source (bare try/finally, no except) confirmed
it never sets level="ERROR" for us when an exception propagates out of the
`with` block — only the explicit try/except added this milestone does that.
Uses InMemorySpanExporter (the same pattern test_trace_design.py established
for Milestone 6) to verify the *actual* exported span attributes, not just
that the right exception type propagates.

No real Anthropic API call: `AnthropicProvider._client` is constructed
normally (a bad api_key never matters, since messages.create is monkeypatched
before any network call would happen), matching the project's established
"monkeypatch the boundary, not the whole object" style.
"""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from travel_ai_concierge.providers.llm.anthropic_provider import AnthropicProvider
from travel_ai_concierge.providers.llm.base import Message


def _memory_client(public_key: str) -> tuple[Langfuse, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=public_key, secret_key="sk-test", span_exporter=exporter, tracing_enabled=True
    )
    return client, exporter


def _attrs_by_name(exporter: InMemorySpanExporter) -> dict:
    return {s.name: dict(s.attributes) for s in exporter.get_finished_spans()}


async def test_a_timeout_marks_the_generation_span_error_before_reraising(
    monkeypatch: pytest.MonkeyPatch,
):
    client, exporter = _memory_client("pk-test-anthropic-timeout")
    monkeypatch.setattr(
        "travel_ai_concierge.providers.llm.anthropic_provider.get_langfuse_client", lambda: client
    )
    provider = AnthropicProvider(api_key="sk-test", model="claude-test", max_tokens=64, timeout=1.0)

    timeout_error = anthropic.APITimeoutError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )

    async def _raise(**kwargs):
        raise timeout_error

    monkeypatch.setattr(provider._client.messages, "create", _raise)

    with pytest.raises(anthropic.APITimeoutError):
        await provider.complete([Message(role="user", content="hi")])

    client.flush()
    generation = _attrs_by_name(exporter)["llm_call"]
    assert generation["langfuse.observation.level"] == "ERROR"
    assert "timed out" in generation["langfuse.observation.status_message"].lower()


async def test_a_successful_call_never_sets_error_level(monkeypatch: pytest.MonkeyPatch):
    client, exporter = _memory_client("pk-test-anthropic-success")
    monkeypatch.setattr(
        "travel_ai_concierge.providers.llm.anthropic_provider.get_langfuse_client", lambda: client
    )
    provider = AnthropicProvider(api_key="sk-test", model="claude-test", max_tokens=64, timeout=1.0)

    fake_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hello there")],
        usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        model="claude-test",
    )

    async def _succeed(**kwargs):
        return fake_response

    monkeypatch.setattr(provider._client.messages, "create", _succeed)

    result = await provider.complete([Message(role="user", content="hi")])
    assert result.content == "hello there"

    client.flush()
    generation = _attrs_by_name(exporter)["llm_call"]
    assert "langfuse.observation.level" not in generation
