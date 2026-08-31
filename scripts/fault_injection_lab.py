#!/usr/bin/env python3
"""Milestone 15: the "failure and resilience laboratory" the spec asks for.

Usage
-----
    make fault-injection-lab

Runs one representative message through the real agent graph under each of
the project spec's named fault types, in-process, no running server needed
(same pattern as `smoke_test_agent.py`). For each: prints whether the call
raised, what the resulting HTTP behavior would be, and a real Langfuse
trace URL to inspect. This is the concrete evidence behind
docs/DEBUGGING_WORKFLOWS.md, not a script that only prints reassuring text —
every claim it makes is checked against what actually happened this run.

Two fault families behave differently by design (see faults.py's own
docstring for why): tool-layer faults (tool_exception, tool_timeout,
llm_malformed_output) are recovered by the agent's own second LLM call —
HTTP 200, a real answer. LLM-layer call failures (llm_timeout,
llm_provider_unavailable) have no equivalent second chance — HTTP 500,
clean failure, not a hang. "No search results" and "Langfuse unavailable"
need no fault injection at all: the first is already the tools' normal
behavior on an empty match; the second is demonstrated by pointing
LANGFUSE_HOST at an unreachable port for one run.
"""

import asyncio
import os
import time

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.faults import FaultInjectingProvider, make_failing_tool
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import Message, get_llm_provider
from travel_ai_concierge.tools import TOOL_REGISTRY, search_hotels

SYSTEM_PROMPT = "You are a helpful, concise travel concierge."
MESSAGE = "find me a hotel"


async def _run(label: str, message: str = MESSAGE) -> None:
    client = get_langfuse_client()
    graph = get_agent_graph()
    print(f"=== {label} ===")

    with client.start_as_current_observation(
        name="travel_concierge_turn", input={"message": message}
    ) as span:
        trace_id = span.trace_id
        try:
            result = await graph.ainvoke(
                {
                    "messages": [
                        Message(role="system", content=SYSTEM_PROMPT),
                        Message(role="user", content=message),
                    ],
                    "iterations": 0,
                }
            )
            final_message = result["messages"][-1]
            span.update(output={"message": final_message.content})
            print("  Result: HTTP 200 (would-be) — the request completed")
            print(f"  Response: {final_message.content[:200]}")
        except Exception as exc:
            span.update(level="ERROR", status_message=str(exc))
            print(f"  Result: HTTP 500 (would-be) — raised {type(exc).__name__}: {exc}")

    client.flush()
    print(f"  Trace: {client.get_trace_url(trace_id=trace_id)}\n")


async def _run_llm_fault(label: str, fault: str) -> None:
    import travel_ai_concierge.agent.nodes as agent_nodes

    original_get_llm_provider = agent_nodes.get_llm_provider  # type: ignore[attr-defined]
    tracker = FaultInjectingProvider(original_get_llm_provider(), fault=fault)  # type: ignore[arg-type]
    agent_nodes.get_llm_provider = lambda: tracker  # type: ignore[attr-defined, assignment]
    try:
        await _run(label)
    finally:
        agent_nodes.get_llm_provider = original_get_llm_provider  # type: ignore[attr-defined]


async def _run_tool_fault(label: str, fault: str, tool_name: str) -> None:
    original_tool = TOOL_REGISTRY[tool_name]
    TOOL_REGISTRY[tool_name] = make_failing_tool(fault, tool_name=tool_name)  # type: ignore[arg-type]
    try:
        await _run(label)
    finally:
        TOOL_REGISTRY[tool_name] = original_tool


def _run_no_search_results() -> None:
    # No fault injection needed or possible here: MockProvider's trigger
    # table always calls search_hotels with a fixed, real destination_id
    # ("algarve") regardless of what the user actually asked — it can't be
    # steered into a genuinely empty result through the mocked agent loop.
    # Calling the real tool directly, standalone (the same "no parent trace"
    # pattern tools-smoke-test already uses), demonstrates the tool's own
    # actual behavior on a destination nothing matches.
    print("=== No search results (real tool call, no fault injected) ===")
    client = get_langfuse_client()
    results = search_hotels(destination_id="atlantis")  # not a real destination in the dataset
    print(f"  Result: HTTP 200 (would-be) — {len(results)} hotels found (empty is not an error)")
    client.flush()
    print()


async def _run_langfuse_unavailable() -> None:
    # Points LANGFUSE_HOST at a closed local port for this one run only —
    # localhost avoids a slow DNS lookup, an unopened port fails fast
    # (ECONNREFUSED), so this stays quick without needing a real unreachable
    # host. Settings/provider/graph caches all get cleared so the rebuilt
    # Langfuse client actually picks up the bad host, then cleared again
    # afterward to restore the real one for any later run in this process.
    original_host = os.environ.get("LANGFUSE_HOST")
    os.environ["LANGFUSE_HOST"] = "http://localhost:1"
    get_settings.cache_clear()
    get_langfuse_client.cache_clear()
    get_llm_provider.cache_clear()
    get_agent_graph.cache_clear()
    try:
        print("=== Langfuse unavailable (LANGFUSE_HOST=http://localhost:1) ===")
        graph = get_agent_graph()
        start = time.monotonic()
        result = await graph.ainvoke(
            {
                "messages": [
                    Message(role="system", content=SYSTEM_PROMPT),
                    Message(role="user", content=MESSAGE),
                ],
                "iterations": 0,
            }
        )
        elapsed_ms = (time.monotonic() - start) * 1000
        final_message = result["messages"][-1]
        print(f"  Result: HTTP 200 (would-be) — completed in {elapsed_ms:.1f}ms despite Langfuse being unreachable")
        print(f"  Response: {final_message.content[:200]}")
        print("  (nothing to inspect in Langfuse for this run — that's the point)\n")
    finally:
        if original_host is not None:
            os.environ["LANGFUSE_HOST"] = original_host
        else:
            os.environ.pop("LANGFUSE_HOST", None)
        get_settings.cache_clear()
        get_langfuse_client.cache_clear()
        get_llm_provider.cache_clear()
        get_agent_graph.cache_clear()


async def main() -> int:
    await _run("Baseline (no fault)")
    await _run_llm_fault("LLM timeout", "llm_timeout")
    await _run_llm_fault("LLM provider unavailable", "llm_provider_unavailable")
    await _run_llm_fault("Malformed model output (tool call missing arguments)", "llm_malformed_output")
    await _run_tool_fault("Tool exception (travel provider error)", "tool_exception", "search_hotels")
    await _run_tool_fault("Tool timeout", "tool_timeout", "search_hotels")
    _run_no_search_results()
    await _run_langfuse_unavailable()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
