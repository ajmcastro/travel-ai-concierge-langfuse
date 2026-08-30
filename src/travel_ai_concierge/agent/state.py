from typing import TypedDict

from travel_ai_concierge.providers.llm.base import Message


class AgentState(TypedDict):
    """Verified against a toy LangGraph run (Milestone 5): a node reads the
    full current state and returns a dict of the fields it wants to update.
    `messages` uses whole-list replacement, not a reducer — each node builds
    the complete new list itself (explicit over LangGraph's Annotated-reducer
    convenience), so there is no hidden merge behaviour to reason about.
    """

    messages: list[Message]
    iterations: int
