from typing import Any

import httpx2

from travel_ai_concierge.domain import Destination, Hotel, PriceBand
from travel_ai_concierge.observability import get_langfuse_client

BACKEND_NAME = "travel_ai_search_api"

# Assumed REST contract for the separate Travel AI Search project — this
# repo has no access to that project's real API, so this shape is designed,
# not confirmed. It's the most natural fit for the parameters this
# project's own tools already take, and the project spec explicitly allows
# assuming schema compatibility ("the dataset may be compatible with or
# derived conceptually from the synthetic dataset used by the existing
# Travel AI Search project"). Response bodies are validated against this
# project's own `Destination`/`Hotel` Pydantic models — if the real API's
# shape differs, `model_validate` raises a clear error rather than silently
# accepting malformed data. Unverified against a live deployment, same
# honesty standard as `AnthropicProvider`'s tool-call translation (M5) —
# pinned by an integration test that runs a real, local fake server
# implementing exactly this contract (tests/integration/test_travel_ai_search_provider.py),
# not by assumption alone.


class TravelAISearchAPIProvider:
    """Calls a separately running Travel AI Search backend over HTTP.

    Deliberately module-level `httpx2.get(...)` calls, not a persistent
    `httpx2.Client` — matches the one other real outbound HTTP call site in
    this repo (`ui/streamlit_app.py`'s `httpx2.post(...)`), and keeps this
    trivially testable the same way (`monkeypatch.setattr("httpx2.get", ...)`).
    """

    def __init__(self, base_url: str, timeout: float, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def _get(self, path: str, params: dict[str, Any]) -> httpx2.Response:
        return httpx2.get(
            f"{self._base_url}{path}",
            params={k: v for k, v in params.items() if v is not None},
            headers=self._headers,
            timeout=self._timeout,
        )

    def search_destinations(
        self, tags: list[str] | None = None, climate: str | None = None, limit: int = 5
    ) -> list[Destination]:
        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="travel_search_backend",
            input={"op": "search_destinations", "tags": tags, "climate": climate, "limit": limit},
            metadata={"backend": BACKEND_NAME, "base_url": self._base_url},
        ) as span:
            try:
                response = self._get(
                    "/destinations", {"tags": tags, "climate": climate, "limit": limit}
                )
                response.raise_for_status()
            except httpx2.HTTPError as exc:
                span.update(level="ERROR", status_message=str(exc))
                raise
            results = [Destination.model_validate(item) for item in response.json()]
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
            metadata={"backend": BACKEND_NAME, "base_url": self._base_url},
        ) as span:
            try:
                response = self._get(
                    "/hotels",
                    {
                        "destination_id": destination_id,
                        "family_friendly": family_friendly,
                        "max_price_band": max_price_band,
                        "limit": limit,
                    },
                )
                response.raise_for_status()
            except httpx2.HTTPError as exc:
                span.update(level="ERROR", status_message=str(exc))
                raise
            results = [Hotel.model_validate(item) for item in response.json()]
            span.update(output={"result_count": len(results)})
            return results

    def get_destination_information(self, destination_id: str) -> Destination | None:
        client = get_langfuse_client()
        with client.start_as_current_observation(
            name="travel_search_backend",
            input={"op": "get_destination_information", "destination_id": destination_id},
            metadata={"backend": BACKEND_NAME, "base_url": self._base_url},
        ) as span:
            try:
                response = self._get(f"/destinations/{destination_id}", {})
                if response.status_code == 404:
                    span.update(output={"found": False})
                    return None
                response.raise_for_status()
            except httpx2.HTTPError as exc:
                span.update(level="ERROR", status_message=str(exc))
                raise
            result = Destination.model_validate(response.json())
            span.update(output={"found": True})
            return result
