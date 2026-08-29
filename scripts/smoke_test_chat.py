#!/usr/bin/env python3
"""Milestone 2 smoke test: call the running /chat endpoint over real HTTP.

Usage
-----
    make serve                 # in one terminal
    make chat-smoke-test       # in another

Unlike scripts/smoke_test_langfuse.py (Milestone 1), this hits the actual
FastAPI server as a real HTTP client would — it does not import the app
in-process. That's deliberate: it exercises the full request path (FastAPI
routing, Pydantic validation, the provider factory, Langfuse instrumentation)
exactly as a real client would, rather than the thinner guarantee an
in-process TestClient call gives you.
"""

import sys

import httpx


def main() -> int:
    base_url = "http://localhost:8000"

    try:
        response = httpx.post(
            f"{base_url}/chat",
            json={"message": "Plan me a quiet 5-day trip to Portugal"},
            timeout=30.0,
        )
    except httpx.ConnectError:
        print(
            f"Could not reach {base_url}. Is the server running? Try: make serve", file=sys.stderr
        )
        return 1

    if response.status_code != 200:
        print(f"Unexpected status {response.status_code}: {response.text}", file=sys.stderr)
        return 1

    body = response.json()
    print(f"Session ID: {body['session_id']}")
    print(f"Response:   {body['message']}")
    print(f"Model:      {body['metadata'].get('model')}")

    trace_id = body.get("trace_id")
    if trace_id:
        # Only present when the server has DEBUG=true — reconstructing the
        # URL locally rather than calling get_trace_url() over the network,
        # since this script only needs the project slug from .env, already
        # known from Milestone 1's setup.
        from travel_ai_concierge.observability import get_langfuse_client

        url = get_langfuse_client().get_trace_url(trace_id=trace_id)
        print(f"Trace URL:  {url}")
    else:
        print("No trace_id in response — set DEBUG=true in .env to see one.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
