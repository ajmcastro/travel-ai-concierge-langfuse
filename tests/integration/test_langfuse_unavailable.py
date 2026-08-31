"""Milestone 15: the single most emphasized resilience claim in the project
spec — "Langfuse unavailable... the application should continue serving
users... observability must not become a hard runtime dependency" (ADR-004)
— verified against a real, if failing, network connection, not just
reasoned about.

Marked `integration` because it makes a real TCP connection attempt (even
though it's expected to fail fast) — but unlike every other file in this
directory, it does NOT need `make langfuse-up` first. The whole point is
testing what happens when Langfuse is *not* there. `LANGFUSE_HOST` is
pointed at `http://localhost:1` — localhost avoids a slow DNS lookup, and
an unopened local port fails with an immediate ECONNREFUSED, so this stays
fast and deterministic without needing a real unreachable external host.

    make test-integration
"""

import time

import pytest
from fastapi.testclient import TestClient

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.api.app import create_app
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.conversation import get_conversation_store
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import get_llm_provider

pytestmark = pytest.mark.integration


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


def test_chat_still_returns_200_quickly_when_langfuse_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:1")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("DEBUG", "false")  # the production path: flush() is never called
    client = TestClient(create_app())

    start = time.monotonic()
    response = client.post("/chat", json={"message": "hello"})
    elapsed_seconds = time.monotonic() - start

    assert response.status_code == 200
    assert response.json()["message"]
    # Generous bound (batch export happens on a background thread and
    # should never block the request at all) — this is checking "did not
    # hang waiting on a dead host," not measuring precise latency.
    assert elapsed_seconds < 2.0
