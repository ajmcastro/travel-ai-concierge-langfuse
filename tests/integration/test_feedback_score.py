"""Integration test: real Langfuse score creation (Milestone 12).

Excluded from `make test` (see `not integration` marker filter in
pyproject.toml). Requires a live local Langfuse instance:

    make langfuse-up
    make test-integration

Doesn't (can't, in this environment) read the score back after the fact —
this deployment runs Langfuse v4 "events_only" mode, which disables the
public read API entirely (see docs/langfuse.md). It instead hits Langfuse's
own `/api/public/ingestion` endpoint directly and asserts on the per-item
"errors" array in the response, rather than only calling the SDK's
`create_score()` + `flush()` and checking neither raised.

That distinction matters and was not cosmetic: an earlier version of this
test *did* only check `flush()` didn't raise, using a payload that carried
both `trace_id` and `session_id` on one score — a combination Langfuse's
ingestion API actually rejects with a real `400` ("provide exactly one of
traceId, sessionId or datasetRunId"). `create_score()`'s batch export runs
on a background thread and only *logs* that rejection; it never raises, so
that earlier test passed every time while every score it "verified" was
silently dropped. The bug was only caught by a human clicking thumbs-up in
the live UI and finding nothing in Langfuse — see docs/EXPERIMENTS.md,
Milestone 12. This test now exercises the same raw endpoint the SDK talks
to, so a similar payload-shape regression fails loudly instead of quietly.
"""

import base64

import httpx2
import pytest

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client

pytestmark = pytest.mark.integration


def test_create_score_and_flush_succeeds_against_real_langfuse():
    """Exercises the actual production code path (SDK create_score + flush).
    Passes even if the score is silently rejected server-side — see the
    stronger check below for the test that would actually catch that.
    """
    client = get_langfuse_client()

    with client.start_as_current_observation(name="feedback_integration_test_trace") as span:
        trace_id = span.trace_id

    client.create_score(
        name="user_thumbs",
        value=1.0,
        data_type="NUMERIC",
        trace_id=trace_id,
        comment="integration test comment",
        score_id="feedback-integration-test-score",
    )

    client.flush()


def test_score_matching_the_route_shape_is_accepted_by_the_real_ingestion_api():
    """Calls Langfuse's /api/public/ingestion directly with exactly the score
    shape api/routes/feedback.py sends (trace_id only, no session_id) and
    asserts the response reports zero errors — the one place in this
    environment a rejected score is actually observable synchronously.
    """
    settings = get_settings()
    auth = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    ).decode()

    body = {
        "batch": [
            {
                "id": "feedback-integration-ingestion-check",
                "type": "score-create",
                "timestamp": "2026-01-01T00:00:00Z",
                "body": {
                    "id": "feedback-integration-ingestion-check-score",
                    "traceId": "0123456789abcdef0123456789abcdef",
                    "name": "user_thumbs",
                    "value": 1.0,
                    "dataType": "NUMERIC",
                    "comment": "integration test comment",
                },
            }
        ]
    }

    response = httpx2.post(
        f"{settings.langfuse_host}/api/public/ingestion",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        json=body,
        timeout=10.0,
    )

    assert response.status_code == 207
    assert response.json()["errors"] == []
