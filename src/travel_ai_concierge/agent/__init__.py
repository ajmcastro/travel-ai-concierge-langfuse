from functools import lru_cache

from langgraph.graph.state import CompiledStateGraph

from travel_ai_concierge.agent.graph import build_graph
from travel_ai_concierge.agent.state import AgentState

__all__ = ["AgentState", "get_agent_graph"]


@lru_cache(maxsize=1)
def get_agent_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    # A compiled graph is stateless and safe to reuse across requests — state
    # is passed per-invocation via ainvoke(), never stored on the graph
    # object itself. Same singleton pattern as get_settings()/get_llm_provider().
    return build_graph()
