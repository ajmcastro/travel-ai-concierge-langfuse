from collections.abc import Callable
from typing import Any

from travel_ai_concierge.providers.llm.base import ToolSpec
from travel_ai_concierge.tools.travel_tools import (
    get_destination_information,
    search_destinations,
    search_hotels,
)

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_destinations",
        description=(
            "Search travel destinations by tag overlap (e.g. beach, culture, quiet, "
            "food, nightlife, nature, romantic, family, adventure, wine) and/or exact "
            "climate match (e.g. mediterranean, temperate, subarctic)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'Interest tags to match, e.g. ["beach", "quiet"].',
                },
                "climate": {"type": "string", "description": "Exact climate to match."},
                "limit": {"type": "integer", "description": "Max results (default 5)."},
            },
        },
    ),
    ToolSpec(
        name="search_hotels",
        description=(
            "Search hotels within a single destination (by destination_id from "
            "search_destinations), optionally filtered by family-friendliness and a "
            "maximum price band."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "destination_id": {
                    "type": "string",
                    "description": 'Destination id, e.g. "algarve".',
                },
                "family_friendly": {"type": "boolean"},
                "max_price_band": {
                    "type": "string",
                    "enum": ["budget", "mid", "luxury"],
                    "description": "Ceiling price band — includes this and cheaper.",
                },
                "limit": {"type": "integer", "description": "Max results (default 5)."},
            },
            "required": ["destination_id"],
        },
    ),
    ToolSpec(
        name="get_destination_information",
        description="Look up full details for a single destination by its id.",
        input_schema={
            "type": "object",
            "properties": {
                "destination_id": {"type": "string"},
            },
            "required": ["destination_id"],
        },
    ),
]

TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "search_destinations": search_destinations,
    "search_hotels": search_hotels,
    "get_destination_information": get_destination_information,
}
