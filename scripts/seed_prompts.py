#!/usr/bin/env python3
"""Milestone 8: create/update the system prompt's v1 and v2 in Langfuse.

Usage
-----
    make seed-prompts

Safe to re-run: `create_prompt()` always creates a new version, it does not
mutate an existing one (Langfuse prompts are immutable per version, like git
commits) — running this again just adds new versions and moves each label to
point at the one just created. That's a feature here, not a footgun: it's
how you'd iterate on prompt text in practice.

Why two versions exist at all: `Settings.prompt_label` (default "production")
is this project's whole v1-vs-v2 comparison mechanism — flip it to "staging"
and `/chat` uses v2's text with zero code changes. See
scripts/smoke_test_prompts.py for a live comparison, and docs/RATIONALE_PER_MILESTONE.md
(Milestone 8) for why v2's *content* differs the way it does.
"""

from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.prompts import SYSTEM_PROMPT_FALLBACK, SYSTEM_PROMPT_NAME

PROMPT_V2 = (
    "You are a helpful, concise travel concierge. Ask clarifying questions when "
    "important details (destination, dates, budget, travellers) are missing. "
    "You MUST use the available tools whenever a user asks about specific "
    "destinations or hotels — never state a specific name, price, or rating from "
    "memory. Prefer calling a tool over guessing, even if you believe you already "
    "know the answer."
)


def main() -> int:
    client = get_langfuse_client()

    v1 = client.create_prompt(
        name=SYSTEM_PROMPT_NAME,
        prompt=SYSTEM_PROMPT_FALLBACK,
        type="text",
        labels=["production"],
        tags=["travel-concierge", "system-prompt"],
        config={
            "variant": "v1",
            "notes": "Original system prompt (Milestone 2) — tool use encouraged, not required.",
        },
        commit_message="v1: baseline system prompt from Milestone 2",
    )
    print(f"Created {v1.name} v{v1.version}, labels={v1.labels}")

    v2 = client.create_prompt(
        name=SYSTEM_PROMPT_NAME,
        prompt=PROMPT_V2,
        type="text",
        labels=["staging"],
        tags=["travel-concierge", "system-prompt"],
        config={
            "variant": "v2",
            "notes": "Directive tool-usage instruction — tests whether this reduces "
            "fabricated destination/hotel details (see PROJECT_SPEC.md's "
            "tool-selection-accuracy comparison criterion).",
        },
        commit_message="v2: require tool use for destination/hotel facts, don't just encourage it",
    )
    print(f"Created {v2.name} v{v2.version}, labels={v2.labels}")

    print(
        "\nBy default /chat uses the 'production' label (v1). Set "
        "PROMPT_LABEL=staging to use v2 instead — no code change needed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
