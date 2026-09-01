"""Tests for the Langfuse client factory.

These are offline by design: constructing a Langfuse client performs no
network I/O (verified empirically — the OTel exporter only talks to the
server on flush/shutdown), so we can assert our own wiring without a live
Langfuse instance. We deliberately do not assert on the SDK's internal
attributes — only on behaviour our own code is responsible for.
"""

import pytest
from langfuse import Langfuse

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability.langfuse_client import get_langfuse_client


def test_returns_langfuse_instance():
    client = get_langfuse_client()
    assert isinstance(client, Langfuse)


def test_is_a_singleton():
    first = get_langfuse_client()
    second = get_langfuse_client()
    assert first is second


def test_construction_does_not_raise_without_network():
    # Default settings point at a local host that may not be running in CI —
    # construction must still succeed (no network call happens here).
    get_langfuse_client()


def test_construction_does_not_raise_with_a_cloud_shaped_host(monkeypatch: pytest.MonkeyPatch):
    """Milestone 19: `get_langfuse_client()` has exactly one `host=...` line,
    with no branching on its value (see the function's own source) — this
    pins that claim as a real, offline-verified test rather than something
    only established by reading the code. Deliberately does not assert on
    `client._base_url`/other SDK internals — same "behaviour, not internals"
    principle the rest of this file already states; the *point* is that a
    Cloud-shaped host constructs exactly as uneventfully as a local one.
    """
    monkeypatch.setenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    get_settings.cache_clear()
    get_langfuse_client.cache_clear()
    try:
        client = get_langfuse_client()
        assert isinstance(client, Langfuse)
    finally:
        get_settings.cache_clear()
        get_langfuse_client.cache_clear()
