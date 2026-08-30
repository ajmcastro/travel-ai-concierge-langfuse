# Architecture — Travel AI Concierge

> Last updated: Milestone 8  
> This document evolves with the project. Each milestone adds to it.

## Overview

The Travel AI Concierge is an agentic AI application with comprehensive LLM observability via Langfuse. Its primary purpose is to demonstrate production-quality AI engineering practices using a realistic travel domain as the workload.

As of Milestone 5, everything in the diagram below is real **except** the OpenAI provider and `build_itinerary` tool (shown for scale — future, unimplemented) and the Travel AI Search API integration (Milestone 18, optional). The Chat UI calls `POST /chat` over HTTP, which runs the LangGraph agent by default (`Settings.agent_enabled`, default `True`) — the agent decides whether to answer directly or call a tool, executes it if so, and loops back until it has a final answer. Since Milestone 7, each call also carries real conversation memory: prior turns in the same `session_id` are replayed into context, not just grouped in Langfuse. Since Milestone 8, the system prompt itself is fetched from Langfuse Prompt Management rather than hardcoded — see [Prompt Management](#prompt-management-m8) below. See the [Trace Structure](#trace-structure) section for what a real request actually produces, and [Milestone Status](#milestone-status) for what's implemented per milestone.

```
┌─────────────────────────────────────────────────────────────┐
│                        Chat UI (Streamlit)                  │
│         user messages · session continuity · debug panel    │
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTP
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI (port 8000)                      │
│        POST /chat · GET /sessions/{id} · GET /health        │
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
- Multi-turn transcript display (client-side history) — since M7, the backend itself also remembers the conversation server-side, so what the UI displays and what the LLM actually sees are the same content, not just a client-side illusion of memory
- Session continuity (`session_id` persisted per browser session) and reset ("New conversation")
- A stable, synthetic `user_id` per browser session (not per message)
- Debug panel: session/user ID, model, client-measured latency, and a link to the trace in Langfuse
- Feedback placeholders (`st.feedback`) — visible, but not yet sent to Langfuse (Milestone 12)
- Clean error display when the API is unreachable or returns an error, and when the debug panel's Langfuse trace-link lookup fails (unreachable host, bad credentials, timeout — caught broadly since this is a non-critical convenience, not the core chat feature)

### FastAPI ✅ Implemented (M0, M2, M5, M6, M7, M8)

The HTTP boundary. Accepts chat requests, manages session IDs, and returns responses. Does not contain agent logic itself — it delegates. Responsible for:
- Validating request schemas (Pydantic) — `api/schemas/chat.py`
- Opening the root Langfuse trace per request and setting session/user/environment/tags/metadata/version attribution — `api/routes/chat.py` (M6 adds tags, metadata, and the `agent_version` axis; see [TRACE_DESIGN.md](TRACE_DESIGN.md))
- Fetching prior turns from the conversation store and replaying them ahead of the current message before calling the agent/provider, then persisting the new turn on success (M7 — see "Conversation Memory" below)
- Fetching the system prompt from Langfuse Prompt Management before building `messages`, and linking it to the turn's generation(s) (M8 — see [Prompt Management](#prompt-management-m8) below)
- Delegating to the agent graph by default (`Settings.agent_enabled`, M5), or the LLM provider directly when `agent_enabled=False` (the M2 shape, kept as a live comparison point rather than deleted)
- Recording `level="ERROR"`/`status_message` on the root trace if the turn raises, before re-raising (M6)
- Returning trace IDs, but only when `Settings.debug` is true
- `GET /sessions/{session_id}` — returns this app's own stored turn history for a session, 404 if none exists (M7)

### Prompt Management (M8)

`src/travel_ai_concierge/prompts.py`'s `get_system_prompt()` fetches the system prompt from Langfuse Prompt Management by name (`travel-concierge-system`) and label (`Settings.prompt_label`, default `"production"`), instead of a hardcoded string. Two versions are seeded by `scripts/seed_prompts.py` (`make seed-prompts`): v1 labeled `production` (the original Milestone 2 text, encourages tool use), v2 labeled `staging` (a more directive version that requires tool use for destination/hotel facts). Flipping `PROMPT_LABEL=staging` switches `/chat` to v2 with no code change — the same "flip a setting" pattern `agent_enabled`/`llm_provider` already use.

**Local fallback, not a hard dependency**: `get_system_prompt()` passes `fallback=SYSTEM_PROMPT_FALLBACK` to the SDK's `get_prompt()` — if Langfuse is unreachable, or the prompt hasn't been seeded yet, the call never raises; it returns a synthetic `PromptClient` (`.is_fallback=True`) carrying the same text as v1. This is the milestone spec's explicit requirement ("do not make the application unable to start if remote prompt retrieval fails"), verified directly in `tests/unit/test_prompts.py` against a real (non-mocked) `Langfuse` client pointed at an intentionally-unreachable host.

**Prompt linking**: `chat.py` passes the fetched prompt to `propagate_attributes(prompt=prompt)`, which the Langfuse backend uses to link every generation in that turn to the exact prompt version that produced it — real Langfuse prompt-usage analytics, not a custom field. One real, non-obvious behavior confirmed by reading the SDK's own propagation source: **fallback prompts are never linked** — when Langfuse is down, the turn still completes correctly, it just has nothing to link to (since a fallback isn't a real served version). `prompt_version`/`prompt_fallback` are also added to trace metadata directly, so this is visible without opening the prompt link.

### Conversation Memory ✅ Implemented (M7)

An in-process, in-memory store (`conversation/store.py`'s `ConversationStore`, `dict[session_id, list[Turn]]` behind an `asyncio.Lock`) giving the agent real multi-turn memory — before this milestone, `session_id` only grouped traces in Langfuse; the LLM itself never saw a prior turn. `api/routes/chat.py` reads a session's history before building the message list, replays it as alternating user/assistant messages ahead of the current one, and appends the new turn only after a successful response (a failed turn is never remembered, so it can't poison every later turn's context).

Bounded by `Settings.max_history_turns` (default 10) — the store keeps only the most recent N turns per session, trimming the oldest first. This is a deliberate answer to the milestone spec's own "did context size grow excessively?" question: unbounded history *is* that failure mode, not just a hypothetical cost concern.

**Deliberately in-memory, not a database**: "semi-durable... appropriate for the educational system" (the spec's own wording) is read here as license to not introduce Postgres/Redis for app-level state when nothing else in this project needs a database. The real, durable record of what happened in a session is already Langfuse's own trace history — this store only needs to survive one running process, not a restart. A real production deployment running multiple worker processes would need shared storage (Redis, a database) instead, since this store is local to whichever process handled the request.

### Travel AI Concierge Agent ✅ Implemented (M5)

A hand-written LangGraph graph (`agent/graph.py`) — no `langgraph.prebuilt` agent, per [ADR-001](decisions/ADR-001-agent-framework.md). Two nodes:
- **`agent`** (`agent/nodes.py`) — one LLM call with the travel tools offered. Opens a real Langfuse **`agent`** observation (a distinct type, like `tool` in M4). If the model requests a tool, routes to `tools`; otherwise the graph ends.
- **`tools`** — executes every tool call the last `agent` message requested, wrapped in one `execute_tools` span so multiple calls in one turn nest together; each individual call is still its own `tool` observation underneath (M4, unchanged). Since M6, `execute_tools` records `level="ERROR"` with a `status_message` naming which call(s) failed — see [TRACE_DESIGN.md](TRACE_DESIGN.md#3-error-metadata) for why this needed to live here rather than inside the individual tool functions.

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

One API request → one top-level Langfuse trace. Every trace carries, since
Milestone 6, `session_id`/`user_id`/`environment` (from M2), plus `tags`,
`metadata`, and — on the agent path — an independent `agent_version`; see
[docs/TRACE_DESIGN.md](TRACE_DESIGN.md) for the full taxonomy and the
error-metadata design (`level`/`status_message`) this milestone also added.
Since Milestone 7, `metadata.history_turns` also records how many prior
turns were replayed into this specific trace's context — the direct,
per-trace answer to "did context size grow excessively," without needing a
custom cost/token dashboard (Langfuse's own per-session aggregation already
covers that; see [TRACE_DESIGN.md](TRACE_DESIGN.md)). Since Milestone 8,
every trace also carries `metadata.prompt_version`/`metadata.prompt_fallback`,
and — when a real (non-fallback) prompt was used — the turn's generation(s)
are linked to that exact prompt version via `propagate_attributes(prompt=...)`.

**What `POST /chat` produces today when no tool is needed** (`agent_enabled=True`, the default — same shape whether the model answers directly or is asked something it doesn't need a tool for):

```
travel_concierge_turn  (trace — session_id, user_id, environment, tags, metadata, agent_version, prompt link via propagate_attributes)
└─ agent                (agent observation, iteration 0)
   └─ llm_call          (generation: model, tokens, latency — linked to the prompt version, unless it was a fallback)
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

**If a tool call fails** (unknown tool name, or missing/malformed arguments — both realistic outcomes of an LLM hallucinating a call), `execute_tools` gets `level="ERROR"` and a `status_message` naming which call(s) failed, in addition to the graceful text-based recovery the agent already had (see [TRACE_DESIGN.md](TRACE_DESIGN.md#3-error-metadata)). **If anything else raises during a turn**, `travel_concierge_turn` itself gets the same `level="ERROR"` treatment before the exception is re-raised — the HTTP response is still a 500, but the trace now says why.

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

`Settings.agent_version` (default `"1.0.0"`) is Milestone 6's addition — bump it when the agent's own graph/node logic changes materially, independent of `Settings.app_version`. See [docs/TRACE_DESIGN.md](TRACE_DESIGN.md) for the full taxonomy this milestone introduced (tags, metadata, error levels).

`Settings.max_history_turns` (default `10`) bounds how many prior turns Milestone 7's conversation store replays into context per `/chat` call — the oldest turns are trimmed first once a session exceeds this. This is app-level state, in-memory and per-process (not backed by Redis/Postgres) — see "Conversation Memory" above for why that's a deliberate choice for this project rather than a shortcut.

`Settings.prompt_label` (default `"production"`) and `Settings.prompt_cache_ttl_seconds` (default `60`) control Milestone 8's Prompt Management fetch — see [Prompt Management](#prompt-management-m8) above and `docs/RATIONALE_PER_MILESTONE.md` for why `prompt_label`, not a second hardcoded prompt string, is the v1-vs-v2 comparison mechanism.

## Milestone Status

| Milestone | Description                         | Status      |
|-----------|-------------------------------------|-------------|
| M0        | Scaffolding, config, health API      | ✅ Complete |
| M1        | Local Langfuse deployment            | ✅ Complete |
| M2        | Minimal concierge (LLM + tracing)   | ✅ Complete |
| M3        | Chat UI                              | ✅ Complete |
| M4        | Synthetic travel tools               | ✅ Complete |
| M5        | LangGraph agent workflow             | ✅ Complete |
| M6        | Production-like trace design         | ✅ Complete |
| M7        | Sessions and multi-turn analysis     | ✅ Complete |
| M8        | Prompt management                    | ✅ Complete |
| M9        | Evaluation framework                 | ⬜ Next     |
| …         | See PROJECT_SPEC.md for full list    |             |

## Architecture Decision Records

| ADR | Decision |
|-----|----------|
| [ADR-001](decisions/ADR-001-agent-framework.md) | LangGraph for agent orchestration |
| [ADR-002](decisions/ADR-002-ui-technology.md) | Streamlit for chat UI |
| [ADR-003](decisions/ADR-003-llm-provider-abstraction.md) | Protocol-based LLM provider abstraction |
| [ADR-004](decisions/ADR-004-langfuse-deployment.md) | Self-hosted Langfuse as default, Cloud as optional |
| [ADR-005](decisions/ADR-005-headless-initialization.md) | Headless-initialize local Langfuse (org/project/keys) rather than manual signup |
