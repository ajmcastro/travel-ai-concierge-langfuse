"""Milestone 18: a real HTTP round trip against a fake Travel AI Search
server — the "Integration tests... Travel AI Search provider" subject the
project spec's own testing-strategy section names.

Unlike test_anthropic_provider.py, this does NOT skip by default: it needs
no paid credential or externally-hosted service, only a loopback HTTP
server this file starts and stops itself (`http.server.ThreadingHTTPServer`
on an OS-assigned free port). That's real, if local, network I/O — the same
"real, not mocked" bar test_langfuse_connectivity.py holds itself to — so it
belongs here in tests/integration/, not tests/unit/, even though it needs
`make langfuse-up` no more than test_langfuse_unavailable.py does.

The server implements this project's own *assumed* contract for the
separate Travel AI Search project (see providers/travel_search/api.py's
module docstring) — unverified against a real deployment of that project,
since this repo has no access to it, but pinned end-to-end here rather than
left as an assumption nobody ever exercised.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from travel_ai_concierge.agent import get_agent_graph
from travel_ai_concierge.config import get_settings
from travel_ai_concierge.conversation import get_conversation_store
from travel_ai_concierge.observability import get_langfuse_client
from travel_ai_concierge.providers.llm import Message, get_llm_provider
from travel_ai_concierge.providers.travel_search import get_travel_search_provider
from travel_ai_concierge.providers.travel_search.api import TravelAISearchAPIProvider
from travel_ai_concierge.providers.travel_search.data import get_destinations, get_hotels
from travel_ai_concierge.providers.travel_search.local import LocalSyntheticTravelSearchProvider

pytestmark = pytest.mark.integration


class _FakeTravelAISearchHandler(BaseHTTPRequestHandler):
    # Quiet by default — BaseHTTPRequestHandler logs every request to
    # stderr otherwise, noisy for a passing test run.
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def _send_json(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler's own naming
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/destinations":
            tags = query.get("tags")
            climate = query.get("climate", [None])[0]
            limit = int(query.get("limit", ["5"])[0])
            results = get_destinations()
            if climate is not None:
                results = [d for d in results if d.climate == climate]
            if tags:
                wanted = set(tags)
                results = [d for d in results if wanted & set(d.tags)]
            self._send_json(200, [d.model_dump() for d in results[:limit]])
            return

        if parsed.path == "/hotels":
            destination_id = query.get("destination_id", [None])[0]
            family_friendly = query.get("family_friendly", [None])[0]
            max_price_band = query.get("max_price_band", [None])[0]
            limit = int(query.get("limit", ["5"])[0])
            results = [h for h in get_hotels() if h.destination_id == destination_id]
            if family_friendly is not None:
                want = family_friendly.lower() == "true"
                results = [h for h in results if h.family_friendly == want]
            if max_price_band is not None:
                order = {"budget": 0, "mid": 1, "luxury": 2}
                results = [h for h in results if order[h.price_band] <= order[max_price_band]]
            self._send_json(200, [h.model_dump() for h in results[:limit]])
            return

        if parsed.path.startswith("/destinations/"):
            destination_id = parsed.path.removeprefix("/destinations/")
            match = next((d for d in get_destinations() if d.id == destination_id), None)
            if match is None:
                self._send_json(404, {"error": "not found"})
            else:
                self._send_json(200, match.model_dump())
            return

        self._send_json(404, {"error": "no such route"})


@pytest.fixture
def fake_travel_ai_search_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeTravelAISearchHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def _clear_all_caches() -> None:
    get_settings.cache_clear()
    get_llm_provider.cache_clear()
    get_langfuse_client.cache_clear()
    get_agent_graph.cache_clear()
    get_conversation_store.cache_clear()
    get_travel_search_provider.cache_clear()


@pytest.fixture(autouse=True)
def _clear_caches():
    _clear_all_caches()
    yield
    _clear_all_caches()


def test_search_destinations_matches_the_local_provider(fake_travel_ai_search_server: str):
    api_provider = TravelAISearchAPIProvider(base_url=fake_travel_ai_search_server, timeout=5.0)
    local_provider = LocalSyntheticTravelSearchProvider()

    api_results = api_provider.search_destinations(tags=["beach"])
    local_results = local_provider.search_destinations(tags=["beach"])

    assert {d.id for d in api_results} == {d.id for d in local_results}
    assert api_results == local_results


def test_search_hotels_matches_the_local_provider(fake_travel_ai_search_server: str):
    api_provider = TravelAISearchAPIProvider(base_url=fake_travel_ai_search_server, timeout=5.0)
    local_provider = LocalSyntheticTravelSearchProvider()

    api_results = api_provider.search_hotels("algarve", family_friendly=True)
    local_results = local_provider.search_hotels("algarve", family_friendly=True)

    assert {h.id for h in api_results} == {h.id for h in local_results}
    assert api_results == local_results


def test_get_destination_information_found_and_not_found(fake_travel_ai_search_server: str):
    provider = TravelAISearchAPIProvider(base_url=fake_travel_ai_search_server, timeout=5.0)

    found = provider.get_destination_information("kyoto")
    assert found is not None
    assert found.name == "Kyoto"

    assert provider.get_destination_information("atlantis") is None


async def test_full_agent_turn_uses_the_real_api_backend_end_to_end(
    monkeypatch: pytest.MonkeyPatch, fake_travel_ai_search_server: str
):
    """The spec's own diagram, run for real: Concierge agent -> search tool
    -> Travel AI Search API -> results -> agent — with a real HTTP call in
    the middle, not a mock standing in for one.
    """
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("TRAVEL_SEARCH_PROVIDER", "travel_ai_search_api")
    monkeypatch.setenv("TRAVEL_AI_SEARCH_BASE_URL", fake_travel_ai_search_server)
    _clear_all_caches()

    graph = get_agent_graph()
    result = await graph.ainvoke(
        {
            "messages": [
                Message(role="system", content="You are a travel concierge."),
                Message(role="user", content="find me a hotel"),
            ],
            "iterations": 0,
        }
    )

    final_message = result["messages"][-1]
    assert final_message.role == "assistant"
    assert final_message.content
    # A real tool round-trip happened, not a direct answer with no tool call.
    assert any(m.role == "tool" for m in result["messages"])
