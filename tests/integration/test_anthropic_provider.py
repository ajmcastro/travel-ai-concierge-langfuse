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

pytestmark = pytest.mark.integration


async def test_anthropic_provider_returns_a_real_completion():
    settings = get_settings()
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not configured")
    if settings.llm_model == "mock":
        pytest.skip("LLM_MODEL is still the mock placeholder — set a real Anthropic model id")

    provider = AnthropicProvider(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        max_tokens=64,
        timeout=30.0,
    )
    messages = [
        Message(role="system", content="Reply with exactly one word."),
        Message(role="user", content="Say hello."),
    ]

    result = await provider.complete(messages)

    assert result.content
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
