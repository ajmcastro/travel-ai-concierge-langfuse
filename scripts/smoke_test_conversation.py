#!/usr/bin/env python3
"""Milestone 7 smoke test: a real multi-turn conversation over real HTTP.

Usage
-----
    make serve                      # in one terminal
    make conversation-smoke-test    # in another

Same real-HTTP-client approach as scripts/smoke_test_chat.py (Milestone 2) —
this exercises the actual request path, not an in-process shortcut.

What this demonstrates
-----------------------
Three turns in one session_id, where the second and third only make sense if
the concierge remembers the first (the same "ask a clarifying question, then
use the answer" shape the project spec itself gives as an example). The mock
provider's own reply text always just echoes the latest message — it isn't a
planner — so the real proof of memory isn't in what it says here, it's in:

1. GET /sessions/{session_id} afterward, showing this app's own stored
   record of all three turns (not just the last one).
2. Each turn's Langfuse trace, whose `history_turns` metadata (Milestone 6's
   metadata axis) grows 0 -> 1 -> 2 across the three trace URLs printed below
   — open them side by side to see the input message list actually growing,
   which is the "context accumulation" analysis question Milestone 7's spec
   section names directly.
"""

import sys
import uuid

import httpx

BASE_URL = "http://localhost:8000"

CONVERSATION = [
    "Find me somewhere warm for a week.",
    "My budget is around $2000 and I'm departing from Lisbon.",
    "Actually, let's look at hotels in the Algarve instead.",
]


def _post_chat(session_id: str, message: str) -> dict:
    response = httpx.post(
        f"{BASE_URL}/chat", json={"message": message, "session_id": session_id}, timeout=30.0
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    session_id = f"smoke-conversation-{uuid.uuid4().hex[:8]}"
    print(f"Session ID: {session_id}\n")

    try:
        for i, message in enumerate(CONVERSATION, start=1):
            body = _post_chat(session_id, message)
            print(f"Turn {i}")
            print(f"  User:      {message}")
            print(f"  Assistant: {body['message']}")
            trace_id = body.get("trace_id")
            if trace_id:
                from travel_ai_concierge.observability import get_langfuse_client

                print(f"  Trace URL: {get_langfuse_client().get_trace_url(trace_id=trace_id)}")
            print()
    except httpx.ConnectError:
        print(
            f"Could not reach {BASE_URL}. Is the server running? Try: make serve", file=sys.stderr
        )
        return 1

    session_response = httpx.get(f"{BASE_URL}/sessions/{session_id}", timeout=10.0)
    session_response.raise_for_status()
    session_body = session_response.json()

    print(f"GET /sessions/{session_id} -> {session_body['turn_count']} turn(s) stored:")
    for i, turn in enumerate(session_body["turns"], start=1):
        print(f"  {i}. {turn['user_message']!r} -> {turn['assistant_message']!r}")

    print(
        "\nOpen the trace URLs above side by side: each turn's `agent`/`llm_call` "
        "input list — and the trace's `history_turns` metadata — should grow by "
        "one exchange per turn, not reset."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
