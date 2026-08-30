"""Integration test against the real Anthropic API.

Excluded from `make test` by default (see the `not integration` marker
filter in pyproject.toml). Unlike the Langfuse integration tests, this one
also skips itself when no API key is configured — a fresh clone of this repo
has Langfuse for free (`make langfuse-up`) but not a paid Anthropic key, so
failing outright here would be the wrong default.

    ANTHROPIC_API_KEY=sk-ant-... LLM_MODEL=claude-sonnet-4-5 make test-integration
"""

import pytest

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.providers.llm.anthropic_provider import AnthropicProvider
from travel_ai_concierge.providers.llm.base import Message
from travel_ai_concierge.tools import TOOL_SPECS

pytestmark = pytest.mark.integration


def _provider_or_skip() -> AnthropicProvider:
    settings = get_settings()
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not configured")
    if settings.llm_model == "mock":
        pytest.skip("LLM_MODEL is still the mock placeholder — set a real Anthropic model id")

    return AnthropicProvider(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        max_tokens=64,
        timeout=30.0,
    )


async def test_anthropic_provider_returns_a_real_completion():
    provider = _provider_or_skip()
    messages = [
        Message(role="system", content="Reply with exactly one word."),
        Message(role="user", content="Say hello."),
    ]

    result = await provider.complete(messages)

    assert result.content
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0


async def test_anthropic_provider_can_request_a_real_tool_call():
    # Milestone 5: verifies the actual Anthropic API against our translated
    # tool schemas — the unit tests in test_anthropic_translation.py only
    # check the shape we send, not that the real API accepts and uses it.
    provider = _provider_or_skip()
    messages = [
        Message(
            role="system",
            content="You must use the search_hotels tool for any hotel request.",
        ),
        Message(role="user", content="Find me a family-friendly hotel in the Algarve."),
    ]

    result = await provider.complete(messages, tools=TOOL_SPECS)

    assert result.tool_calls
    assert result.tool_calls[0].name == "search_hotels"
    assert "destination_id" in result.tool_calls[0].arguments
