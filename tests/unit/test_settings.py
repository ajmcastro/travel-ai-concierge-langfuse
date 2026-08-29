"""Tests for application configuration."""

import pytest

# Each test gets a fresh Settings so lru_cache doesn't leak across tests
from travel_ai_concierge.config.settings import Settings


def _defaults() -> Settings:
    # `Settings()` alone would pick up whatever `.env` happens to exist on the
    # developer's machine (e.g. a locally overridden LANGFUSE_HOST for a port
    # conflict) — these tests assert the hardcoded code defaults specifically,
    # so we disable env_file loading for them.
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_default_environment():
    s = _defaults()
    assert s.environment == "development"


def test_default_langfuse_host():
    s = _defaults()
    assert s.langfuse_host == "http://localhost:3000"


def test_default_llm_provider_is_mock():
    s = _defaults()
    assert s.llm_provider == "mock"


def test_langfuse_enabled_by_default():
    s = _defaults()
    assert s.langfuse_enabled is True


def test_environment_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    s = _defaults()
    assert s.environment == "production"


def test_langfuse_host_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    s = _defaults()
    assert s.langfuse_host == "https://cloud.langfuse.com"
