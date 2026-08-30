#!/usr/bin/env python3
"""Milestone 5 smoke test: compare "simple chatbot" vs. "tool-using agent" traces.

Usage
-----
    make agent-smoke-test

Calls both code paths directly, in-process — no running server needed, and
no environment restart to flip AGENT_ENABLED (which is baked into a running
`/chat` server's own process at startup, not something a client can toggle
per-request). This is the exact comparison the milestone spec asks for:
same message, same provider, two trace shapes.
"""

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import Message, get_llm_provider

SYSTEM_PROMPT = "You are a helpful, concise travel concierge."
MESSAGE = "find me a hotel"


async def main() -> int:
    settings = get_settings()
    client = get_langfuse_client()
    provider = get_llm_provider()

    print(f'Message: "{MESSAGE}"\n')

    # --- Simple chatbot (Milestone 2 shape): one direct provider call ---
    print("=== Simple chatbot (no tools) ===")
    with client.start_as_current_observation(
        name="travel_concierge_turn", input={"message": MESSAGE}
    ) as span:
        trace_id_simple = span.trace_id
        messages = [
            Message(role="system", content=SYSTEM_PROMPT),
            Message(role="user", content=MESSAGE),
        ]
        response = await provider.complete(messages)
        span.update(output={"message": response.content})
    print(f"  Response: {response.content}")

    # --- Tool-using agent (Milestone 5 shape): the LangGraph loop ---
    print("\n=== Tool-using agent ===")
    graph = get_agent_graph()
    with client.start_as_current_observation(
        name="travel_concierge_turn", input={"message": MESSAGE}
    ) as span:
        trace_id_agent = span.trace_id
        result = await graph.ainvoke(
            {
                "messages": [
                    Message(role="system", content=SYSTEM_PROMPT),
                    Message(role="user", content=MESSAGE),
                ],
                "iterations": 0,
            }
        )
        final_message = result["messages"][-1]
        span.update(output={"message": final_message.content})
    print(f"  Iterations: {result['iterations']}")
    print(f"  Response:   {final_message.content}")

    client.flush()

    print("\nCompare the two traces in Langfuse:")
    print(f"  Simple chatbot:   {client.get_trace_url(trace_id=trace_id_simple)}")
    print(f"  Tool-using agent: {client.get_trace_url(trace_id=trace_id_agent)}")
    print(f"  ({settings.langfuse_host})")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
