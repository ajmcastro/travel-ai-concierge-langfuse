"""Tests for providers/travel_search/ — Milestone 18.

`LocalSyntheticTravelSearchProvider`'s filtering behavior is already
exhaustively covered by test_travel_tools.py through the public tool
functions it now delegates to (the refactor is behavior-preserving, pinned
by that file passing unchanged) — this file adds direct coverage of the
provider layer itself, plus `TravelAISearchAPIProvider`, fully offline via
`monkeypatch.setattr("httpx2.get", ...)`, the same pattern
tests/unit/test_ui_chat.py already established for `httpx2.post`.
"""

import httpx2
import pytest

from travel_ai_concierge.config.settings import Settings
from travel_ai_concierge.domain import Destination, Hotel
from travel_ai_concierge.providers.travel_search.api import TravelAISearchAPIProvider
from travel_ai_concierge.providers.travel_search.local import LocalSyntheticTravelSearchProvider

_DESTINATION = {
    "id": "algarve",
    "name": "Algarve",
    "country": "Portugal",
    "region": "Algarve",
    "climate": "mediterranean",
    "tags": ["beach", "family"],
    "best_months": ["May", "Jun"],
    "description": "Cliff-backed beaches.",
}

_HOTEL = {
    "id": "algarve-beach-resort",
    "destination_id": "algarve",
    "name": "Algarve Beach Resort",
    "star_rating": 5,
    "customer_rating": 9.0,
    "price_band": "luxury",
    "family_friendly": True,
    "adults_only": False,
    "amenities": ["pool"],
}


def _fake_response(json_body, status_code: int = 200) -> httpx2.Response:
    return httpx2.Response(status_code, json=json_body, request=httpx2.Request("GET", "http://x"))


# --- LocalSyntheticTravelSearchProvider ---


def test_local_provider_search_destinations_filters_by_tag():
    provider = LocalSyntheticTravelSearchProvider()
    results = provider.search_destinations(tags=["beach"])
    assert all("beach" in d.tags for d in results)


def test_local_provider_search_hotels_scoped_to_destination():
    provider = LocalSyntheticTravelSearchProvider()
    results = provider.search_hotels("porto")
    assert all(h.destination_id == "porto" for h in results)


def test_local_provider_get_destination_information_not_found_returns_none():
    provider = LocalSyntheticTravelSearchProvider()
    assert provider.get_destination_information("atlantis") is None


# --- TravelAISearchAPIProvider ---


def test_api_provider_search_destinations_parses_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("httpx2.get", lambda *a, **k: _fake_response([_DESTINATION]))
    provider = TravelAISearchAPIProvider(base_url="http://travel-search:8100", timeout=5.0)

    results = provider.search_destinations(tags=["beach"])

    assert results == [Destination.model_validate(_DESTINATION)]


def test_api_provider_search_hotels_parses_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("httpx2.get", lambda *a, **k: _fake_response([_HOTEL]))
    provider = TravelAISearchAPIProvider(base_url="http://travel-search:8100", timeout=5.0)

    results = provider.search_hotels("algarve")

    assert results == [Hotel.model_validate(_HOTEL)]


def test_api_provider_get_destination_information_found(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("httpx2.get", lambda *a, **k: _fake_response(_DESTINATION))
    provider = TravelAISearchAPIProvider(base_url="http://travel-search:8100", timeout=5.0)

    result = provider.get_destination_information("algarve")

    assert result == Destination.model_validate(_DESTINATION)


def test_api_provider_get_destination_information_404_returns_none(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("httpx2.get", lambda *a, **k: _fake_response(None, status_code=404))
    provider = TravelAISearchAPIProvider(base_url="http://travel-search:8100", timeout=5.0)

    assert provider.get_destination_information("atlantis") is None


def test_api_provider_server_error_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "httpx2.get", lambda *a, **k: _fake_response({"error": "boom"}, status_code=500)
    )
    provider = TravelAISearchAPIProvider(base_url="http://travel-search:8100", timeout=5.0)

    with pytest.raises(httpx2.HTTPStatusError):
        provider.search_destinations()


def test_api_provider_connection_error_propagates(monkeypatch: pytest.MonkeyPatch):
    def _raise(*args, **kwargs):
        raise httpx2.ConnectError("connection refused")

    monkeypatch.setattr("httpx2.get", _raise)
    provider = TravelAISearchAPIProvider(base_url="http://travel-search:8100", timeout=5.0)

    with pytest.raises(httpx2.ConnectError):
        provider.search_hotels("algarve")


def test_api_provider_sends_bearer_token_when_api_key_configured(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def _capture(url, **kwargs):
        captured.update(kwargs)
        return _fake_response([])

    monkeypatch.setattr("httpx2.get", _capture)
    provider = TravelAISearchAPIProvider(
        base_url="http://travel-search:8100", timeout=5.0, api_key="secret-key"
    )

    provider.search_destinations()

    assert captured["headers"] == {"Authorization": "Bearer secret-key"}


def test_api_provider_no_auth_header_when_api_key_not_configured(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def _capture(url, **kwargs):
        captured.update(kwargs)
        return _fake_response([])

    monkeypatch.setattr("httpx2.get", _capture)
    provider = TravelAISearchAPIProvider(base_url="http://travel-search:8100", timeout=5.0)

    provider.search_destinations()

    assert captured["headers"] == {}


# --- factory ---


def test_factory_returns_local_provider_by_default(monkeypatch: pytest.MonkeyPatch):
    from travel_ai_concierge.providers import travel_search as travel_search_module

    travel_search_module.get_travel_search_provider.cache_clear()
    monkeypatch.setattr(
        "travel_ai_concierge.providers.travel_search.get_settings",
        lambda: Settings(_env_file=None, travel_search_provider="local"),  # type: ignore[call-arg]
    )

    provider = travel_search_module.get_travel_search_provider()

    assert isinstance(provider, LocalSyntheticTravelSearchProvider)
    travel_search_module.get_travel_search_provider.cache_clear()


def test_factory_returns_api_provider(monkeypatch: pytest.MonkeyPatch):
    from travel_ai_concierge.providers import travel_search as travel_search_module

    travel_search_module.get_travel_search_provider.cache_clear()
    monkeypatch.setattr(
        "travel_ai_concierge.providers.travel_search.get_settings",
        lambda: Settings(  # type: ignore[call-arg]
            _env_file=None,
            travel_search_provider="travel_ai_search_api",
            travel_ai_search_base_url="http://travel-search:8100",
        ),
    )

    provider = travel_search_module.get_travel_search_provider()

    assert isinstance(provider, TravelAISearchAPIProvider)
    travel_search_module.get_travel_search_provider.cache_clear()


def test_factory_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch):
    from travel_ai_concierge.providers import travel_search as travel_search_module

    travel_search_module.get_travel_search_provider.cache_clear()
    monkeypatch.setattr(
        "travel_ai_concierge.providers.travel_search.get_settings",
        lambda: Settings(_env_file=None, travel_search_provider="does-not-exist"),  # type: ignore[call-arg]
    )

    with pytest.raises(ValueError, match="Unknown travel search provider"):
        travel_search_module.get_travel_search_provider()

    travel_search_module.get_travel_search_provider.cache_clear()
