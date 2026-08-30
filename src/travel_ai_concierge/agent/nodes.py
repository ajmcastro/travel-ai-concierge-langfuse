import json

from pydantic import BaseModel

from travel_ai_concierge.agent.state import AgentState
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import Message, get_llm_provider
from travel_ai_concierge.tools import TOOL_REGISTRY, TOOL_SPECS


def _serialize_tool_result(result: object) -> str:
    if result is None:
        return "null"
    if isinstance(result, BaseModel):
        return result.model_dump_json()
    if isinstance(result, list):
        return json.dumps(
            [item.model_dump() if isinstance(item, BaseModel) else item for item in result]
        )
    return json.dumps(result)


async def agent_node(state: AgentState) -> dict[str, object]:
    """The reasoning step: one LLM call, with tools offered.

    This is a real, distinct Langfuse `agent` observation (not a generic
    span) — same principle as Milestone 4's `tool` type: tell Langfuse what
    kind of thing this is, don't just name it descriptively.

    Once this is about to be the last call `_route_after_agent`'s hard cap
    would allow, tools are withheld instead — the API physically cannot
    return a tool_use block if none were offered, guaranteeing a text
    response instead of one last empty-content tool request the graph would
    then have nowhere to route. The threshold below is deliberately
    `iterations + 1 >= max`, not `iterations >= max`: tracing through by
    hand showed that comparing pre-increment iterations against the same
    bound routing checks post-increment made this branch unreachable — the
    hard cap in routing would always fire one call earlier, making this
    branch dead code — caught by tracing the exact call sequence by hand
    for a small max_iterations before running anything, not by a failing
    test (see tests/unit/test_agent.py for the two tests that pin this:
    one with a provider that ignores `tools=None` to prove routing's cap
    is a real backstop, one that respects it to prove this branch is
    actually reachable and produces a usable answer).
    """
    client = get_langfuse_client()
    provider = get_llm_provider()
    settings = get_settings()

    forced_final = state["iterations"] + 1 >= settings.agent_max_iterations
    tools = None if forced_final else TOOL_SPECS

    with client.start_as_current_observation(
        name="agent",
        as_type="agent",
        input={"iteration": state["iterations"], "forced_final": forced_final},
    ) as span:
        response = await provider.complete(state["messages"], tools=tools)
        new_message = Message(
            role="assistant", content=response.content, tool_calls=response.tool_calls
        )
        span.update(
            output={
                "tool_calls": [tc.name for tc in response.tool_calls],
                "has_final_text": bool(response.content) and not response.tool_calls,
            }
        )

    return {
        "messages": [*state["messages"], new_message],
        "iterations": state["iterations"] + 1,
    }


async def tools_node(state: AgentState) -> dict[str, object]:
    """Execute every tool call requested by the last agent message.

    Wraps the batch in one `execute_tools` span (matching the trace shape
    already documented in docs/architecture.md) so multiple tool calls in
    one turn nest under a single grouping step, each tool call itself
    nesting further as its own `tool` observation (Milestone 4) — no change
    needed in the tool functions themselves for that nesting to happen.
    """
    client = get_langfuse_client()
    last_message = state["messages"][-1]
    new_messages = list(state["messages"])

    with client.start_as_current_observation(
        name="execute_tools",
        input={"tool_calls": [tc.name for tc in last_message.tool_calls]},
    ) as span:
        for call in last_message.tool_calls:
            func = TOOL_REGISTRY.get(call.name)
            if func is None:
                result_content = f"Error: unknown tool {call.name!r}"
            else:
                try:
                    result_content = _serialize_tool_result(func(**call.arguments))
                except Exception as exc:  # noqa: BLE001 — a hallucinated tool call is the
                    # agent's problem to recover from, not a reason to fail the request.
                    result_content = f"Error executing {call.name}: {exc}"

            new_messages.append(
                Message(
                    role="tool",
                    content=result_content,
                    tool_call_id=call.id,
                    name=call.name,
                )
            )

        span.update(output={"executed": len(last_message.tool_calls)})

    return {"messages": new_messages}
