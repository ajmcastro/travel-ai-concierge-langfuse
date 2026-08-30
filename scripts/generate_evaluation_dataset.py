#!/usr/bin/env python3
"""Milestone 9: (re)write data/evaluation/cases.json.

Usage
-----
    uv run python scripts/generate_evaluation_dataset.py

Same pattern as scripts/generate_data.py: hand-authored content embedded
directly in this script (not procedurally generated combinatorics — the
spec explicitly warns against a dataset that "depends entirely on
LLM-generated labels", and hand-written expectations are the more honest
alternative to either), written out to JSON that the app loads at runtime
(evaluation/dataset.py).

Every case's expectations describe what a *real, reasoning* agent should
do — grounded in the actual synthetic dataset (real destination IDs, tags,
price bands from data/synthetic/*.json) and the actual tool schemas
(tools/specs.py). They are not tuned to match MockProvider's fixed
keyword-trigger behavior; see docs/RATIONALE_PER_MILESTONE.md (Milestone 9)
for why that's a deliberate choice, not an oversight.

`max_price_band` is a *ceiling* (includes this band and cheaper — see
domain/models.py's price_band_at_most()), not an exact-match filter. That
makes it well-suited to expressing "budget" queries (ceiling of "budget" =
budget only) but unable to express "luxury only" (ceiling of "luxury" =
any band at all) — so "luxury" cases below deliberately don't assert a
max_price_band argument; a well-informed agent facing this tool's actual
semantics would omit that filter and reason over the returned list instead.
"""

import json
from pathlib import Path

