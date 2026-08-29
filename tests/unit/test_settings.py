"""Tests for application configuration."""

import pytest

# Each test gets a fresh Settings so lru_cache doesn't leak across tests
from travel_ai_concierge.config.settings import Settings


def test_default_environment():
    s = Settings()
    assert s.environment == "development"


def test_default_langfuse_host():
    s = Settings()
    assert s.langfuse_host == "http://localhost:3000"


def test_default_llm_provider_is_mock():
    s = Settings()
    assert s.llm_provider == "mock"


def test_langfuse_enabled_by_default():
    s = Settings()
    assert s.langfuse_enabled is True


def test_environment_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    s = Settings()
    assert s.environment == "production"


def test_langfuse_host_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    s = Settings()
    assert s.langfuse_host == "https://cloud.langfuse.com"
