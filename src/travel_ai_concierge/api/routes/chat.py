import uuid

from fastapi import APIRouter
from langfuse import propagate_attributes

from travel_ai_concierge.api.schemas.chat import ChatRequest, ChatResponse
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import Message, get_llm_provider

router = APIRouter(tags=["chat"])

SYSTEM_PROMPT = (
    "You are a helpful, concise travel concierge. Ask clarifying questions when "
    "important details (destination, dates, budget, travellers) are missing."
)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    settings = get_settings()
    client = get_langfuse_client()
    provider = get_llm_provider()

    session_id = request.session_id or f"session-{uuid.uuid4().hex[:12]}"

    with client.start_as_current_observation(
        name="travel_concierge_turn",
        input={"message": request.message},
    ) as root_span:
        # Capture now — both the span and its trace_id become unreachable
        # once this `with` block exits (see docs/EXPERIMENTS.md, Milestone 1).
        trace_id = root_span.trace_id

        with propagate_attributes(
            session_id=session_id,
            user_id=request.user_id,
            environment=settings.environment,
        ):
            messages = [
                Message(role="system", content=SYSTEM_PROMPT),
                Message(role="user", content=request.message),
            ]
            response = await provider.complete(messages)

        root_span.update(output={"message": response.content})

    if settings.debug:
        # Spans batch and export asynchronously; a request in a short-lived
        # dev session should be visible in the UI right away. Never done on
        # the production path — flush() is a blocking network round trip,
        # exactly the hard dependency ADR-004 says observability must not be.
        client.flush()

    return ChatResponse(
        session_id=session_id,
        message=response.content,
        trace_id=trace_id if settings.debug else None,
        metadata={"model": response.model},
    )
