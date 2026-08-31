# ADR-006: Travel Search Provider Abstraction

**Date:** 2026-08-31
**Status:** Accepted

## Context

The project spec describes a separate, real "Travel AI Search" project and asks this repo to be able to consume it later through an API — but *never* to require it: "The Travel AI Concierge must nevertheless be capable of running independently using synthetic/local travel data." It names the shape directly:

> Later introduce an optional `TravelSearchProvider` with implementations such as `LocalSyntheticTravelSearchProvider` and `TravelAISearchAPIProvider`. The second implementation may call a separately running Travel AI Search API. This demonstrates service composition without creating a hard dependency.

This is the same problem `LLMProvider` (ADR-003) already solved for LLM calls — swap the concrete backend without touching the code that uses it, and let tests run fully offline.

## Options

### Option A — Branch inside `tools/travel_tools.py`

Add an `if Settings.travel_search_provider == "..."` branch directly inside each of the three tool functions.

**Cons:** Every tool function grows a second, unrelated responsibility (deciding *and* fetching). Adding a third backend later means editing three functions again, not adding one file. No natural place to instrument the backend call as its own Langfuse observation, distinct from the tool call itself.

### Option B — A second, parallel set of "API" tool functions

Register `search_hotels_via_api`, etc. as separate tools, and have the agent (or a router) pick which to use.

**Cons:** Doubles `TOOL_SPECS`/`TOOL_REGISTRY` for no reason the LLM should ever need to know about — which backend serves a search is an infrastructure decision, not something the model should be reasoning about. Exactly the kind of complexity ADR-003 already rejected for LLM providers (Option B there: "switching providers requires touching every call site").

### Option C — Protocol-based thin abstraction, mirroring `LLMProvider` exactly

```python
class TravelSearchProvider(Protocol):
    def search_destinations(self, tags=None, climate=None, limit=5) -> list[Destination]: ...
    def search_hotels(self, destination_id, family_friendly=None, max_price_band=None, limit=5) -> list[Hotel]: ...
    def get_destination_information(self, destination_id) -> Destination | None: ...
```

`tools/travel_tools.py`'s three functions become thin: open the Langfuse `tool` span (unchanged since Milestone 4), delegate to `get_travel_search_provider()`, record the result count. `TOOL_SPECS`/`TOOL_REGISTRY`/`agent/nodes.py` need zero changes.

**Pros:**
- `LocalSyntheticTravelSearchProvider` is always available, zero external services — the spec's own independence requirement, satisfied structurally, not by convention.
- `TravelAISearchAPIProvider` can be added, tested, and swapped in with a single `Settings.travel_search_provider` change.
- Each concrete provider opens its own `travel_search_backend` observation, nested inside the tool span — giving the spec's own requested trace shape (`search tool -> Travel AI Search API -> results -> agent`) and a real, isolated latency signal for the search backend, independent of LLM latency, for free from the span's own duration.

## Decision

**Protocol-based thin abstraction (Option C)**, deliberately synchronous — not `async def` like `LLMProvider`. `agent/nodes.py`'s `tools_node` calls every `TOOL_REGISTRY` entry synchronously (`func(**call.arguments)`, never awaited), a convention every tool and every milestone since M4 depends on. Making this Protocol async would mean making the whole tool-execution path async too — a much larger, riskier change than a search-provider swap needs. `TravelAISearchAPIProvider` uses `httpx2`'s synchronous `Client`-free `httpx2.get(...)` calls (module-level, matching the one other real outbound HTTP call site in this repo, `ui/streamlit_app.py`'s `httpx2.post(...)`), not `AsyncClient`.

## Consequences

- `src/travel_ai_concierge/providers/travel_search/` — `base.py` (Protocol), `local.py` (`LocalSyntheticTravelSearchProvider`, wraps this project's own `data/synthetic/*.json`), `api.py` (`TravelAISearchAPIProvider`, calls the separate Travel AI Search backend over HTTP), `data.py` (the JSON loader, moved here from `tools/data.py` — see the "circular import" note below), `__init__.py` (`get_travel_search_provider()`, `lru_cache`'d, selects from `Settings.travel_search_provider`, default `"local"`).
- `Settings` gains `travel_search_provider` (`"local"` | `"travel_ai_search_api"`), `travel_ai_search_base_url`, `travel_ai_search_timeout_seconds`, `travel_ai_search_api_key` — never hardcoded, same convention as every other provider config in this project.
- **The HTTP contract `TravelAISearchAPIProvider` assumes is designed, not confirmed** — this repo has no access to the real Travel AI Search project. Response bodies are validated against this project's own `Destination`/`Hotel` models; a real deployment with a different shape would raise a clear validation error, not silently accept malformed data. Pinned end-to-end by `tests/integration/test_travel_ai_search_provider.py` against a real (if local, self-hosted-for-the-test) HTTP server implementing exactly this assumed contract — not skip-by-default like `test_anthropic_provider.py`, since no paid credential is needed, only a loopback socket.
- **A genuine import cycle, found while wiring this up, not anticipated in advance**: `tools/travel_tools.py` needs to import `providers.travel_search` to get `get_travel_search_provider()`; `providers/travel_search/local.py` needs the JSON loader that used to live at `tools/data.py`; but importing anything from the `tools` package first runs `tools/__init__.py`, which eagerly imports `travel_tools.py` — a real cycle, not a hypothetical one (caught by running the tests, not by reasoning about the import graph beforehand). Fixed by moving the loader to `providers/travel_search/data.py`, which is also the more honest home for it now: loading the local synthetic dataset is a concern of the *local search provider*, not of the tool-wrapping layer above it.
- On a backend failure (a real HTTP error or a connection failure from `TravelAISearchAPIProvider`), the exception propagates up unhandled — `tools_node`'s existing per-call `try/except` (Milestone 6) already turns it into a graceful error message the agent's next turn can react to, the same recovery path Milestone 15's `tool_exception` fault already exercises. No new error-handling code was needed for this — closing the loop Milestone 15's own RATIONALE entry left open ("'Travel provider error' has no real second provider to demonstrate a fallback *to*... that specific spec example isn't fully exercisable here yet").
- No automatic fallback from `travel_ai_search_api` back to `local` on failure — the spec asks for "service composition without creating a hard dependency" (the app must still run on `local` alone), not automatic failover between the two once a request is already in flight, which would need a policy for partial results and retry semantics the spec never asks for. Deliberately out of scope, not an oversight.
