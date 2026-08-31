from fastapi import APIRouter, HTTPException

from travel_ai_concierge.api.schemas.sessions import SessionResponse, SessionTurn
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.conversation import get_conversation_store

router = APIRouter(tags=["sessions"])


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    """Return this app's own record of a conversation's turns.

    This is deliberately app-level state (Settings.max_history_turns'
    trimmed window), not a proxy for Langfuse's own Session view — Langfuse
    already aggregates cost/latency/tokens per session_id natively (see
    docs/TRACE_DESIGN.md); this endpoint answers a different question
    ("what did this session actually say"), for a client that wants to
    restore or inspect conversation content without a Langfuse API key.
    """
    settings = get_settings()
    history = await get_conversation_store().get_history(session_id)

    if not history:
        raise HTTPException(status_code=404, detail=f"No session found for {session_id!r}")

    return SessionResponse(
        session_id=session_id,
        turn_count=len(history),
        turns=[
            SessionTurn(
                user_message=turn.user_message,
                assistant_message=turn.assistant_message,
                trace_id=turn.trace_id if settings.debug else None,
                message_id=turn.turn_id,
            )
            for turn in history
        ],
    )
