"""Tests for POST /chat.

Uses the default mock LLM provider — no network, no credentials. Where a
test needs a specific Settings value (e.g. `debug`), it clears the
`get_settings`/`get_llm_provider` caches and monkeypatches the env var,
following the pattern established in test_settings.py: env vars always win
over whatever `.env` a developer happens to have on disk.
"""

import pytest
from fastapi.testclient import TestClient

from travel_ai_concierge.api.app import create_app
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import get_llm_provider


def _clear_all_caches() -> None:
    # get_langfuse_client() is its own lru_cache singleton, separate from
    # Settings — without clearing it too, whichever test runs first "freezes"
    # its Langfuse config (host, tracing_enabled) for the rest of the process.
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_langfuse_client.cache_clear()


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
