# Architecture — Travel AI Concierge

> Last updated: Milestone 4  
> This document evolves with the project. Each milestone adds to it.

## Overview

The Travel AI Concierge is an agentic AI application with comprehensive LLM observability via Langfuse. Its primary purpose is to demonstrate production-quality AI engineering practices using a realistic travel domain as the workload.

The diagram below is the **target architecture** — what this system looks like once the LangGraph agent (M5) exists and calls the travel tools (M4, built but not yet wired to anything — see [Milestone Status](#milestone-status)). As of Milestone 4, the top two boxes, the LLM Provider, and the Travel Tools box are real, but not yet connected to each other: the Chat UI calls `POST /chat` over HTTP, which calls a provider directly; the tools are independently callable and tested but nothing calls them from a request yet. See the [Trace Structure](#trace-structure) section for the current (simpler) trace shape a real request produces right now.

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
│              Travel AI Concierge Agent                      │
│                   (LangGraph graph)                         │
│                                                             │
│  understand_request ──→ clarify? ──yes──→ ask_user          │
│         │                                                   │
│        no                                                   │
│         ▼                                                   │
│  select_tools ──→ execute_tools ──→ generate_response       │
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

### FastAPI ✅ Implemented (M0, M2)

The HTTP boundary. Accepts chat requests, manages session IDs, and returns responses. Does not contain agent logic. Responsible for:
- Validating request schemas (Pydantic) — `api/schemas/chat.py`
- Opening the root Langfuse trace per request and setting session/user/environment attribution — `api/routes/chat.py`
- Delegating to the LLM provider directly (M2); will delegate to the agent graph instead from M5
- Returning trace IDs, but only when `Settings.debug` is true

### Travel AI Concierge Agent — Planned (M5)

The LangGraph graph. Defines the agent's reasoning workflow as explicit nodes and conditional edges. Each node is a named Python function. The graph is declared once and can be visualised. Not built yet — `POST /chat` calls the LLM provider directly for now.

### LLM Provider ✅ Implemented (M2)

A Protocol (`providers/llm/base.py`) with two concrete implementations: `MockProvider` (deterministic, offline) and `AnthropicProvider` (real, wraps the Anthropic Messages API). Both record their own Langfuse `generation` for every call — same span name and shape regardless of which is configured (`LLM_PROVIDER` in `.env`), capturing model, tokens, and cost details. `get_llm_provider()` selects between them from `Settings`.

### Travel Tools ✅ Implemented, not yet connected (M4)

Plain, synchronous, typed Python functions (`tools/travel_tools.py`) backed by a small hand-authored synthetic dataset (`data/synthetic/`: 8 destinations, 18 hotels) generated by `scripts/generate_data.py`. Each call opens a real Langfuse **`tool`** observation — a distinct type from `span`/`generation`, with its own UI filter facet — capturing input parameters and a result summary (e.g. `result_count`). Called standalone today (via `make tools-smoke-test`, or directly in tests); nothing in `/chat` or the LLM provider calls them yet. That wiring — an LLM actually choosing to call a tool — is Milestone 5's job; see [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-4--synthetic-travel-tools) for why this boundary was drawn here rather than in M4.

Three tools:
- `search_destinations(tags, climate, limit)` — filters by tag overlap and/or exact climate match
- `search_hotels(destination_id, family_friendly, max_price_band, limit)` — scoped to one destination, filtered by family fit and a price-band ceiling (`budget ≤ mid ≤ luxury`)
- `get_destination_information(destination_id)` — single-record lookup, `None` if not found

### Langfuse

The observability backend. Receives structured trace data from the application. Provides the UI for trace inspection, prompt management, dataset management, evaluation, and experiments.

## Trace Structure

One API request → one top-level Langfuse trace. **What `POST /chat` actually produces today (M2)**:

```
travel_concierge_turn  (trace — session_id, user_id, environment via propagate_attributes)
└─ llm_call             (generation: model, tokens, latency — MockProvider or AnthropicProvider)
```

**What a standalone tool call produces today (M4)** — no parent trace exists, so each becomes its own root trace, named after the tool:

```
search_hotels  (trace — this IS the tool call, not nested under anything yet)
```

This is the tools' true current call shape: `make tools-smoke-test` or any test calling `search_hotels(...)` directly produces exactly this. The moment something calls these tools from inside an active `travel_concierge_turn` trace (Milestone 5), the identical code nests automatically via OTel context propagation — no code change to the tools themselves.

**Target shape once the agent graph exists and calls the tools (M5)** — each node below becomes a real span once it exists, not before:

```
travel_concierge_turn  (trace)
├─ understand_request   (span)
│  └─ llm_call          (generation: model, tokens, latency)
├─ select_tools         (span)
├─ execute_tools        (span)
│  ├─ search_destinations  (tool: input params, result count — implemented, M4)
│  └─ search_hotels        (tool: input params, result count — implemented, M4)
└─ generate_response    (span)
   └─ llm_call          (generation: model, tokens, latency)
```

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

## Milestone Status

| Milestone | Description                         | Status      |
|-----------|-------------------------------------|-------------|
| M0        | Scaffolding, config, health API      | ✅ Complete |
| M1        | Local Langfuse deployment            | ✅ Complete |
| M2        | Minimal concierge (LLM + tracing)   | ✅ Complete |
| M3        | Chat UI                              | ✅ Complete |
| M4        | Synthetic travel tools               | ✅ Complete |
| M5        | LangGraph agent workflow             | ⬜ Next     |
| …         | See PROJECT_SPEC.md for full list    |             |

## Architecture Decision Records

| ADR | Decision |
|-----|----------|
| [ADR-001](decisions/ADR-001-agent-framework.md) | LangGraph for agent orchestration |
| [ADR-002](decisions/ADR-002-ui-technology.md) | Streamlit for chat UI |
| [ADR-003](decisions/ADR-003-llm-provider-abstraction.md) | Protocol-based LLM provider abstraction |
| [ADR-004](decisions/ADR-004-langfuse-deployment.md) | Self-hosted Langfuse as default, Cloud as optional |
| [ADR-005](decisions/ADR-005-headless-initialization.md) | Headless-initialize local Langfuse (org/project/keys) rather than manual signup |
