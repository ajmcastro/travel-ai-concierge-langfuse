"""Integration test: prompt v1 (production) and v2 (staging), for real.

Excluded from `make test` by default (see the `not integration` marker
filter in pyproject.toml). Requires two things a fresh clone won't have:

    make seed-prompts                                  # creates v1 + v2
    ANTHROPIC_API_KEY=sk-ant-... LLM_MODEL=claude-sonnet-4-5 make test-integration

This deliberately does NOT assert one prompt is "better" than the other —
the project spec explicitly warns against declaring a prompt superior from a
handful of manually inspected examples; that's Milestone 9+'s job, with a
real evaluation dataset. This only proves the mechanism: two distinct,
independently fetchable, independently versioned prompts, each producing a
valid completion from the real API.
"""

import pytest

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.prompts import SYSTEM_PROMPT_NAME
from travel_ai_concierge.providers.llm.anthropic_provider import AnthropicProvider
from travel_ai_concierge.providers.llm.base import Message

pytestmark = pytest.mark.integration


def _prompt_or_skip(label: str):
    prompt = get_langfuse_client().get_prompt(
        SYSTEM_PROMPT_NAME, label=label, type="text", fallback=""
    )
    if prompt.is_fallback:
        pytest.skip(
            f"Prompt {SYSTEM_PROMPT_NAME!r} label={label!r} not seeded — run `make seed-prompts`"
        )
    return prompt


def _provider_or_skip() -> AnthropicProvider:
    settings = get_settings()
    if not settings.anthropic_api_key:
        pytest.skip("ANTHROPIC_API_KEY not configured")
    if settings.llm_model == "mock":
        pytest.skip("LLM_MODEL is still the mock placeholder — set a real Anthropic model id")

    return AnthropicProvider(
        api_key=settings.anthropic_api_key, model=settings.llm_model, max_tokens=128, timeout=30.0
    )


async def test_v1_and_v2_are_distinct_seeded_versions():
    v1 = _prompt_or_skip("production")
    v2 = _prompt_or_skip("staging")

    assert v1.prompt != v2.prompt
    assert v1.version != v2.version


async def test_both_prompt_versions_produce_a_real_completion():
    v1 = _prompt_or_skip("production")
    v2 = _prompt_or_skip("staging")
    provider = _provider_or_skip()

    message = Message(role="user", content="Tell me about a hotel in the Algarve.")

    for prompt in (v1, v2):
        result = await provider.complete(
            [Message(role="system", content=prompt.compile()), message]
        )
        assert result.content or result.tool_calls
