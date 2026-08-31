from functools import lru_cache

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.providers.travel_search.api import TravelAISearchAPIProvider
from travel_ai_concierge.providers.travel_search.base import TravelSearchProvider
from travel_ai_concierge.providers.travel_search.local import LocalSyntheticTravelSearchProvider

__all__ = [
    "TravelSearchProvider",
    "LocalSyntheticTravelSearchProvider",
    "TravelAISearchAPIProvider",
    "get_travel_search_provider",
]


@lru_cache(maxsize=1)
def get_travel_search_provider() -> TravelSearchProvider:
    """Selects the concrete provider from `Settings.travel_search_provider`
    — same factory shape as `get_llm_provider()`. lru_cache'd like every
    other provider factory in this project; tests that vary
    `TRAVEL_SEARCH_PROVIDER`/`TRAVEL_AI_SEARCH_*` mid-process must clear
    this cache alongside `get_settings.cache_clear()`, the same discipline
    `get_llm_provider`/`get_langfuse_client`/`get_agent_graph` already need.
    """
    settings = get_settings()

    if settings.travel_search_provider == "local":
        return LocalSyntheticTravelSearchProvider()

    if settings.travel_search_provider == "travel_ai_search_api":
        return TravelAISearchAPIProvider(
            base_url=settings.travel_ai_search_base_url,
            timeout=settings.travel_ai_search_timeout_seconds,
            api_key=settings.travel_ai_search_api_key,
        )

    raise ValueError(f"Unknown travel search provider: {settings.travel_search_provider!r}")
