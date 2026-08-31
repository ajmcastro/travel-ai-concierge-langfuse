from fastapi import APIRouter, HTTPException

from travel_ai_concierge.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.conversation import get_conversation_store
from travel_ai_concierge.observability import get_langfuse_client

router = APIRouter(tags=["feedback"])

# One name, used consistently — Langfuse's own UI groups/filters scores by
# name, so a stray second name for the same concept would fragment "which
# traces got negative feedback" into two separate questions.
FEEDBACK_SCORE_NAME = "user_thumbs"


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """Milestone 12: thumbs up/down (+ optional comment) as a real Langfuse
    score — Layer 3 of the project's evaluation architecture.

    `message_id` is resolved back to the turn's real `trace_id` via
    `ConversationStore` — the client only ever handles the opaque id
    `POST /chat` already returned it, never the raw trace_id (see
    `ChatResponse.message_id`'s own docstring for why that split exists).

    The score is linked to `trace_id` only, never `session_id` as well.
    Langfuse's ingestion API rejects a score body carrying more than one of
    `traceId`/`sessionId`/`datasetRunId` — confirmed with a real `400`
    ("Provide exactly one of the following...") from a direct
    `/api/public/ingestion` call, after `create_score(trace_id=..., session_id=...)`
    together silently dropped every score in practice (the SDK's own
    `create_score()`/`flush()` never surface this: the batch export runs on
    a background thread and only logs the rejection, it doesn't raise —
    see `docs/EXPERIMENTS.md`, Milestone 12). This isn't a loss of the
    per-session view: the scored trace already carries `session_id` from
    when the turn itself was created (`chat.py`, Milestone 2), so Langfuse's
    UI still surfaces the score when browsing that session — it groups by
    the trace's own session membership, not by a session_id set on the score.

    `score_id` is deterministic (`feedback-<message_id>`) so a comment sent
    after an initial thumbs click updates the same score rather than
    creating a second, disconnected one — matching the same id-based upsert
    convention `create_dataset_item()` uses (Milestone 10), though Langfuse's
    score-level upsert behavior specifically is not independently verified
    here (no read API available in this deployment's "events_only" mode —
    see docs/langfuse.md).
    """
    store = get_conversation_store()
    turn = await store.find_turn(request.session_id, request.message_id)
    if turn is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No turn {request.message_id!r} found in session {request.session_id!r} — "
                "wrong id, or trimmed out by Settings.max_history_turns since it was returned."
            ),
        )

    client = get_langfuse_client()
    client.create_score(
        name=FEEDBACK_SCORE_NAME,
        value=1.0 if request.thumbs_up else 0.0,
        data_type="NUMERIC",
        trace_id=turn.trace_id,
        comment=request.comment,
        score_id=f"feedback-{request.message_id}",
    )

    if get_settings().debug:
        # Same reasoning as chat.py: visible immediately in a short dev
        # session, never a blocking network round trip on the unconditional
        # request path (ADR-004).
        client.flush()

    return FeedbackResponse(recorded=True)
