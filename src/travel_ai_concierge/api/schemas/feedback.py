from pydantic import BaseModel


class FeedbackRequest(BaseModel):
    session_id: str
    # References ChatResponse.message_id / SessionTurn.message_id — never
    # the raw Langfuse trace_id (see conversation/store.py's Turn.turn_id).
    message_id: str
    thumbs_up: bool
    # Attaches to the same thumbs rating rather than standing alone — a
    # comment without a rating doesn't map onto a single Langfuse score
    # (see api/routes/feedback.py).
    comment: str | None = None


class FeedbackResponse(BaseModel):
    recorded: bool = True
