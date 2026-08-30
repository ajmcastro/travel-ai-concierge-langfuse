"""Tests for POST /chat.

Uses the default mock LLM provider — no network, no credentials. Where a
test needs a specific Settings value (e.g. `debug`), it clears the
`get_settings`/`get_llm_provider` caches and monkeypatches the env var,
following the pattern established in test_settings.py: env vars always win
over whatever `.env` a developer happens to have on disk.
"""

import pytest
from fastapi.testclient import TestClient

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.api.app import create_app
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.conversation import get_conversation_store
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import get_llm_provider


def _clear_all_caches() -> None:
    # Each of these is its own lru_cache singleton, separate from Settings —
    # without clearing all of them, whichever test runs first "freezes" its
    # config (Langfuse host/tracing, provider, compiled graph) for the rest
    # of the process. get_conversation_store (Milestone 7) is additionally
    # *stateful*, not just cached config — without clearing it, a session_id
    # reused across two tests would carry real conversation history between
    # them.
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


def _client(monkeypatch: pytest.MonkeyPatch, **env: str) -> TestClient:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TestClient(create_app())


def test_chat_returns_200(monkeypatch: pytest.MonkeyPatch):
    response = _client(monkeypatch).post("/chat", json={"message": "hello"})
    assert response.status_code == 200


def test_chat_response_shape(monkeypatch: pytest.MonkeyPatch):
    body = _client(monkeypatch).post("/chat", json={"message": "hello"}).json()

    assert "session_id" in body
    assert "message" in body
    assert "metadata" in body
    assert body["metadata"]["model"] == "mock-echo-v1"


def test_chat_generates_session_id_when_absent(monkeypatch: pytest.MonkeyPatch):
    body = _client(monkeypatch).post("/chat", json={"message": "hello"}).json()
    assert body["session_id"].startswith("session-")


def test_chat_reuses_provided_session_id(monkeypatch: pytest.MonkeyPatch):
    body = (
        _client(monkeypatch)
        .post("/chat", json={"message": "hello", "session_id": "my-session"})
        .json()
    )
    assert body["session_id"] == "my-session"


def test_chat_rejects_empty_message(monkeypatch: pytest.MonkeyPatch):
    response = _client(monkeypatch).post("/chat", json={"message": ""})
    assert response.status_code == 422


def test_trace_id_present_in_debug_mode(monkeypatch: pytest.MonkeyPatch):
    # LANGFUSE_ENABLED=false keeps flush() a local no-op — no network needed
    # even though debug=True triggers it (verified empirically, Milestone 2).
    body = (
        _client(monkeypatch, DEBUG="true", LANGFUSE_ENABLED="false")
        .post("/chat", json={"message": "hello"})
        .json()
    )
    assert body["trace_id"] is not None
    assert len(body["trace_id"]) > 0


def test_trace_id_absent_outside_debug_mode(monkeypatch: pytest.MonkeyPatch):
    body = (
        _client(monkeypatch, DEBUG="false", LANGFUSE_ENABLED="false")
        .post("/chat", json={"message": "hello"})
        .json()
    )
    assert body["trace_id"] is None


def test_agent_enabled_by_default_uses_tools(monkeypatch: pytest.MonkeyPatch):
    # A message MockProvider's trigger heuristic recognizes — with the agent
    # graph (the default), this should round-trip through a real tool call.
    body = _client(monkeypatch).post("/chat", json={"message": "find me a hotel"}).json()
    assert "tool result" in body["message"].lower()


def test_agent_disabled_bypasses_tools_entirely(monkeypatch: pytest.MonkeyPatch):
    # Same message, but with the Milestone 2 direct-call path restored — no
    # graph, no tools offered, so MockProvider falls straight to its plain
    # echo regardless of what the message says. This is the exact one-line
    # comparison Milestone 5 asks for (simple chatbot vs. tool-using agent).
    body = (
        _client(monkeypatch, AGENT_ENABLED="false")
        .post("/chat", json={"message": "find me a hotel"})
        .json()
    )
    assert body["message"] == "[mock] I heard: find me a hotel"


