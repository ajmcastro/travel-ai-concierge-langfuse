"""Tests for the /health endpoint."""

from fastapi.testclient import TestClient

from travel_ai_concierge.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=True)


def test_health_returns_200():
    response = _client().get("/health")
    assert response.status_code == 200


def test_health_body():
    body = _client().get("/health").json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "environment" in body


def test_health_default_environment():
    body = _client().get("/health").json()
    assert body["environment"] == "development"
