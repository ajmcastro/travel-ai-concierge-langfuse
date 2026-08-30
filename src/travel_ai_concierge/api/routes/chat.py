import uuid

from fastapi import APIRouter
from langfuse import propagate_attributes

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.api.schemas.chat import ChatRequest, ChatResponse
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.conversation import Turn, get_conversation_store
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import Message, get_llm_provider

router = APIRouter(tags=["chat"])

SYSTEM_PROMPT = (
    "You are a helpful, concise travel concierge. Ask clarifying questions when "
    "important details (destination, dates, budget, travellers) are missing. Use "
    "the available tools to look up real destination and hotel information rather "
    "than guessing."
)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    settings = get_settings()
    client = get_langfuse_client()
    provider = get_llm_provider()
    store = get_conversation_store()

    session_id = request.session_id or f"session-{uuid.uuid4().hex[:12]}"
    history = await store.get_history(session_id)

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
            # Milestone 6: `agent_enabled` is the one feature flag this app
            # has today, and it changes trace *shape* (agent loop vs. direct
            # call) — worth a tag you can filter by in the UI, not just a
            # metadata field you'd have to open each trace to see.
            tags=[
                "agent" if settings.agent_enabled else "direct-llm",
                f"provider:{settings.llm_provider}",
            ],
            metadata={
                "agent_enabled": settings.agent_enabled,
                "llm_provider": settings.llm_provider,
                # Milestone 7: a direct, cheap answer to "did context size
                # grow excessively" — filterable/sortable per trace without
                # opening it, independent of Langfuse's own token counts.
                "history_turns": len(history),
            },
            # Only the agent path has an agent version to report; the direct
            # path (AGENT_ENABLED=false) isn't running agent code at all.
            version=settings.agent_version if settings.agent_enabled else None,
        ):
            messages = [Message(role="system", content=SYSTEM_PROMPT)]
            for turn in history:
                messages.append(Message(role="user", content=turn.user_message))
                messages.append(Message(role="assistant", content=turn.assistant_message))
            messages.append(Message(role="user", content=request.message))

            try:
                if settings.agent_enabled:
                    # Milestone 5: the LangGraph agent/tools loop. Flip
                    # AGENT_ENABLED=false to compare against the Milestone 2
                    # direct-call trace shape on the same endpoint, same
                    # provider.
                    graph = get_agent_graph()
                    result = await graph.ainvoke({"messages": messages, "iterations": 0})
                    final_message = result["messages"][-1]
                    content = final_message.content
                else:
                    response = await provider.complete(messages)
                    content = response.content
            except Exception as exc:
                # Milestone 6: record error metadata on the trace explicitly
                # rather than letting it surface only as an opaque 500 — a
                # real production trace should say *why* a turn failed, not
                # just that it did. Re-raised unchanged: FastAPI's default
                # exception handling still returns 500 to the caller.
                root_span.update(level="ERROR", status_message=str(exc))
                raise

        root_span.update(output={"message": content})

    # Only reached on success — a turn that raised never gets remembered,
    # so a failed exchange can't poison every subsequent turn's context.
    await store.append_turn(
        session_id,
        Turn(user_message=request.message, assistant_message=content, trace_id=trace_id),
        max_turns=settings.max_history_turns,
    )

    if settings.debug:
        # Spans batch and export asynchronously; a request in a short-lived
        # dev session should be visible in the UI right away. Never done on
        # the production path — flush() is a blocking network round trip,
        # exactly the hard dependency ADR-004 says observability must not be.
        client.flush()

    return ChatResponse(
        session_id=session_id,
        message=content,
        trace_id=trace_id if settings.debug else None,
        metadata={"model": provider.model},
    )