class RecordingProvider:
    """Records every `messages` list it's called with, so a test can assert
    on how much history was actually replayed — MockProvider's own reply
    text only ever echoes the latest message, which can't prove history grew.
    """

    model = "recording"

    def __init__(self) -> None:
        self.calls: list[list] = []

    async def complete(self, messages, tools=None):
        from travel_ai_concierge.providers.llm.base import LLMResponse, Usage

        self.calls.append(messages)
        return LLMResponse(
            content=f"msg_count={len(messages)}",
            model=self.model,
            usage=Usage(input_tokens=1, output_tokens=1),
        )


def test_second_turn_in_same_session_includes_first_turns_history(
    monkeypatch: pytest.MonkeyPatch,
):
    provider = RecordingProvider()
    monkeypatch.setattr("travel_ai_concierge.api.routes.chat.get_llm_provider", lambda: provider)
    client = _client(monkeypatch, AGENT_ENABLED="false")

    first = client.post("/chat", json={"message": "hello", "session_id": "s1"}).json()
    second = client.post("/chat", json={"message": "hi again", "session_id": "s1"}).json()

    # Turn 1: [system, user]. Turn 2: [system, user1, assistant1, user2] —
    # the prior exchange was genuinely replayed, not dropped.
    assert first["message"] == "msg_count=2"
    assert second["message"] == "msg_count=4"


def test_sessions_do_not_share_history(monkeypatch: pytest.MonkeyPatch):
    provider = RecordingProvider()
    monkeypatch.setattr("travel_ai_concierge.api.routes.chat.get_llm_provider", lambda: provider)
    client = _client(monkeypatch, AGENT_ENABLED="false")

    client.post("/chat", json={"message": "hello", "session_id": "s1"})
    other_session = client.post("/chat", json={"message": "hello", "session_id": "s2"}).json()

    assert other_session["message"] == "msg_count=2"


def test_history_is_trimmed_to_max_history_turns(monkeypatch: pytest.MonkeyPatch):
    provider = RecordingProvider()
    monkeypatch.setattr("travel_ai_concierge.api.routes.chat.get_llm_provider", lambda: provider)
    client = _client(monkeypatch, AGENT_ENABLED="false", MAX_HISTORY_TURNS="1")

    client.post("/chat", json={"message": "turn 1", "session_id": "s1"})
    client.post("/chat", json={"message": "turn 2", "session_id": "s1"})
    third = client.post("/chat", json={"message": "turn 3", "session_id": "s1"}).json()

    # Only the single most recent prior turn survives: [system, user2,
    # assistant2, user3] — turn 1 was trimmed out, not accumulated forever.
    assert third["message"] == "msg_count=4"


def test_failed_turn_is_not_remembered(monkeypatch: pytest.MonkeyPatch):
    class FlakyThenFineProvider:
        model = "flaky"
        calls = 0

        async def complete(self, messages, tools=None):
            from travel_ai_concierge.providers.llm.base import LLMResponse, Usage

            FlakyThenFineProvider.calls += 1
            if FlakyThenFineProvider.calls == 1:
                raise RuntimeError("boom")
            return LLMResponse(
                content=f"msg_count={len(messages)}",
                model=self.model,
                usage=Usage(input_tokens=1, output_tokens=1),
            )

    monkeypatch.setattr(
        "travel_ai_concierge.api.routes.chat.get_llm_provider", lambda: FlakyThenFineProvider()
    )
    client = _client(monkeypatch, AGENT_ENABLED="false")

    with pytest.raises(RuntimeError):
        client.post("/chat", json={"message": "will fail", "session_id": "s1"})

    second = client.post("/chat", json={"message": "hello", "session_id": "s1"}).json()
    # Still [system, user] — the failed first attempt left no trace in history.
    assert second["message"] == "msg_count=2"
