#!/usr/bin/env python3
"""Milestone 8 smoke test: compare prompt v1 (production) vs v2 (staging).

Usage
-----
    make seed-prompts          # create/update v1 + v2 in Langfuse, once
    make prompts-smoke-test    # this script — no server needed

Calls both labels directly, in-process — same reasoning as
scripts/smoke_test_agent.py: a running `/chat` server's PROMPT_LABEL is fixed
at process startup, not something a client can toggle per-request.

Honest limitation: MockProvider (the default, offline provider) never reads
the system prompt's content at all — its `_decide()` only ever looks at the
last *user* message (see providers/llm/mock.py). So the two replies below
will be identical regardless of which prompt produced them; this script
proves the retrieval/labeling/fallback/linking *mechanism* works, not that
v2 is behaviorally better. That comparison needs a real provider — set
LLM_PROVIDER=anthropic and re-run, or see
tests/integration/test_prompt_versions.py for the skip-by-default version of
that same comparison.
"""

from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.prompts import SYSTEM_PROMPT_NAME
from travel_ai_concierge.providers.llm import Message, get_llm_provider

MESSAGE = "Tell me about a hotel in the Algarve."


async def main() -> int:
    client = get_langfuse_client()
    provider = get_llm_provider()

    trace_ids = {}
    for label in ("production", "staging"):
        prompt = client.get_prompt(SYSTEM_PROMPT_NAME, label=label, type="text")
        print(f"=== label={label!r}: v{prompt.version} (config={prompt.config}) ===")
        print(f"  Prompt: {prompt.prompt[:100]}...")

        from langfuse import propagate_attributes

        with client.start_as_current_observation(
            name="travel_concierge_turn", input={"message": MESSAGE}
        ) as span:
            trace_ids[label] = span.trace_id
            with propagate_attributes(tags=[f"prompt-label:{label}"], prompt=prompt):
                messages = [
                    Message(role="system", content=prompt.compile()),
                    Message(role="user", content=MESSAGE),
                ]
                response = await provider.complete(messages)
            span.update(output={"message": response.content})
        print(f"  Response: {response.content}\n")

    client.flush()

    print("Compare the two traces in Langfuse (same message, different prompt version):")
    for label, trace_id in trace_ids.items():
        print(f"  {label:10s}: {client.get_trace_url(trace_id=trace_id)}")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
