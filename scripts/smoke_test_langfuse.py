#!/usr/bin/env python3
"""Milestone 1 smoke test: connect to Langfuse and create one real trace.

Usage
-----
    make langfuse-smoke-test
    # or directly:
    uv run python scripts/smoke_test_langfuse.py

What this demonstrates
-----------------------
- `auth_check()`      — verifies the configured API keys are valid (blocking;
                        fine for a one-off script, not for the request path).
- a root span         — the top-level unit of work; its enclosing trace is
                        created implicitly the first time a span is opened.
- a nested generation — a span type that additionally records model, token
                        usage, and latency, standing in here for a real LLM
                        call we don't have until Milestone 2.
- propagate_attributes — the recommended way to set trace-level session_id /
                        user_id / tags so they apply to every span in the
                        trace, not just the one you set them on.
- flush()             — spans are batched asynchronously; a short-lived
                        script must flush before exiting or it may lose data.

After running, open the printed trace URL in Langfuse to see the result.
"""

import sys
import time
import uuid

from langfuse import propagate_attributes

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client


def main() -> int:
    settings = get_settings()
    client = get_langfuse_client()

    print(f"Connecting to Langfuse at {settings.langfuse_host} ...")
    try:
        if not client.auth_check():
            print("Authentication failed: credentials were rejected.", file=sys.stderr)
            return 1
    except Exception as exc:  # noqa: BLE001 — this script's whole job is to surface this clearly
        print(f"Could not reach Langfuse: {exc}", file=sys.stderr)
        print("Is the stack running? Try: make langfuse-up", file=sys.stderr)
        return 1

    print("Authenticated. Creating a test trace ...")

    session_id = f"smoke-test-{uuid.uuid4().hex[:8]}"

    with client.start_as_current_observation(
        name="travel_concierge_turn",
        input={"message": "smoke test — no real user input"},
    ) as root_span:
        # Capture the trace_id now — it is only available on the span/context
        # while a span from this trace is still active; both go away once we
        # leave this `with` block.
        trace_id = root_span.trace_id

        with propagate_attributes(
            session_id=session_id,
            user_id="smoke-test-user",
            tags=["milestone-1", "smoke-test"],
            environment=settings.environment,
        ):
            with client.start_as_current_observation(
                name="mock_llm_call",
                as_type="generation",
                model="mock-model",
                input=[{"role": "user", "content": "smoke test"}],
            ) as generation:
                time.sleep(0.05)  # stand-in for real LLM latency
                generation.update(
                    output="This is a fixture response from the Milestone 1 smoke test.",
                    usage_details={"input": 10, "output": 12},
                )

            root_span.update(output={"status": "ok"})

    client.flush()

    trace_url = client.get_trace_url(trace_id=trace_id) if trace_id else None
    print(f"Trace ID:  {trace_id}")
    print(f"Trace URL: {trace_url}")
    print("Done. Open the URL above to inspect the trace in Langfuse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
