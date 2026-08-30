from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from travel_ai_concierge.agent.nodes import agent_node, tools_node
from travel_ai_concierge.agent.state import AgentState
from travel_ai_concierge.config import get_settings


def _route_after_agent(state: AgentState) -> str:
    # Two independent safeguards, not one: agent_node withholds tools once
    # agent_max_iterations is reached, so a well-behaved provider naturally
    # stops requesting them — that alone produces a clean final text answer
    # instead of a dangling empty-content tool request (found via the
    # max-iterations test). But routing does its own hard check too, rather
    # than trusting every provider to honour tools=None: a provider that
    # returned a tool_use block anyway would otherwise loop forever.
    last_message = state["messages"][-1]
    settings = get_settings()
    if last_message.tool_calls and state["iterations"] < settings.agent_max_iterations:
        return "tools"
    return END


def build_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Build the agent graph fresh (uncompiled StateGraph is not reusable).

    We hand-write every node and edge — no `langgraph.prebuilt` agent — per
    ADR-001's explicit decision: a developer should be able to read this
    function and see the entire routing logic, not trust a library default.
    """
    graph: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", _route_after_agent, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()
