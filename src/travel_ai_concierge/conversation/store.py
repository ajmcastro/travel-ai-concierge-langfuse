import asyncio
import uuid
from dataclasses import dataclass, field


@dataclass
class Turn:
    user_message: str
    assistant_message: str
    # None whenever tracing produced no trace (Langfuse disabled) — distinct
    # from the ChatResponse-level gating on Settings.debug, which happens at
    # the API boundary instead (see api/routes/sessions.py).
    trace_id: str | None
    # Milestone 12: an opaque id, always returned to the client (unlike
    # trace_id, never gated on Settings.debug) — feedback references a turn
    # by this, and the server resolves it back to the real trace_id here.
    # Decoupling the two on purpose: a production client should never need
    # to know the raw Langfuse trace_id just to say "I liked this answer."
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)


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

    async def find_turn(self, session_id: str, turn_id: str) -> Turn | None:
        """Look up one turn by its opaque id — used by POST /feedback to
        resolve a client-visible message_id back to the trace_id needed to
        score it. Returns None if the turn was never seen, or has since been
        trimmed out by max_history_turns — a session that's had a lot of
        conversation since the rated turn simply can't be scored anymore,
        an honest, bounded limitation of an in-memory store (see this
        module's own docstring).
        """
        async with self._lock:
            for turn in self._sessions.get(session_id, []):
                if turn.turn_id == turn_id:
                    return turn
            return None

    async def append_turn(self, session_id: str, turn: Turn, max_turns: int) -> None:
        async with self._lock:
            turns = self._sessions.setdefault(session_id, [])
            turns.append(turn)
            if len(turns) > max_turns:
                del turns[: len(turns) - max_turns]
