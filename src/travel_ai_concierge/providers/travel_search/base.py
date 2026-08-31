from typing import Protocol

from travel_ai_concierge.domain import Destination, Hotel, PriceBand


class TravelSearchProvider(Protocol):
    """Where destination/hotel data actually comes from — Milestone 18.

    Mirrors `LLMProvider` (ADR-003) deliberately: same Protocol-based thin
    abstraction, same reason (swap the concrete implementation via one
    `Settings` value, with zero changes to `tools/travel_tools.py` or
    anything above it). Method signatures are identical to the tool
    functions themselves — a real search backend, unlike this project's own
    static local JSON, is exactly the kind of thing that filters
    server-side, so the Protocol takes the same query parameters a real
    search API would.

    Synchronous, not `async def` like `LLMProvider` — a deliberate
    divergence, not an oversight. `agent/nodes.py`'s `tools_node` calls
    `TOOL_REGISTRY` entries synchronously (`func(**call.arguments)`, never
    awaited), a convention every tool and every milestone since M4 depends
    on; making this Protocol async would mean making `tools_node` and the
    whole tool-execution path async too, a much larger and riskier change
    than this milestone needs. `TravelAISearchAPIProvider` uses `httpx2`'s
    synchronous `Client`, not `AsyncClient`, for the same reason.
    """

    def search_destinations(
        self, tags: list[str] | None = None, climate: str | None = None, limit: int = 5
    ) -> list[Destination]: ...

    def search_hotels(
        self,
        destination_id: str,
        family_friendly: bool | None = None,
        max_price_band: PriceBand | None = None,
        limit: int = 5,
    ) -> list[Hotel]: ...

    def get_destination_information(self, destination_id: str) -> Destination | None: ...
