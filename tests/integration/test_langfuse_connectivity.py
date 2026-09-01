"""Integration tests against whichever real Langfuse target `Settings`
currently points at — local self-hosted by default, but exactly these same
tests, unmodified, are Milestone 19's actual verification mechanism for
Langfuse Cloud too.

`get_langfuse_client()` builds `Langfuse(host=settings.langfuse_host, ...)`
with no branching on the host's value (see observability/langfuse_client.py)
— so proving "the same application can send traces to local or Cloud" is
exactly a matter of running this file against each target and watching it
pass both times, not writing separate Cloud-specific test code (that would
be exactly the "duplicate instrumentation" the spec says not to build).

Excluded from `make test` / `make test-unit` (see the `not integration`
default in pyproject.toml). Run explicitly once a target is up:

    make langfuse-up && make test-integration          # local (default)

Or, having switched `.env`'s three LANGFUSE_* values to a real Cloud
project (see README's "Optional: Langfuse Cloud" / ADR-004):

    make test-integration                              # same command, Cloud this time

Not exercised against real Cloud in this environment — no Cloud account is
configured here, the same "verified structurally, not live" gap every other
"no credential in this environment" limitation in this project already has
(Anthropic, the real LLM judge). `tests/unit/test_langfuse_client.py`'s
`test_construction_does_not_raise_with_a_cloud_shaped_host` covers the part
that *is* verifiable offline: construction itself never depends on which
host is configured.
"""

import pytest

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability.langfuse_client import get_langfuse_client

pytestmark = pytest.mark.integration


def test_auth_check_succeeds_against_the_configured_langfuse_target():
    client = get_langfuse_client()
    assert client.auth_check() is True


def test_can_create_and_flush_a_trace_and_it_lands_at_the_configured_host():
    client = get_langfuse_client()

    with client.start_as_current_observation(name="integration_test_trace") as span:
        trace_id = span.trace_id
        span.update(output={"status": "ok"})

    client.flush()

    trace_url = client.get_trace_url(trace_id=trace_id)
    assert trace_url is not None
    assert trace_id in trace_url
    # The literal point of Milestone 19: the trace really did land at
    # whichever host Settings.langfuse_host currently names — local or
    # Cloud — not just that *some* URL came back.
    assert trace_url.startswith(get_settings().langfuse_host)
