from travel_ai_concierge.domain import Destination, Hotel, PriceBand
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.travel_search import get_travel_search_provider


def search_destinations(
    tags: list[str] | None = None,
    climate: str | None = None,
    limit: int = 5,
) -> list[Destination]:
    """Search destinations by tag overlap and/or climate.

    Called standalone today (Milestone 4) — not yet wired into the LLM's
    tool-calling loop, which is Milestone 5's job. Still opens a real
    Langfuse `tool` span: with no parent trace active, this becomes its own
    root trace; called later from within an active `travel_concierge_turn`
    trace, the exact same code nests under it automatically via OTel context
    propagation — no change needed here when Milestone 5 arrives.

    Since Milestone 18, the actual filtering happens inside whichever
    `TravelSearchProvider` is configured (`Settings.travel_search_provider`)
    — this function is only the LLM-facing tool boundary and its own
    Langfuse `tool`-type instrumentation, unchanged regardless of which
    provider actually serves the data. See `providers/travel_search/`.
    """
    client = get_langfuse_client()
    with client.start_as_current_observation(
        name="search_destinations",
        as_type="tool",
        input={"tags": tags, "climate": climate, "limit": limit},
    ) as span:
        results = get_travel_search_provider().search_destinations(
            tags=tags, climate=climate, limit=limit
        )
        span.update(output={"result_count": len(results)})
        return results


def search_hotels(
    destination_id: str,
    family_friendly: bool | None = None,
    max_price_band: PriceBand | None = None,
    limit: int = 5,
) -> list[Hotel]:
    """Search hotels in a destination, optionally filtered by price/family fit."""
    client = get_langfuse_client()
    with client.start_as_current_observation(
        name="search_hotels",
        as_type="tool",
        input={
            "destination_id": destination_id,
            "family_friendly": family_friendly,
            "max_price_band": max_price_band,
            "limit": limit,
        },
    ) as span:
        results = get_travel_search_provider().search_hotels(
            destination_id=destination_id,
            family_friendly=family_friendly,
            max_price_band=max_price_band,
            limit=limit,
        )
        span.update(output={"result_count": len(results)})
        return results


def get_destination_information(destination_id: str) -> Destination | None:
    """Look up a single destination's full details by ID."""
    client = get_langfuse_client()
    with client.start_as_current_observation(
        name="get_destination_information",
        as_type="tool",
        input={"destination_id": destination_id},
    ) as span:
        result = get_travel_search_provider().get_destination_information(destination_id)
        span.update(output={"found": result is not None})
        return result
