#!/usr/bin/env python3
"""Milestone 4 smoke test: call the synthetic travel tools directly.

Usage
-----
    make tools-smoke-test

Demonstrates the tools independent of any LLM or agent — they are not wired
into /chat's decision loop yet (that's Milestone 5; see
docs/RATIONALE_PER_MILESTONE.md for why). Each call below has no parent
trace active, so each becomes its own root trace named after the tool,
with a real Langfuse `tool` observation — not a generic `span`.
"""

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.tools import (
    get_destination_information,
    search_destinations,
    search_hotels,
)


def main() -> int:
    settings = get_settings()
    client = get_langfuse_client()

    print("search_destinations(tags=['beach'], climate='mediterranean')")
    destinations = search_destinations(tags=["beach"], climate="mediterranean")
    for d in destinations:
        print(f"  - {d.id}: {d.name} ({d.country})")

    print()
    print("search_hotels('algarve', family_friendly=True)")
    hotels = search_hotels("algarve", family_friendly=True)
    for h in hotels:
        print(f"  - {h.id}: {h.name} [{h.price_band}]")

    print()
    print("get_destination_information('kyoto')")
    kyoto = get_destination_information("kyoto")
    print(f"  - {kyoto.description if kyoto else 'not found'}")

    client.flush()

    print()
    print(f"Done. {len(destinations) + len(hotels) + 1} tool calls made, each its own trace.")
    print(f"Open Langfuse at {settings.langfuse_host} -> Tracing to inspect them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
