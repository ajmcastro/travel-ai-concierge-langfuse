# Travel AI Concierge — Langfuse Observability Lab

Your agent works great in the demo. Then it's in production: a user got a weird recommendation, the OpenAI bill tripled overnight, or one specific conversation is slow and you don't know if it's the LLM, a tool call, or your own code. **How do you actually find out what happened?**

This repo builds a real (if toy) agentic AI application — a travel concierge — and instruments it end-to-end with [Langfuse](https://langfuse.com) to answer exactly that question, milestone by milestone: tracing, sessions, token/cost/latency monitoring, prompt versioning, and offline/online evaluation including LLM-as-judge and regression detection. The travel domain is the vehicle; **AI observability and evaluation engineering is what you're here to learn.**

**Who this is for**: developers who can already build an LLM agent and now want to answer "is it actually working, and how would I know if it broke?" — not a Python or LangChain tutorial.

> **Current milestone:** M5 — Explicit Agentic AI workflow ([progress table](#milestones))  
> Built and documented one milestone at a time — see [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md) for the reasoning behind each step, not just the result.

---

## What this project teaches

Each item below is built at a specific milestone (see the [Milestones](#milestones) table) — this isn't a feature list, it's a curriculum you can follow in order.

- Agentic AI application architecture (LangGraph)
- Production LLM observability: traces, spans, generations, sessions, users
- Tool-call observability and agent trajectory analysis
- Token usage, latency, and cost monitoring
- Prompt management and versioning
- Offline and online evaluation (deterministic + LLM-as-judge + human feedback)
- Regression detection and evaluation-driven CI
- Production debugging workflows using trace data
- Privacy and security considerations for AI observability

---

## Technology

| Concern | Technology |
|---------|-----------|
| Language | Python 3.12 |
| Package management | [uv](https://docs.astral.sh/uv/) |
| API | FastAPI |
| Agent orchestration | LangGraph ✅ |
| Chat UI | Streamlit ✅ |
| Observability | [Langfuse](https://langfuse.com) |
| LLM provider | Anthropic / Mock (OpenAI planned) |
| Testing | pytest |
| Linting | Ruff |
| Type checking | mypy |
| Infrastructure | Docker Compose |

---

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker + Docker Compose (for Langfuse)

---

## Quick start

```bash
# 1. Install dependencies
make install

# 2. Create your local .env (fill in credentials after creating Langfuse project)
make env

# 3. Start the API
make serve

# 4. Check it's running
make health

# 5. Start the chat UI (in another terminal)
make ui
```

---

## Langfuse — local self-hosted (default)

**Start this before you call `/chat`** — with the `.env.example` default (`DEBUG=true`), every request flushes to Langfuse before responding; if nothing is listening yet, that's a real ~2.5s retry/backoff penalty per request, not an instant failure. See `docs/EXPERIMENTS.md` (Milestone 2) for the measured number.

```bash
# Start the full Langfuse stack: postgres, clickhouse, redis, minio, langfuse-web/worker
make langfuse-up

# Open the UI (port from LANGFUSE_WEB_PORT in your .env, default 3000)
open http://localhost:3000

# Create a real trace and print its URL
make langfuse-smoke-test

# Stop
make langfuse-down
```

Your `.env` (from `.env.example`) provisions an org, project, user, and API key pair automatically on first boot — no manual signup required, and `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are valid immediately. Sign in to the UI with `LANGFUSE_INIT_USER_EMAIL`/`_PASSWORD` from the same file. Full reference, including the manual-signup alternative and what to do if port 3000 is already taken on your machine: [docs/langfuse.md](docs/langfuse.md).

### Optional: Langfuse Cloud

To use [Langfuse Cloud](https://cloud.langfuse.com) instead, change three values in `.env`:

```env
LANGFUSE_PUBLIC_KEY=pk-lf-<your-cloud-key>
LANGFUSE_SECRET_KEY=sk-lf-<your-cloud-key>
LANGFUSE_HOST=https://cloud.langfuse.com
```

No code changes required.

---

## Chat API

```bash
# Talk to it — defaults to the deterministic mock provider, no API key needed
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Plan me a quiet 5-day trip to Portugal"}' | python3 -m json.tool

# Or, with the server already running elsewhere (make serve):
make chat-smoke-test
```

Every request is one Langfuse trace. By default (`AGENT_ENABLED=true`) it runs the Milestone 5 agent: an `agent` step decides whether to answer directly or call a tool; if it calls one, an `execute_tools` step runs it and the agent gets another turn to incorporate the result, looping until it has a final answer (capped by `AGENT_MAX_ITERATIONS`, default 5). Try a message that triggers the mock provider's tool-calling path:

```bash
curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message": "find me a hotel"}' | python3 -m json.tool
```

Pass the same `session_id` across requests to group them into one conversation; pass `user_id` to attribute a trace to a real, stable identity (omitted rather than fabricated when you don't have one — see [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md#milestone-2--minimal-concierge-with-tracing)).

With `DEBUG=true` (the `.env.example` default), the response includes a `trace_id` you can open directly in the Langfuse UI. Switch to the real model:

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5
ANTHROPIC_API_KEY=sk-ant-...
```

No code changes, no different endpoint — same `/chat`, same trace shape, real tokens and cost instead of a deterministic echo.

---

## Chat UI

```bash
make serve    # API, in one terminal
make ui       # Streamlit, in another — opens at http://localhost:8501
```

A real chat interface: multi-turn transcript, a "New conversation" button (fresh `session_id`, cleared history), thumbs up/down under each response, and a sidebar debug panel (session/user ID, model, client-measured latency, and a link straight to the trace in Langfuse).

Talks to the API exclusively over HTTP (`API_BASE_URL` in `.env`) — the UI process never imports agent or provider code, so it can be started, stopped, or deployed independently of the API. Two honest limitations, both visible in the UI itself rather than hidden: feedback buttons are a visible placeholder with no backend effect yet (real Langfuse scoring is Milestone 12), and each message is still sent as a single, stateless request — the LLM doesn't see earlier turns in the same conversation yet (that starts in Milestone 7), even though the transcript displays the full history.

---

## Travel Tools

```bash
make generate-data      # (re)writes data/synthetic/*.json from scripts/generate_data.py
make tools-smoke-test   # calls all three tools directly, prints results + real Langfuse traces
```

Three typed, synchronous functions over a small hand-authored dataset (8 destinations, 18 hotels): `search_destinations`, `search_hotels`, `get_destination_information`. Each call opens a real Langfuse **tool** observation — a distinct type from `span`/`generation`, visible as its own filter facet in the Tracing UI.

Built and tested standalone in Milestone 4 before anything called them from a request — `make tools-smoke-test` still calls them directly with no parent trace, producing their own single-node root traces. Since Milestone 5, the same unchanged code is also called from inside the agent's `execute_tools` step, where it nests under the request's trace instead — see [Agent](#agent) below.

---

## Agent

```bash
make agent-smoke-test   # compares "simple chatbot" vs "tool-using agent" traces, no server needed
```

A hand-written LangGraph graph — two nodes, `agent` and `tools`, looping until the model stops requesting tools. No `langgraph.prebuilt` agent: every node and routing decision is a named Python function you can read directly (`src/travel_ai_concierge/agent/`). `agent` opens a real Langfuse **agent** observation (a distinct type, like `tool` in Milestone 4); `tools` groups every tool call from one turn under one `execute_tools` span.

Two independent safety nets cap the loop at `AGENT_MAX_ITERATIONS` (default 5): the agent withholds tools on what would be the last allowed call (so a well-behaved model still produces a real answer, not an empty one), and routing hard-stops regardless of that, in case a provider ever ignores having no tools offered. Full story, including a real off-by-one bug this went through, in [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md#milestone-5--explicit-agentic-ai-workflow).

Set `AGENT_ENABLED=false` to bypass the graph entirely and restore the Milestone 2 direct-call shape on the same `/chat` endpoint — the exact "simple chatbot vs. tool-using agent" comparison the milestone asks for, without maintaining two endpoints.

---

## Development Commands

```bash
make test              # run all tests (excludes integration by default)
make test-unit         # unit tests only (no infrastructure required)
make test-integration  # requires `make langfuse-up` first
make lint              # ruff check
make format            # ruff format
make typecheck         # mypy
make check             # lint + format-check + typecheck
```

---

## Project structure

```
src/travel_ai_concierge/
├── config/          — Pydantic Settings
├── api/             — FastAPI app, routes (/health, /chat), request/response schemas
├── agent/           — LangGraph agent/tools loop ✅ (Milestone 5): state, nodes, graph
├── providers/llm/   — LLM provider abstraction ✅ (Milestone 2, tool-calling added M5): Mock, Anthropic
├── observability/   — Langfuse client factory ✅ (Milestone 1)
├── domain/          — Destination, Hotel models ✅ (Milestone 4)
├── tools/           — search_destinations, search_hotels, get_destination_information ✅ (Milestone 4, connected via the agent M5)
└── evaluation/      — Evaluators and runners (Milestone 9)

ui/
└── streamlit_app.py — Chat UI ✅ (Milestone 3), talks to the API over HTTP only

data/
├── synthetic/       — 8 destinations, 18 hotels ✅ (Milestone 4), regenerate via `make generate-data`
└── evaluation/      — Evaluation datasets (Milestone 9)
```

---

## Documentation

| Read this... | ...when you want to |
|---|---|
| [docs/architecture.md](docs/architecture.md) | See the current system diagram, trace structure, and component responsibilities |
| [docs/langfuse.md](docs/langfuse.md) | Understand or troubleshoot the self-hosted Langfuse stack — services, ports, credentials |
| [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md) | Understand *why* a milestone was built the way it was, not just what it does |
| [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) | See what was actually tried and measured, including surprises and dead ends |
| [docs/decisions/](docs/decisions/) | Read the formal ADRs behind each major technical choice (agent framework, UI, LLM provider, Langfuse deployment) |
| [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) | Read the full, original brief this project is built from — kept verbatim for transparency |

---

## Milestones

| # | Description |
|---|-------------|
| M0 | Scaffolding, config, health API ✅ |
| M1 | Local Langfuse deployment ✅ |
| M2 | Minimal concierge with tracing ✅ |
| M3 | Chat UI ✅ |
| M4 | Synthetic travel tools ✅ |
| M5 | LangGraph agent workflow ✅ |
| M6 | Production-like trace design |
| M7 | Sessions and multi-turn analysis |
| M8 | Prompt management |
| M9 | Evaluation framework |
| M10–M21 | Datasets, experiments, LLM-as-judge, regression… |

---

## Development

This project was designed and implemented by Antonio de Castro, with AI-assisted development using Claude Code (model Sonnet5).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
