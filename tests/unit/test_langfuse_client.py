"""Tests for the Langfuse client factory.

These are offline by design: constructing a Langfuse client performs no
network I/O (verified empirically — the OTel exporter only talks to the
server on flush/shutdown), so we can assert our own wiring without a live
Langfuse instance. We deliberately do not assert on the SDK's internal
attributes — only on behaviour our own code is responsible for.
"""

from langfuse import Langfuse

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
