# Travel AI Concierge — Langfuse Observability Lab

Your agent works great in the demo. Then it's in production: a user got a weird recommendation, the OpenAI bill tripled overnight, or one specific conversation is slow and you don't know if it's the LLM, a tool call, or your own code. **How do you actually find out what happened?**

This repo builds a real (if toy) agentic AI application — a travel concierge — and instruments it end-to-end with [Langfuse](https://langfuse.com) to answer exactly that question, milestone by milestone: tracing, sessions, token/cost/latency monitoring, prompt versioning, and offline/online evaluation including LLM-as-judge and regression detection. The travel domain is the vehicle; **AI observability and evaluation engineering is what you're here to learn.**

**Who this is for**: developers who can already build an LLM agent and now want to answer "is it actually working, and how would I know if it broke?" — not a Python or LangChain tutorial.

> **Current milestone:** M1 — Local Langfuse ([progress table](#milestones))  
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
| Agent orchestration | LangGraph (Milestone 5) |
| Chat UI | Streamlit (Milestone 3) |
| Observability | [Langfuse](https://langfuse.com) |
| LLM provider | Anthropic / OpenAI / Mock |
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
```

---

## Langfuse — local self-hosted (default)

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
├── api/             — FastAPI app and routes
├── agent/           — LangGraph state and graph (Milestone 5)
├── tools/           — Tool implementations (Milestone 4)
├── providers/       — LLM provider abstraction (Milestone 2)
├── observability/   — Langfuse client factory ✅ (Milestone 1)
└── evaluation/      — Evaluators and runners (Milestone 9)

data/
├── synthetic/       — Synthetic travel data (Milestone 4)
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
| M2 | Minimal concierge with tracing |
| M3 | Chat UI |
| M4 | Synthetic travel tools |
| M5 | LangGraph agent workflow |
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
