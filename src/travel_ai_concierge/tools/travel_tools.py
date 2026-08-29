from travel_ai_concierge.domain import Destination, Hotel, PriceBand, price_band_at_most
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.tools.data import get_destinations, get_hotels


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
    """
    client = get_langfuse_client()
    with client.start_as_current_observation(
        name="search_destinations",
        as_type="tool",
        input={"tags": tags, "climate": climate, "limit": limit},
    ) as span:
        results = get_destinations()

        if climate is not None:
            results = [d for d in results if d.climate == climate]
        if tags:
            wanted = set(tags)
            results = [d for d in results if wanted & set(d.tags)]

        results = results[:limit]
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
        results = [h for h in get_hotels() if h.destination_id == destination_id]

        if family_friendly is not None:
            results = [h for h in results if h.family_friendly == family_friendly]
        if max_price_band is not None:
            results = [h for h in results if price_band_at_most(h.price_band, max_price_band)]

        results = results[:limit]
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
        result = next((d for d in get_destinations() if d.id == destination_id), None)
        span.update(output={"found": result is not None})
        return result
