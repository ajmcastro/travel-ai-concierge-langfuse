"""Tests for POST /feedback (Milestone 12)."""

import pytest
from fastapi.testclient import TestClient

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.api.app import create_app
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.conversation import get_conversation_store
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.prompts import SYSTEM_PROMPT_FALLBACK
from travel_ai_concierge.providers.llm import get_llm_provider


class _StubPrompt:
    # See tests/unit/test_chat_route.py's copy for why this exists — keeps
    # every test in this file off the network (get_system_prompt() would
    # otherwise make a real, blocking Langfuse call on cache miss).
    name = "travel-concierge-system"
    version = 1
    is_fallback = False

    def compile(self, **kwargs: object) -> str:
        return SYSTEM_PROMPT_FALLBACK


class _RecordingLangfuseClient:
    """Records create_score() calls instead of sending them for real —
    verifying the score payload the route builds, not the SDK's own
    network/export behavior. Unlike span creation (M6's InMemorySpanExporter
    tests), a score has no span to inspect that way, so this records the
    call directly instead.
    """

    def __init__(self) -> None:
        self.scores: list[dict] = []

    def create_score(self, **kwargs: object) -> None:
        self.scores.append(kwargs)

    def flush(self) -> None:
        pass


def _clear_all_caches() -> None:
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_langfuse_client.cache_clear()
    get_agent_graph.cache_clear()
    get_conversation_store.cache_clear()


@pytest.fixture(autouse=True)
def _clear_caches():
    _clear_all_caches()
    yield
    _clear_all_caches()


def _client(
    monkeypatch: pytest.MonkeyPatch, recorder: _RecordingLangfuseClient, **env: str
) -> TestClient:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("AGENT_ENABLED", "false")
    monkeypatch.setattr(
        "travel_ai_concierge.api.routes.chat.get_system_prompt", lambda: _StubPrompt()
    )
    # Only the feedback route's own client is swapped — chat.py keeps using
    # the real one, same as every other test file (span creation is local
    # only, no network required, established since Milestone 1).
    monkeypatch.setattr(
        "travel_ai_concierge.api.routes.feedback.get_langfuse_client", lambda: recorder
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TestClient(create_app())


def _chat_and_get_message_id(client: TestClient, session_id: str, message: str = "hello") -> str:
    body = client.post("/chat", json={"message": message, "session_id": session_id}).json()
    return body["message_id"]


def test_thumbs_up_creates_a_numeric_score_linked_to_trace_only(
    monkeypatch: pytest.MonkeyPatch,
):
    recorder = _RecordingLangfuseClient()
    client = _client(monkeypatch, recorder)
    message_id = _chat_and_get_message_id(client, "s1")

    response = client.post(
        "/feedback", json={"session_id": "s1", "message_id": message_id, "thumbs_up": True}
    )

    assert response.status_code == 201
    assert response.json() == {"recorded": True}
    assert len(recorder.scores) == 1
    score = recorder.scores[0]
    assert score["name"] == "user_thumbs"
    assert score["value"] == 1.0
    assert score["data_type"] == "NUMERIC"
    assert score["trace_id"]  # a real trace_id was resolved via the store
    # Regression guard: Langfuse's ingestion API rejects a score carrying
    # both traceId and sessionId ("provide exactly one of...") — confirmed
    # against a real deployment (docs/EXPERIMENTS.md, Milestone 12). The
    # route must never pass session_id to create_score().
    assert "session_id" not in score


def test_thumbs_down_scores_zero(monkeypatch: pytest.MonkeyPatch):
    recorder = _RecordingLangfuseClient()
    client = _client(monkeypatch, recorder)
    message_id = _chat_and_get_message_id(client, "s1")

    client.post(
        "/feedback", json={"session_id": "s1", "message_id": message_id, "thumbs_up": False}
    )

    assert recorder.scores[0]["value"] == 0.0


def test_comment_is_passed_through(monkeypatch: pytest.MonkeyPatch):
    recorder = _RecordingLangfuseClient()
    client = _client(monkeypatch, recorder)
    message_id = _chat_and_get_message_id(client, "s1")

    client.post(
        "/feedback",
        json={
            "session_id": "s1",
            "message_id": message_id,
            "thumbs_up": True,
            "comment": "great!",
        },
    )

    assert recorder.scores[0]["comment"] == "great!"


def test_comment_defaults_to_none(monkeypatch: pytest.MonkeyPatch):
    recorder = _RecordingLangfuseClient()
    client = _client(monkeypatch, recorder)
    message_id = _chat_and_get_message_id(client, "s1")

    client.post("/feedback", json={"session_id": "s1", "message_id": message_id, "thumbs_up": True})

    assert recorder.scores[0]["comment"] is None


def test_unknown_message_id_returns_404_and_records_nothing(monkeypatch: pytest.MonkeyPatch):
    recorder = _RecordingLangfuseClient()
    client = _client(monkeypatch, recorder)
    client.post("/chat", json={"message": "hello", "session_id": "s1"})

    response = client.post(
        "/feedback",
        json={"session_id": "s1", "message_id": "does-not-exist", "thumbs_up": True},
    )

    assert response.status_code == 404
    assert recorder.scores == []


def test_correct_message_id_in_the_wrong_session_returns_404(monkeypatch: pytest.MonkeyPatch):
    recorder = _RecordingLangfuseClient()
    client = _client(monkeypatch, recorder)
    message_id = _chat_and_get_message_id(client, "s1")

    response = client.post(
        "/feedback", json={"session_id": "s2", "message_id": message_id, "thumbs_up": True}
    )

    assert response.status_code == 404


def test_score_id_is_deterministic_per_message_so_a_followup_comment_updates_it(
    monkeypatch: pytest.MonkeyPatch,
):
    recorder = _RecordingLangfuseClient()
    client = _client(monkeypatch, recorder)
    message_id = _chat_and_get_message_id(client, "s1")

    client.post("/feedback", json={"session_id": "s1", "message_id": message_id, "thumbs_up": True})
    client.post(
        "/feedback",
        json={
            "session_id": "s1",
            "message_id": message_id,
            "thumbs_up": True,
            "comment": "nice",
        },
    )

    assert recorder.scores[0]["score_id"] == recorder.scores[1]["score_id"]


def test_trace_id_hidden_from_get_sessions_outside_debug_but_feedback_still_works(
    monkeypatch: pytest.MonkeyPatch,
):
    # The whole point of message_id: feedback must work even when the raw
    # trace_id is never exposed to the client at all.
    recorder = _RecordingLangfuseClient()
    client = _client(monkeypatch, recorder, DEBUG="false")
    body = client.post("/chat", json={"message": "hello", "session_id": "s1"}).json()
    assert body["trace_id"] is None
    message_id = body["message_id"]
    assert message_id

    response = client.post(
        "/feedback", json={"session_id": "s1", "message_id": message_id, "thumbs_up": True}
    )

    assert response.status_code == 201
    assert recorder.scores[0]["trace_id"]  # resolved server-side regardless
