from langfuse import propagate_attributes

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.evaluation.models import CaseResult, EvaluationCase
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.prompts import get_system_prompt
from travel_ai_concierge.providers.llm import Message


async def run_case(case: EvaluationCase) -> CaseResult:
    """Run one evaluation case through the real agent graph.

    Deliberately always the agent path (`get_agent_graph()`), regardless of
    `Settings.agent_enabled` — evaluation exists to test tool-selection and
    agent behavior, so bypassing the agent would defeat the point. Each case
    gets its own real Langfuse trace (`travel_concierge_turn`, same span
    name production traffic uses), tagged `evaluation` plus its query class,
    so a failing case can be opened and inspected exactly like a real
    request — not a parallel, invisible process.
    """
    client = get_langfuse_client()
    prompt = get_system_prompt()
    graph = get_agent_graph()

    with client.start_as_current_observation(
        name="travel_concierge_turn", input={"message": case.message}
    ) as span:
        trace_id = span.trace_id
        with propagate_attributes(
            session_id=f"evaluation-{case.id}",
            tags=["evaluation", case.query_class],
            metadata={"case_id": case.id, "query_class": case.query_class},
            prompt=prompt,
        ):
            messages = [
                Message(role="system", content=prompt.compile()),
                Message(role="user", content=case.message),
            ]
            state = await graph.ainvoke({"messages": messages, "iterations": 0})
        span.update(output={"message": state["messages"][-1].content})

    tool_calls: list[str] = []
    tool_arguments_by_name: dict[str, dict[str, object]] = {}
    tool_result_texts: list[str] = []
    for message in state["messages"]:
        if message.role == "assistant":
            for call in message.tool_calls:
                tool_calls.append(call.name)
                # First occurrence only if a tool is called more than once —
                # keeps argument-checking scoped to the common single-call
                # case (see EvaluationCase's own docstring).
                tool_arguments_by_name.setdefault(call.name, call.arguments)
        elif message.role == "tool":
            tool_result_texts.append(message.content)

    return CaseResult(
        case_id=case.id,
        query_class=case.query_class,
        trace_id=trace_id,
        tool_calls=tool_calls,
        tool_arguments_by_name=tool_arguments_by_name,
        tool_result_texts=tool_result_texts,
        final_response=state["messages"][-1].content,
        iterations=state["iterations"],
    )
