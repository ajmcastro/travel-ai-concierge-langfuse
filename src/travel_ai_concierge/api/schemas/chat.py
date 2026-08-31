from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    # No user_id -> stays unset in Langfuse rather than being fabricated, so
    # aggregations by user_id only ever reflect real, stable identities.
    user_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    message: str
    # Only populated when Settings.debug is True — a trace identifier is a
    # development convenience for immediate inspection, not something a real
    # production client should see (see docs/PROJECT_SPEC.md, FastAPI section).
    trace_id: str | None = None
    # Milestone 12: unlike trace_id, always populated — an opaque reference
    # to this turn for POST /feedback, deliberately not the real trace_id
    # (see conversation/store.py's Turn.turn_id).
    message_id: str
    metadata: dict[str, str] = Field(default_factory=dict)
