#!/usr/bin/env python3
"""Milestone 4: write the synthetic travel dataset to data/synthetic/.

The dataset is hand-authored, not randomly generated — at this scale (8
destinations, ~18 hotels), fixed content reviewed by a human is more useful
than seeded-random data, and "deterministic" only requires that running this
script twice produces byte-identical output, which plain literals do for
free. This script is the source of truth; data/synthetic/*.json are
regenerable, committed artifacts — edit the data here, then re-run:

    make generate-data
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"

DESTINATIONS = [
    {
        "id": "porto",
        "name": "Porto",
        "country": "Portugal",
        "region": "Northern Portugal",
        "climate": "temperate",
        "tags": ["food", "wine", "culture", "quiet", "city"],
        "best_months": ["Apr", "May", "Jun", "Sep", "Oct"],
        "description": "A compact riverside city built on port wine cellars and "
        "azulejo-tiled facades, best explored on foot.",
    },
    {
        "id": "algarve",
        "name": "Algarve",
        "country": "Portugal",
        "region": "Algarve",
        "climate": "mediterranean",
        "tags": ["beach", "family", "nightlife"],
        "best_months": ["May", "Jun", "Jul", "Aug", "Sep"],
        "description": "Portugal's southern coast: cliff-backed beaches, resort towns, "
        "and a long summer season.",
    },
    {
        "id": "lisbon",
        "name": "Lisbon",
        "country": "Portugal",
        "region": "Lisbon",
        "climate": "mediterranean",
        "tags": ["culture", "nightlife", "food", "city"],
        "best_months": ["Apr", "May", "Jun", "Sep", "Oct"],
        "description": "A hilly capital of tram lines, viewpoints, and a lively "
        "restaurant and nightlife scene.",
    },
    {
        "id": "mallorca",
        "name": "Mallorca",
        "country": "Spain",
        "region": "Balearic Islands",
        "climate": "mediterranean",
        "tags": ["beach", "nightlife", "family"],
        "best_months": ["May", "Jun", "Jul", "Aug", "Sep"],
        "description": "The largest Balearic island, ranging from resort strips to "
        "quiet inland villages and mountains.",
    },
    {
        "id": "santorini",
        "name": "Santorini",
        "country": "Greece",
        "region": "Cyclades",
        "climate": "mediterranean",
        "tags": ["beach", "romantic", "quiet", "culture"],
        "best_months": ["May", "Jun", "Sep", "Oct"],
        "description": "A volcanic caldera island of whitewashed villages and "
        "sunset views, popular with couples.",
    },
    {
        "id": "tuscany",
        "name": "Tuscany",
        "country": "Italy",
        "region": "Tuscany",
        "climate": "temperate",
        "tags": ["food", "wine", "culture", "quiet", "nature"],
        "best_months": ["Apr", "May", "Sep", "Oct"],
        "description": "Rolling vineyards and hill towns between Florence and Siena, "
        "built around food and wine.",
    },
    {
        "id": "reykjavik",
        "name": "Reykjavik",
        "country": "Iceland",
        "region": "Capital Region",
        "climate": "subarctic",
        "tags": ["nature", "quiet", "adventure"],
        "best_months": ["Jun", "Jul", "Aug"],
        "description": "A small capital used as a base for glaciers, geothermal "
        "areas, and the surrounding coastline.",
    },
    {
        "id": "kyoto",
        "name": "Kyoto",
        "country": "Japan",
        "region": "Kansai",
        "climate": "temperate",
        "tags": ["culture", "food", "quiet", "nature"],
        "best_months": ["Mar", "Apr", "Oct", "Nov"],
        "description": "Japan's former capital, dense with temples, gardens, and "
        "traditional wooden neighborhoods.",
    },
]

HOTELS = [
    # Porto
    {
        "id": "porto-riverside-boutique",
        "destination_id": "porto",
        "name": "Porto Riverside Boutique",
        "star_rating": 4,
        "customer_rating": 9.1,
        "price_band": "mid",
        "family_friendly": False,
        "adults_only": True,
        "amenities": ["wifi", "breakfast", "river-view"],
    },
    {
        "id": "porto-family-suites",
        "destination_id": "porto",
        "name": "Porto Family Suites",
        "star_rating": 3,
        "customer_rating": 8.4,
        "price_band": "budget",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["wifi", "kitchenette", "pool"],
    },
    # Algarve
    {
        "id": "algarve-beach-resort",
        "destination_id": "algarve",
        "name": "Algarve Beach Resort",
        "star_rating": 5,
        "customer_rating": 9.0,
        "price_band": "luxury",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["pool", "beach-access", "kids-club"],
    },
    {
        "id": "algarve-adults-retreat",
        "destination_id": "algarve",
        "name": "Algarve Adults Retreat",
        "star_rating": 4,
        "customer_rating": 8.8,
        "price_band": "mid",
        "family_friendly": False,
        "adults_only": True,
        "amenities": ["pool", "spa", "quiet"],
    },
    {
        "id": "algarve-budget-inn",
        "destination_id": "algarve",
        "name": "Algarve Budget Inn",
        "star_rating": 2,
        "customer_rating": 7.2,
        "price_band": "budget",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["wifi"],
    },
    # Lisbon
    {
        "id": "lisbon-baixa-hotel",
        "destination_id": "lisbon",
        "name": "Lisbon Baixa Hotel",
        "star_rating": 4,
        "customer_rating": 8.9,
        "price_band": "mid",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["wifi", "breakfast", "rooftop-bar"],
    },
    {
        "id": "lisbon-hostel-central",
        "destination_id": "lisbon",
        "name": "Lisbon Hostel Central",
        "star_rating": 2,
        "customer_rating": 8.0,
        "price_band": "budget",
        "family_friendly": False,
        "adults_only": False,
        "amenities": ["wifi", "shared-kitchen"],
    },
    # Mallorca
    {
        "id": "mallorca-family-resort",
        "destination_id": "mallorca",
        "name": "Mallorca Family Resort",
        "star_rating": 4,
        "customer_rating": 8.7,
        "price_band": "mid",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["pool", "kids-club", "beach-access"],
    },
    {
        "id": "mallorca-party-hotel",
        "destination_id": "mallorca",
        "name": "Mallorca Party Hotel",
        "star_rating": 3,
        "customer_rating": 7.9,
        "price_band": "budget",
        "family_friendly": False,
        "adults_only": True,
        "amenities": ["pool", "bar", "nightlife"],
    },
    {
        "id": "mallorca-luxury-villas",
        "destination_id": "mallorca",
        "name": "Mallorca Luxury Villas",
        "star_rating": 5,
        "customer_rating": 9.4,
        "price_band": "luxury",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["pool", "spa", "sea-view"],
    },
    # Santorini
    {
        "id": "santorini-caldera-suites",
        "destination_id": "santorini",
        "name": "Santorini Caldera Suites",
        "star_rating": 5,
        "customer_rating": 9.6,
        "price_band": "luxury",
        "family_friendly": False,
        "adults_only": True,
        "amenities": ["caldera-view", "pool", "spa"],
    },
    {
        "id": "santorini-budget-studios",
        "destination_id": "santorini",
        "name": "Santorini Budget Studios",
        "star_rating": 2,
        "customer_rating": 7.5,
        "price_band": "budget",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["wifi", "kitchenette"],
    },
    # Tuscany
    {
        "id": "tuscany-agriturismo",
        "destination_id": "tuscany",
        "name": "Tuscany Agriturismo",
        "star_rating": 3,
        "customer_rating": 9.0,
        "price_band": "mid",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["pool", "breakfast", "vineyard-view"],
    },
    {
        "id": "tuscany-boutique-villa",
        "destination_id": "tuscany",
        "name": "Tuscany Boutique Villa",
        "star_rating": 4,
        "customer_rating": 9.2,
        "price_band": "luxury",
        "family_friendly": False,
        "adults_only": True,
        "amenities": ["pool", "spa", "wine-tasting"],
    },
    # Reykjavik
    {
        "id": "reykjavik-city-hotel",
        "destination_id": "reykjavik",
        "name": "Reykjavik City Hotel",
        "star_rating": 3,
        "customer_rating": 8.3,
        "price_band": "mid",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["wifi", "breakfast"],
    },
    {
        "id": "reykjavik-northern-lights-lodge",
        "destination_id": "reykjavik",
        "name": "Reykjavik Northern Lights Lodge",
        "star_rating": 4,
        "customer_rating": 8.9,
        "price_band": "luxury",
        "family_friendly": False,
        "adults_only": False,
        "amenities": ["hot-tub", "aurora-tours"],
    },
    # Kyoto
    {
        "id": "kyoto-ryokan-traditional",
        "destination_id": "kyoto",
        "name": "Kyoto Traditional Ryokan",
        "star_rating": 4,
        "customer_rating": 9.3,
        "price_band": "luxury",
        "family_friendly": False,
        "adults_only": False,
        "amenities": ["onsen", "kaiseki-dinner", "garden"],
    },
    {
        "id": "kyoto-budget-guesthouse",
        "destination_id": "kyoto",
        "name": "Kyoto Budget Guesthouse",
        "star_rating": 2,
        "customer_rating": 8.1,
        "price_band": "budget",
        "family_friendly": True,
        "adults_only": False,
        "amenities": ["wifi", "shared-kitchen"],
    },
]


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    destinations_path = DATA_DIR / "destinations.json"
    hotels_path = DATA_DIR / "hotels.json"

    destinations_path.write_text(json.dumps(DESTINATIONS, indent=2) + "\n")
    hotels_path.write_text(json.dumps(HOTELS, indent=2) + "\n")

    print(f"Wrote {len(DESTINATIONS)} destinations -> {destinations_path}")
    print(f"Wrote {len(HOTELS)} hotels -> {hotels_path}")


if __name__ == "__main__":
    main()
