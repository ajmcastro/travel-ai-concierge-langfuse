import asyncio
from dataclasses import dataclass


@dataclass
class Turn:
    user_message: str
    assistant_message: str
    # None whenever tracing produced no trace (Langfuse disabled) — distinct
    # from the ChatResponse-level gating on Settings.debug, which happens at
    # the API boundary instead (see api/routes/sessions.py).
    trace_id: str | None


class ConversationStore:
    """In-process, in-memory conversational state, keyed by session_id.

    "Semi-durable" per Milestone 7's own wording: durable enough to give the
    agent real multi-turn memory across requests within one running process,
    but gone on restart. A real production system would back this with
    Redis/Postgres so state survives restarts and is shared across worker
    processes — deliberately not built here, since nothing else in this
    project needs a database, and Langfuse itself already durably stores the
    full per-session trace history for after-the-fact analysis regardless of
    what this store remembers.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, list[Turn]] = {}
        self._lock = asyncio.Lock()

    async def get_history(self, session_id: str) -> list[Turn]:
        async with self._lock:
            return list(self._sessions.get(session_id, []))

    async def append_turn(self, session_id: str, turn: Turn, max_turns: int) -> None:
        async with self._lock:
            turns = self._sessions.setdefault(session_id, [])
            turns.append(turn)
            if len(turns) > max_turns:
                del turns[: len(turns) - max_turns]
