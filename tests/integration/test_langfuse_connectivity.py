"""Integration tests against a live local Langfuse instance.

Excluded from `make test` / `make test-unit` (see the `not integration`
default in pyproject.toml). Run explicitly once the stack is up:

    make langfuse-up
    make test-integration
"""

import pytest

from travel_ai_concierge.observability.langfuse_client import get_langfuse_client

pytestmark = pytest.mark.integration


def test_auth_check_succeeds_against_local_langfuse():
    client = get_langfuse_client()
    assert client.auth_check() is True


def test_can_create_and_flush_a_trace():
    client = get_langfuse_client()

    with client.start_as_current_observation(name="integration_test_trace") as span:
        trace_id = span.trace_id
        span.update(output={"status": "ok"})

    client.flush()

    trace_url = client.get_trace_url(trace_id=trace_id)
    assert trace_url is not None
    assert trace_id in trace_url
