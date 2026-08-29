"""Tests for the LLM provider abstraction (ADR-003).

All offline: MockProvider does no network I/O, and opening a Langfuse
generation span (as these tests exercise) is also local-only — see
docs/EXPERIMENTS.md, Milestone 1.
"""

import pytest

from travel_ai_concierge.config.settings import Settings
from travel_ai_concierge.providers.llm.base import Message
from travel_ai_concierge.providers.llm.mock import MockProvider


async def test_mock_provider_echoes_last_user_message():
    provider = MockProvider()
    messages = [
        Message(role="system", content="You are a travel concierge."),
        Message(role="user", content="Plan me a trip to Porto"),
    ]

    response = await provider.complete(messages)

    assert "Plan me a trip to Porto" in response.content
    assert response.model == "mock-echo-v1"


async def test_mock_provider_usage_is_positive():
    provider = MockProvider()
    messages = [Message(role="user", content="hello there")]

    response = await provider.complete(messages)

    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0


async def test_mock_provider_ignores_missing_user_message():
    provider = MockProvider()
    messages = [Message(role="system", content="system only, no user turn")]

    response = await provider.complete(messages)

    assert "I heard:" in response.content


def test_factory_returns_mock_provider(monkeypatch: pytest.MonkeyPatch):
    from travel_ai_concierge.providers import llm as llm_module

    llm_module.get_llm_provider.cache_clear()
    monkeypatch.setattr(
        "travel_ai_concierge.providers.llm.get_settings",
        lambda: Settings(_env_file=None, llm_provider="mock"),  # type: ignore[call-arg]
    )

    provider = llm_module.get_llm_provider()

    assert isinstance(provider, MockProvider)
    llm_module.get_llm_provider.cache_clear()


def test_factory_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch):
    from travel_ai_concierge.providers import llm as llm_module

    llm_module.get_llm_provider.cache_clear()
    monkeypatch.setattr(
        "travel_ai_concierge.providers.llm.get_settings",
        lambda: Settings(_env_file=None, llm_provider="does-not-exist"),  # type: ignore[call-arg]
    )

    with pytest.raises(ValueError, match="Unknown LLM provider"):
        llm_module.get_llm_provider()

    llm_module.get_llm_provider.cache_clear()
