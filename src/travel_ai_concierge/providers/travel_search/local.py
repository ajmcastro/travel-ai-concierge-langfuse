from travel_ai_concierge.domain import Destination, Hotel, PriceBand, price_band_at_most
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.travel_search.data import get_destinations, get_hotels

BACKEND_NAME = "local_synthetic"


class LocalSyntheticTravelSearchProvider:
    """The always-available default — filters this project's own local JSON
    dataset (Milestone 4) in-process. No network, no credentials, no
    external service; this is what keeps the Travel AI Concierge capable of
    running fully independently, per the spec's own requirement.

    Opens the same `travel_search_backend` span `TravelAISearchAPIProvider`
    does, with the same shape (Milestone 15's Mock/Anthropic parity
    reasoning applied here too) — so a trace looks structurally identical
    regardless of `Settings.travel_search_provider`, and `metadata.backend`
    is the one thing that tells them apart.
    """

    def search_destinations(
        self, tags: list[str] | None = None, climate: str | None = None, limit: int = 5
    ) -> list[Destination]:
        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="travel_search_backend",
            input={"op": "search_destinations", "tags": tags, "climate": climate, "limit": limit},
            metadata={"backend": BACKEND_NAME},
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
        self,
        destination_id: str,
        family_friendly: bool | None = None,
        max_price_band: PriceBand | None = None,
        limit: int = 5,
    ) -> list[Hotel]:
        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="travel_search_backend",
            input={
                "op": "search_hotels",
                "destination_id": destination_id,
                "family_friendly": family_friendly,
                "max_price_band": max_price_band,
                "limit": limit,
            },
            metadata={"backend": BACKEND_NAME},
        ) as span:
            results = [h for h in get_hotels() if h.destination_id == destination_id]
            if family_friendly is not None:
                results = [h for h in results if h.family_friendly == family_friendly]
            if max_price_band is not None:
                results = [h for h in results if price_band_at_most(h.price_band, max_price_band)]
            results = results[:limit]
            span.update(output={"result_count": len(results)})
            return results

    def get_destination_information(self, destination_id: str) -> Destination | None:
        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="travel_search_backend",
            input={"op": "get_destination_information", "destination_id": destination_id},
            metadata={"backend": BACKEND_NAME},
        ) as span:
            result = next((d for d in get_destinations() if d.id == destination_id), None)
            span.update(output={"found": result is not None})
            return result
