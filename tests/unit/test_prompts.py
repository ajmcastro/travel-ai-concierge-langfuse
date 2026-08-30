"""Tests for Milestone 8's Langfuse Prompt Management wiring.

Fully offline: points a *real* (non-mocked) Langfuse client at
`http://localhost:1` — a port that refuses connections instantly, no timeout
wait — with `max_retries=0`, so the real SDK fallback/retry code actually
runs, fast and deterministically, without needing `make langfuse-up`. Same
"verify against the real SDK, not a hand-rolled fake" discipline as
tests/unit/test_trace_design.py (Milestone 6).
"""

import pytest
from langfuse import Langfuse
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.prompts import (
    SYSTEM_PROMPT_FALLBACK,
    SYSTEM_PROMPT_NAME,
    get_system_prompt,
)


class _FastFailLangfuse(Langfuse):
    """`get_prompt()` retries (exponential backoff) by default even when the
    underlying failure — connection refused — is instant; three tests
    calling the real SDK's `max_retries=2` default cost ~2.9s total,
    measured (`pytest --durations`). `get_system_prompt()` deliberately
    doesn't expose retry tuning in production (real resilience should retry),
    so this test-only subclass forces fast failure instead of changing that.
    """

    def get_prompt(self, name: str, **kwargs: object):  # type: ignore[override]
        kwargs.setdefault("max_retries", 0)
        kwargs.setdefault("fetch_timeout_seconds", 1)
        return super().get_prompt(name, **kwargs)


def _unreachable_client(public_key: str, **kwargs) -> Langfuse:
    # tracing_enabled=True: span *creation*/export is local-only and doesn't
    # depend on the host being reachable (batched/async, same reasoning as
    # every other test in this project) — only `get_prompt()` actually hits
    # the network synchronously, and localhost:1 makes that fail instantly
    # (connection refused) once retries are forced off, above.
    return _FastFailLangfuse(
        public_key=public_key,
        secret_key="sk-test",
        host="http://localhost:1",
        tracing_enabled=True,
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _clear_caches():
    get_settings.cache_clear()
    get_langfuse_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_langfuse_client.cache_clear()


def test_unreachable_langfuse_falls_back_to_local_prompt(monkeypatch: pytest.MonkeyPatch):
    client = _unreachable_client("pk-test-prompt-fallback")
    monkeypatch.setattr("travel_ai_concierge.prompts.get_langfuse_client", lambda: client)

    prompt = get_system_prompt()

    assert prompt.is_fallback is True
    assert prompt.compile() == SYSTEM_PROMPT_FALLBACK
    assert prompt.name == SYSTEM_PROMPT_NAME


def test_prompt_label_setting_is_used_even_in_fallback(monkeypatch: pytest.MonkeyPatch):
    # The fallback PromptClient still carries the *requested* label — proof
    # that Settings.prompt_label actually reaches the SDK call, not just
    # that some fallback object comes back.
    client = _unreachable_client("pk-test-prompt-label")
    monkeypatch.setattr("travel_ai_concierge.prompts.get_langfuse_client", lambda: client)
    monkeypatch.setenv("PROMPT_LABEL", "staging")
    get_settings.cache_clear()

    prompt = get_system_prompt()

    assert prompt.labels == ["staging"]


def test_default_label_is_production():
    assert get_settings().prompt_label == "production"


def _generation_attrs_after_propagating(
    exporter: InMemorySpanExporter, client: Langfuse, prompt
) -> dict:
    from langfuse import propagate_attributes

    with client.start_as_current_observation(name="root") as root:
        with (
            propagate_attributes(prompt=prompt),
            client.start_as_current_observation(
                name="llm_call", as_type="generation", model="mock"
            ) as gen,
        ):
            gen.update(output="ok")
        root.update(output="done")

    client.flush()
    spans = {s.name: dict(s.attributes) for s in exporter.get_finished_spans()}
    return spans["llm_call"]


def test_fallback_prompt_is_never_linked_to_a_generation(monkeypatch: pytest.MonkeyPatch):
    # Verified against the SDK's own propagation source (_extract_propagated_prompt):
    # "Fallback prompts are never linked" is a deliberate rule, not an
    # omission — linking a generation to "version 0" of a prompt that was
    # never actually served would misrepresent what happened. This matters
    # for us directly: when Langfuse is unreachable, chat.py's own
    # `propagate_attributes(prompt=prompt)` call silently produces no link
    # for that turn — expected, not a bug, but worth pinning explicitly.
    exporter = InMemorySpanExporter()
    client = _unreachable_client("pk-test-prompt-no-link", span_exporter=exporter)
    monkeypatch.setattr("travel_ai_concierge.prompts.get_langfuse_client", lambda: client)
    prompt = get_system_prompt()
    assert prompt.is_fallback is True  # sanity: this test is exercising the fallback path

    generation_attrs = _generation_attrs_after_propagating(exporter, client, prompt)

    assert "langfuse.observation.prompt.name" not in generation_attrs


def test_a_real_fetched_prompt_would_be_linked_to_its_generation():
    # propagate_attributes(prompt=...) also accepts a plain Mapping with
    # name/version (per its own docstring) — using one here stands in for a
    # genuinely-fetched, non-fallback PromptClient (is_fallback defaults to
    # False for a plain dict) without needing a live Langfuse instance to
    # fetch a real one from.
    exporter = InMemorySpanExporter()
    client = _unreachable_client("pk-test-prompt-real-link", span_exporter=exporter)

    generation_attrs = _generation_attrs_after_propagating(
        exporter, client, {"name": SYSTEM_PROMPT_NAME, "version": 3}
    )

    assert generation_attrs["langfuse.observation.prompt.name"] == SYSTEM_PROMPT_NAME
    assert generation_attrs["langfuse.observation.prompt.version"] == 3
