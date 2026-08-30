"""Tests for GET /sessions/{session_id} (Milestone 7)."""

import pytest
from fastapi.testclient import TestClient

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.api.app import create_app
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.conversation import get_conversation_store
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import get_llm_provider


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


def _client(monkeypatch: pytest.MonkeyPatch, **env: str) -> TestClient:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("AGENT_ENABLED", "false")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return TestClient(create_app())


def test_unknown_session_returns_404(monkeypatch: pytest.MonkeyPatch):
    response = _client(monkeypatch).get("/sessions/never-existed")
    assert response.status_code == 404


def test_session_reflects_chat_turns(monkeypatch: pytest.MonkeyPatch):
    client = _client(monkeypatch)
    client.post("/chat", json={"message": "hello", "session_id": "s1"})
    client.post("/chat", json={"message": "hi again", "session_id": "s1"})

    body = client.get("/sessions/s1").json()
    assert body["session_id"] == "s1"
    assert body["turn_count"] == 2
    assert body["turns"][0]["user_message"] == "hello"
    assert body["turns"][0]["assistant_message"] == "[mock] I heard: hello"
    assert body["turns"][1]["user_message"] == "hi again"


def test_trace_id_hidden_outside_debug_mode(monkeypatch: pytest.MonkeyPatch):
    client = _client(monkeypatch, DEBUG="false", LANGFUSE_ENABLED="false")
    client.post("/chat", json={"message": "hello", "session_id": "s1"})

    body = client.get("/sessions/s1").json()
    assert body["turns"][0]["trace_id"] is None


def test_trace_id_present_in_debug_mode(monkeypatch: pytest.MonkeyPatch):
    client = _client(monkeypatch, DEBUG="true", LANGFUSE_ENABLED="false")
    client.post("/chat", json={"message": "hello", "session_id": "s1"})

    body = client.get("/sessions/s1").json()
    assert body["turns"][0]["trace_id"] is not None


def test_sessions_are_independent(monkeypatch: pytest.MonkeyPatch):
    client = _client(monkeypatch)
    client.post("/chat", json={"message": "for s1", "session_id": "s1"})
    client.post("/chat", json={"message": "for s2", "session_id": "s2"})

    assert client.get("/sessions/s1").json()["turn_count"] == 1
    assert client.get("/sessions/s2").json()["turn_count"] == 1
    assert client.get("/sessions/s1").json()["turns"][0]["user_message"] == "for s1"
