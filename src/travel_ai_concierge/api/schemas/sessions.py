from pydantic import BaseModel


class SessionTurn(BaseModel):
    user_message: str
    assistant_message: str
    # Same privacy/production convention as ChatResponse.trace_id: a
    # development convenience for jumping straight to a turn's trace in
    # Langfuse, not something a real production client should see.
    trace_id: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    turn_count: int
    turns: list[SessionTurn]
