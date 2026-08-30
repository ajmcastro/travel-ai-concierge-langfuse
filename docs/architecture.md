# Architecture — Travel AI Concierge

> Last updated: Milestone 5  
> This document evolves with the project. Each milestone adds to it.

## Overview

The Travel AI Concierge is an agentic AI application with comprehensive LLM observability via Langfuse. Its primary purpose is to demonstrate production-quality AI engineering practices using a realistic travel domain as the workload.

As of Milestone 5, everything in the diagram below is real **except** the OpenAI provider and `build_itinerary` tool (shown for scale — future, unimplemented) and the Travel AI Search API integration (Milestone 18, optional). The Chat UI calls `POST /chat` over HTTP, which runs the LangGraph agent by default (`Settings.agent_enabled`, default `True`) — the agent decides whether to answer directly or call a tool, executes it if so, and loops back until it has a final answer. See the [Trace Structure](#trace-structure) section for what a real request actually produces, and [Milestone Status](#milestone-status) for what's implemented per milestone.

```
┌─────────────────────────────────────────────────────────────┐
│                        Chat UI (Streamlit)                  │
│         user messages · session continuity · debug panel    │
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTP
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI (port 8000)                      │
│       POST /chat · GET /health · POST /feedback             │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                  Travel AI Concierge Agent                  │
│               (LangGraph: agent ↔ tools loop)               │
│                                                             │
│             agent ──tool call──▶ execute_tools              │
│                 ▲                         │                 │
│                 └─────────────────────────┘                 │
│                 no tool call ▶ final answer                 │
└─────┬───────────────────────────────────┬───────────────────┘
      │                                   │
      ▼                                   ▼
┌──────────────┐                 ┌────────────────────┐
│  LLM Provider│                 │   Travel Tools     │
│   (Protocol) │                 │                    │
│              │                 │ search_destinations│
│ Anthropic    │                 │ search_hotels      │
│ OpenAI       │                 │ get_destination    │
│ Mock         │                 │ build_itinerary    │
└──────────────┘                 └──────────┬─────────┘
                                            │
                              ┌─────────────┴──────────────┐
                              │                            │
                    ┌─────────▼──────────┐  ┌─────────────▼──────┐
                    │ Synthetic Travel   │  │  Travel AI Search  │
                    │ Provider (local)   │  │  API (optional,    │
                    │                   │  │  Milestone 18)     │
                    └───────────────────┘  └────────────────────┘

Instrumentation (all components above emit to Langfuse):

┌─────────────────────────────────────────────────────────────┐
│                          Langfuse                           │
│                                                             │
│  traces · spans · generations · sessions · users            │
│  prompts · datasets · experiments · scores · evaluations    │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### Chat UI ✅ Implemented (M3)

Streamlit app (`ui/streamlit_app.py`), a separate process that talks to FastAPI exclusively over HTTP — it never imports agent/provider code. Responsible for:
- Multi-turn transcript display (client-side history; the backend itself is still stateless per request — see [Milestone 7](#milestone-status))
- Session continuity (`session_id` persisted per browser session) and reset ("New conversation")
- A stable, synthetic `user_id` per browser session (not per message)
- Debug panel: session/user ID, model, client-measured latency, and a link to the trace in Langfuse
- Feedback placeholders (`st.feedback`) — visible, but not yet sent to Langfuse (Milestone 12)
- Clean error display when the API is unreachable or returns an error, and when the debug panel's Langfuse trace-link lookup fails (unreachable host, bad credentials, timeout — caught broadly since this is a non-critical convenience, not the core chat feature)

### FastAPI ✅ Implemented (M0, M2, M5)

The HTTP boundary. Accepts chat requests, manages session IDs, and returns responses. Does not contain agent logic itself — it delegates. Responsible for:
- Validating request schemas (Pydantic) — `api/schemas/chat.py`
- Opening the root Langfuse trace per request and setting session/user/environment attribution — `api/routes/chat.py`
- Delegating to the agent graph by default (`Settings.agent_enabled`, M5), or the LLM provider directly when `agent_enabled=False` (the M2 shape, kept as a live comparison point rather than deleted)
- Returning trace IDs, but only when `Settings.debug` is true

### Travel AI Concierge Agent ✅ Implemented (M5)

A hand-written LangGraph graph (`agent/graph.py`) — no `langgraph.prebuilt` agent, per [ADR-001](decisions/ADR-001-agent-framework.md). Two nodes:
- **`agent`** (`agent/nodes.py`) — one LLM call with the travel tools offered. Opens a real Langfuse **`agent`** observation (a distinct type, like `tool` in M4). If the model requests a tool, routes to `tools`; otherwise the graph ends.
- **`tools`** — executes every tool call the last `agent` message requested, wrapped in one `execute_tools` span so multiple calls in one turn nest together; each individual call is still its own `tool` observation underneath (M4, unchanged).

Two independent safeguards against an unbounded loop (`Settings.agent_max_iterations`, default 5): the `agent` node withholds tools once about to make the last allowed call (so a well-behaved provider produces a clean final answer, not an empty-content dead end), and routing separately hard-stops regardless of the last message's content (so a provider that ignores having no tools still can't loop forever). See [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-5--explicit-agentic-ai-workflow) for the off-by-one bug this design went through before it was correct.

### LLM Provider ✅ Implemented (M2, extended M5)

A Protocol (`providers/llm/base.py`) with two concrete implementations: `MockProvider` (deterministic, offline) and `AnthropicProvider` (real, wraps the Anthropic Messages API). Both record their own Langfuse `generation` for every call — same span name and shape regardless of which is configured (`LLM_PROVIDER` in `.env`), capturing model, tokens, and cost details. `get_llm_provider()` selects between them from `Settings`. Since M5, `complete()` accepts an optional `tools` parameter and `LLMResponse` may carry `tool_calls` — `AnthropicProvider` translates these to/from Anthropic's actual tool-calling shapes (verified via SDK introspection, not assumed); `MockProvider` uses a small fixed keyword-trigger table as a deterministic stand-in for real tool selection.

### Travel Tools ✅ Implemented and connected (M4, wired M5)

Plain, synchronous, typed Python functions (`tools/travel_tools.py`) backed by a small hand-authored synthetic dataset (`data/synthetic/`: 8 destinations, 18 hotels) generated by `scripts/generate_data.py`. Each call opens a real Langfuse **`tool`** observation — a distinct type from `span`/`generation`, with its own UI filter facet — capturing input parameters and a result summary (e.g. `result_count`). Callable standalone (`make tools-smoke-test`) or, since M5, from within the agent's `tools` node — the same code, unchanged, nests correctly under whichever trace is active either way.

Three tools, described to the LLM via `tools/specs.py`'s `TOOL_SPECS` (JSON Schema, matching Anthropic's `tools` parameter format directly):
- `search_destinations(tags, climate, limit)` — filters by tag overlap and/or exact climate match
- `search_hotels(destination_id, family_friendly, max_price_band, limit)` — scoped to one destination, filtered by family fit and a price-band ceiling (`budget ≤ mid ≤ luxury`)
- `get_destination_information(destination_id)` — single-record lookup, `None` if not found

### Langfuse

The observability backend. Receives structured trace data from the application. Provides the UI for trace inspection, prompt management, dataset management, evaluation, and experiments.

## Trace Structure

One API request → one top-level Langfuse trace. **What `POST /chat` produces today when no tool is needed** (`agent_enabled=True`, the default — same shape whether the model answers directly or is asked something it doesn't need a tool for):

```
travel_concierge_turn  (trace — session_id, user_id, environment via propagate_attributes)
└─ agent                (agent observation, iteration 0)
   └─ llm_call          (generation: model, tokens, latency)
```

**What it produces when the model requests a tool** — verified live via `POST /chat` with `"find me a hotel"`, exactly this shape in the Langfuse UI, not just asserted in tests:

```
travel_concierge_turn        (trace)
├─ agent                     (agent, iteration 0 — requests a tool)
│  └─ llm_call               (generation)
├─ execute_tools             (span — groups every tool call from this turn)
│  └─ search_hotels          (tool: input params, result count)
└─ agent                     (agent, iteration 1 — final answer)
   └─ llm_call               (generation)
```

The loop continues (another `execute_tools` + `agent` pair) if the model requests another tool from the result, up to `Settings.agent_max_iterations` (default 5) — see [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-5--explicit-agentic-ai-workflow) for what happens at that limit.

**With `AGENT_ENABLED=false`** — the Milestone 2 shape, kept as a live comparison point rather than removed:

```
travel_concierge_turn  (trace)
└─ llm_call             (generation — no `agent` span, no tools offered at all)
```

`scripts/smoke_test_agent.py` (`make agent-smoke-test`) produces both of the first two shapes in one run, for exactly this comparison, without needing to restart the server with a different `AGENT_ENABLED` value.

A standalone tool call (`make tools-smoke-test`, or a test calling `search_hotels(...)` directly) still produces its own single-node root trace, unnested — the same code the agent's `tools` node calls, just with no parent trace active. Confirmed unchanged since Milestone 4.

## Configuration

All behaviour is controlled by environment variables via Pydantic Settings.  
See `.env.example` for the full list.

Two Langfuse modes:
- **Local** (default): `LANGFUSE_HOST=http://localhost:${LANGFUSE_WEB_PORT:-3000}` — started via `make langfuse-up`. Full deployment reference: [docs/langfuse.md](langfuse.md).
- **Cloud**: `LANGFUSE_HOST=https://cloud.langfuse.com` — requires Cloud credentials

`src/travel_ai_concierge/observability/langfuse_client.py` builds the Langfuse client explicitly from `Settings` (`get_langfuse_client()`), rather than relying on the SDK's own env-var auto-discovery — see [ADR-004](decisions/ADR-004-langfuse-deployment.md) and [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-1--local-langfuse) for why.

LLM provider selection (`LLM_PROVIDER=mock|anthropic`) is likewise a `Settings`-driven, one-line config change — see [ADR-003](decisions/ADR-003-llm-provider-abstraction.md) and [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-2--minimal-concierge-with-tracing).

The UI reaches the API via `Settings.api_base_url` (`API_BASE_URL` in `.env`) — a separate value from `api_host`/`api_port`, which describe where the server binds, not where a client should connect. See [ADR-002](decisions/ADR-002-ui-technology.md) and [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-3--chat-ui).

The synthetic travel dataset (`data/synthetic/*.json`) is not `Settings`-configurable — its path is resolved relative to the `tools/data.py` module's own location, since it's a fixed part of this repository rather than an environment-specific value. Regenerate it with `make generate-data` after editing `scripts/generate_data.py`.

`Settings.agent_enabled` (default `True`) and `Settings.agent_max_iterations` (default `5`) control the Milestone 5 agent graph — see [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-5--explicit-agentic-ai-workflow) for why this is a flag rather than two permanent code paths.

## Milestone Status

| Milestone | Description                         | Status      |
|-----------|-------------------------------------|-------------|
| M0        | Scaffolding, config, health API      | ✅ Complete |
| M1        | Local Langfuse deployment            | ✅ Complete |
| M2        | Minimal concierge (LLM + tracing)   | ✅ Complete |
| M3        | Chat UI                              | ✅ Complete |
| M4        | Synthetic travel tools               | ✅ Complete |
| M5        | LangGraph agent workflow             | ✅ Complete |
| M6        | Production-like trace design         | ⬜ Next     |
| …         | See PROJECT_SPEC.md for full list    |             |

## Architecture Decision Records

| ADR | Decision |
|-----|----------|
| [ADR-001](decisions/ADR-001-agent-framework.md) | LangGraph for agent orchestration |
| [ADR-002](decisions/ADR-002-ui-technology.md) | Streamlit for chat UI |
| [ADR-003](decisions/ADR-003-llm-provider-abstraction.md) | Protocol-based LLM provider abstraction |
| [ADR-004](decisions/ADR-004-langfuse-deployment.md) | Self-hosted Langfuse as default, Cloud as optional |
| [ADR-005](decisions/ADR-005-headless-initialization.md) | Headless-initialize local Langfuse (org/project/keys) rather than manual signup |
