"""Tests for the synthetic travel tools (Milestone 4).

Offline by design: the dataset is local JSON, and opening a Langfuse `tool`
span is local-only (no network) regardless of whether a parent trace is
active — consistent with the rest of this project's tests. These assert on
business logic (filtering correctness), not on Langfuse internals.
"""

from travel_ai_concierge.tools import (
    get_destination_information,
    search_destinations,
    search_hotels,
)
from travel_ai_concierge.tools.data import get_destinations, get_hotels


def test_dataset_loads():
    assert len(get_destinations()) == 8
    assert len(get_hotels()) == 18


def test_dataset_is_cached_singleton():
    assert get_destinations() is get_destinations()
    assert get_hotels() is get_hotels()


def test_search_destinations_no_filters_returns_up_to_limit():
    results = search_destinations(limit=3)
    assert len(results) == 3


def test_search_destinations_by_tag():
    results = search_destinations(tags=["beach"])
    ids = {d.id for d in results}
    assert ids == {"algarve", "mallorca", "santorini"}


def test_search_destinations_by_tag_is_any_overlap_not_all():
    # "romantic" only appears on santorini; "beach" appears on 3 — a
    # destination matching either tag should be included, not just ones
    # matching every tag in the list.
    results = search_destinations(tags=["romantic", "beach"])
    ids = {d.id for d in results}
    assert "santorini" in ids
    assert "algarve" in ids


def test_search_destinations_by_climate():
    results = search_destinations(climate="subarctic")
    assert [d.id for d in results] == ["reykjavik"]


def test_search_destinations_combines_filters():
    results = search_destinations(tags=["quiet"], climate="mediterranean")
    ids = {d.id for d in results}
    assert ids == {"santorini"}


def test_search_destinations_unknown_climate_returns_empty():
    assert search_destinations(climate="lunar") == []


def test_search_hotels_scoped_to_destination():
    results = search_hotels("porto")
    assert all(h.destination_id == "porto" for h in results)
    assert len(results) == 2


def test_search_hotels_unknown_destination_returns_empty():
    assert search_hotels("atlantis") == []


def test_search_hotels_family_friendly_filter():
    results = search_hotels("algarve", family_friendly=True)
    assert {h.id for h in results} == {"algarve-beach-resort", "algarve-budget-inn"}


def test_search_hotels_max_price_band_is_inclusive_and_below():
    # mallorca has one hotel each of budget/mid/luxury; max_price_band="mid"
    # should include the budget and mid ones but exclude the luxury one.
    results = search_hotels("mallorca", max_price_band="mid")
    assert {h.id for h in results} == {"mallorca-family-resort", "mallorca-party-hotel"}


def test_search_hotels_combines_filters():
    results = search_hotels("algarve", family_friendly=False, max_price_band="mid")
    assert {h.id for h in results} == {"algarve-adults-retreat"}


def test_get_destination_information_found():
    result = get_destination_information("kyoto")
    assert result is not None
    assert result.name == "Kyoto"


def test_get_destination_information_not_found():
    assert get_destination_information("atlantis") is None