CASES = [
    # --- destination recommendation ---
    {
        "id": "destination-recommendation-001",
        "query_class": "destination_recommendation",
        "message": "I love good food, wine, and quiet places — any destination recommendations?",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["food", "wine", "quiet"]},
    },
    {
        "id": "destination-recommendation-002",
        "query_class": "destination_recommendation",
        "message": "Where can I find beach destinations that are also good for romance?",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["beach", "romantic"]},
    },
    # --- hotel recommendation ---
    {
        "id": "hotel-recommendation-001",
        "query_class": "hotel_recommendation",
        "message": "What hotels do you have in the Algarve?",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "algarve"},
    },
    {
        "id": "hotel-recommendation-002",
        "query_class": "hotel_recommendation",
        "message": "Show me hotels in Kyoto.",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "kyoto"},
    },
    # --- family holiday ---
    {
        "id": "family-holiday-001",
        "query_class": "family_holiday",
        "message": (
            "We're a family with two young kids looking for a beach holiday in the "
            "Algarve. What hotels would work?"
        ),
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "algarve", "family_friendly": True},
    },
    {
        "id": "family-holiday-002",
        "query_class": "family_holiday",
        "message": "Any family-friendly hotels in Mallorca?",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "mallorca", "family_friendly": True},
    },
    # --- couples holiday ---
    {
        "id": "couples-holiday-001",
        "query_class": "couples_holiday",
        "message": "My partner and I want a romantic getaway. Any destination ideas?",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["romantic"]},
    },
    {
        "id": "couples-holiday-002",
        "query_class": "couples_holiday",
        "message": "Looking for a quiet, romantic hotel in Santorini for our anniversary.",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "santorini"},
    },
    # --- budget ---
    {
        "id": "budget-001",
        "query_class": "budget",
        "message": "What's the cheapest hotel you have in Lisbon?",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "lisbon", "max_price_band": "budget"},
    },
    {
        "id": "budget-002",
        "query_class": "budget",
        "message": "I need a budget-friendly hotel in the Algarve, nothing fancy.",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "algarve", "max_price_band": "budget"},
    },
    # --- luxury ---
    {
        "id": "luxury-001",
        "query_class": "luxury",
        "message": "I want the most luxurious hotel available in Santorini.",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "santorini"},
    },
    {
        "id": "luxury-002",
        "query_class": "luxury",
        "message": "Book me the fanciest room you've got in Kyoto.",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "kyoto"},
    },
    # --- beach ---
    {
        "id": "beach-001",
        "query_class": "beach",
        "message": "I want a beach vacation, ideally somewhere lively with nightlife.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["beach", "nightlife"]},
    },
    {
        "id": "beach-002",
        "query_class": "beach",
        "message": "Recommend a good beach destination for a relaxing week.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["beach"]},
    },
    # --- city ---
    {
        "id": "city-001",
        "query_class": "city",
        "message": "I'm looking for a city break somewhere with great culture and nightlife.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["city", "culture", "nightlife"]},
    },
    {
        "id": "city-002",
        "query_class": "city",
        "message": "Any recommendations for a compact, walkable city?",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["city"]},
    },
    # --- culture ---
    {
        "id": "culture-001",
        "query_class": "culture",
        "message": "I want a trip full of culture, museums, and history.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["culture"]},
    },
    {
        "id": "culture-002",
        "query_class": "culture",
        "message": "Somewhere with rich history and traditional architecture, like temples.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["culture"]},
    },
    # --- nightlife ---
    {
        "id": "nightlife-001",
        "query_class": "nightlife",
        "message": "Where's good for nightlife and partying?",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["nightlife"]},
    },
    # --- quiet ---
    {
        "id": "quiet-001",
        "query_class": "quiet",
        "message": "I need somewhere peaceful and quiet to unwind, away from crowds.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["quiet"]},
    },
    {
        "id": "quiet-002",
        "query_class": "quiet",
        "message": "Looking for a calm, non-touristy hotel in Porto.",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "porto"},
    },
    # --- food/wine ---
    {
        "id": "food-wine-001",
        "query_class": "food_wine",
        "message": "I'm a foodie who loves wine regions.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["food", "wine"]},
    },
    {
        "id": "food-wine-002",
        "query_class": "food_wine",
        "message": "Recommend somewhere known for great food and wine culture.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["food", "wine"]},
    },
    # --- itinerary planning (no itinerary tool exists — see module docstring) ---
    {
        "id": "itinerary-planning-001",
        "query_class": "itinerary_planning",
        "message": "Can you build me a 5-day itinerary for Kyoto?",
        "expected_tools": ["get_destination_information"],
        "expected_arguments": {"destination_id": "kyoto"},
    },
    {
        "id": "itinerary-planning-002",
        "query_class": "itinerary_planning",
        "message": "Plan out a week in Tuscany for me, day by day.",
        "expected_tools": ["get_destination_information"],
        "expected_arguments": {"destination_id": "tuscany"},
    },
    # --- vague request ---
    {
        "id": "vague-request-001",
        "query_class": "vague_request",
        "message": "I want to go on vacation somewhere nice.",
        "expects_clarification": True,
    },
    {
        "id": "vague-request-002",
        "query_class": "vague_request",
        "message": "Help me plan a trip.",
        "expects_clarification": True,
    },
    # --- multi-constraint query ---
    {
        "id": "multi-constraint-001",
        "query_class": "multi_constraint",
        "message": "Family-friendly, budget hotel in the Algarve for a beach holiday.",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {
            "destination_id": "algarve",
            "family_friendly": True,
            "max_price_band": "budget",
        },
    },
    {
        "id": "multi-constraint-002",
        "query_class": "multi_constraint",
        "message": "Quiet, romantic destination somewhere with good beaches.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["beach", "quiet", "romantic"]},
    },
    # --- requests requiring clarification (spec's own canonical example) ---
    {
        "id": "requires-clarification-001",
        "query_class": "requires_clarification",
        "message": "Find me somewhere warm for a week.",
        "expects_clarification": True,
    },
    {
        "id": "requires-clarification-002",
        "query_class": "requires_clarification",
        "message": "I want to book a hotel.",
        "expects_clarification": True,
    },
    # --- requires one tool ---
    {
        "id": "requires-one-tool-001",
        "query_class": "requires_one_tool",
        "message": "Tell me about Lisbon.",
        "expected_tools": ["get_destination_information"],
        "expected_arguments": {"destination_id": "lisbon"},
    },
    {
        "id": "requires-one-tool-002",
        "query_class": "requires_one_tool",
        "message": "What's the climate like in Reykjavik?",
        "expected_tools": ["get_destination_information"],
        "expected_arguments": {"destination_id": "reykjavik"},
    },
    # --- requires multiple tools ---
    {
        "id": "requires-multiple-tools-001",
        "query_class": "requires_multiple_tools",
        "message": "Tell me about Santorini, then show me hotels there.",
        "expected_tools": ["get_destination_information", "search_hotels"],
    },
    {
        "id": "requires-multiple-tools-002",
        "query_class": "requires_multiple_tools",
        "message": (
            "Find me a beach destination good for families, then show me a hotel "
            "there for two kids."
        ),
        "expected_tools": ["search_destinations", "search_hotels"],
    },
    # --- impossible constraint ---
    {
        "id": "impossible-constraint-001",
        "query_class": "impossible_constraint",
        "message": "I want to book a hotel on the Moon.",
        "expected_tools": [],
    },
    {
        "id": "impossible-constraint-002",
        "query_class": "impossible_constraint",
        "message": "Find me a beach holiday in Antarctica.",
        "expected_tools": ["search_destinations"],
        "expected_arguments": {"tags": ["beach"]},
    },
    # --- contradictory preferences ---
    {
        "id": "contradictory-preferences-001",
        "query_class": "contradictory_preferences",
        "message": "I want a lively nightlife scene but somewhere completely quiet and peaceful.",
        "expects_clarification": True,
    },
    {
        "id": "contradictory-preferences-002",
        "query_class": "contradictory_preferences",
        "message": "I want a budget hotel but with five-star luxury amenities, in Mallorca.",
        "expected_tools": ["search_hotels"],
        "expected_arguments": {"destination_id": "mallorca", "max_price_band": "budget"},
    },
]

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "evaluation" / "cases.json"


def main() -> int:
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case ids"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(CASES, indent=2) + "\n")
    print(f"Wrote {len(CASES)} cases to {OUTPUT_PATH}")

    classes = sorted({c["query_class"] for c in CASES})
    print(f"Query classes covered ({len(classes)}): {', '.join(classes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
