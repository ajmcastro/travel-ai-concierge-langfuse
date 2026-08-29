from functools import lru_cache

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.providers.llm.anthropic_provider import AnthropicProvider
from travel_ai_concierge.providers.llm.base import LLMProvider, LLMResponse, Message, Usage
from travel_ai_concierge.providers.llm.mock import MockProvider

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "Message",
    "Usage",
    "MockProvider",
    "AnthropicProvider",
    "get_llm_provider",
]


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    settings = get_settings()

    if settings.llm_provider == "mock":
        return MockProvider()

    if settings.llm_provider == "anthropic":
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
        )

    raise ValueError(f"Unknown LLM provider: {settings.llm_provider!r}")
