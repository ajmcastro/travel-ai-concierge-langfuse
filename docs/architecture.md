# Architecture — Travel AI Concierge

> Last updated: Milestone 1  
> This document evolves with the project. Each milestone adds to it.

## Overview

The Travel AI Concierge is an agentic AI application with comprehensive LLM observability via Langfuse. Its primary purpose is to demonstrate production-quality AI engineering practices using a realistic travel domain as the workload.

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
│ OpenAI       │                 │ get_dest_info      │
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

### FastAPI

The HTTP boundary. Accepts chat requests, manages session IDs, and returns responses. Does not contain agent logic. Responsible for:
- Validating request schemas (Pydantic)
- Creating/resuming Langfuse traces
- Delegating to the agent
- Returning trace IDs in development mode

### Travel AI Concierge Agent

The LangGraph graph. Defines the agent's reasoning workflow as explicit nodes and conditional edges. Each node is a named Python function. The graph is declared once and can be visualised.

### LLM Provider

A Protocol with concrete implementations. Handles all communication with the LLM API. Records a Langfuse `generation` for every call, capturing model, tokens, latency, and cost.

### Travel Tools

Plain Python functions with typed signatures. Each tool is a node in the agent graph (or called from a tool-execution node). Tool calls are recorded as Langfuse spans with input/output metadata.

### Langfuse

The observability backend. Receives structured trace data from the application. Provides the UI for trace inspection, prompt management, dataset management, evaluation, and experiments.

## Trace Structure

One API request → one top-level Langfuse trace:

```
travel_concierge_turn  (trace)
├─ understand_request   (span)
│  └─ llm_call          (generation: model, tokens, latency)
├─ select_tools         (span)
├─ execute_tools        (span)
│  ├─ tool.search_destinations  (span: input params, result count, latency)
│  └─ tool.search_hotels        (span: input params, result count, latency)
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

## Milestone Status

| Milestone | Description                         | Status      |
|-----------|-------------------------------------|-------------|
| M0        | Scaffolding, config, health API      | ✅ Complete |
| M1        | Local Langfuse deployment            | ✅ Complete |
| M2        | Minimal concierge (LLM + tracing)   | ⬜ Next     |
| M3        | Chat UI                              | ⬜ Planned  |
| M4        | Synthetic travel tools               | ⬜ Planned  |
| M5        | LangGraph agent workflow             | ⬜ Planned  |
| …         | See PROJECT_SPEC.md for full list    |             |

## Architecture Decision Records

| ADR | Decision |
|-----|----------|
| [ADR-001](decisions/ADR-001-agent-framework.md) | LangGraph for agent orchestration |
| [ADR-002](decisions/ADR-002-ui-technology.md) | Streamlit for chat UI |
| [ADR-003](decisions/ADR-003-llm-provider-abstraction.md) | Protocol-based LLM provider abstraction |
| [ADR-004](decisions/ADR-004-langfuse-deployment.md) | Self-hosted Langfuse as default, Cloud as optional |
| [ADR-005](decisions/ADR-005-headless-initialization.md) | Headless-initialize local Langfuse (org/project/keys) rather than manual signup |
