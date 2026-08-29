# Travel AI Concierge — Langfuse Observability Lab

An educational, production-quality open-source project demonstrating how to design, instrument, monitor, evaluate, and progressively improve an **Agentic AI application using [Langfuse](https://langfuse.com)**.

The application domain is travel. The learning objective is **AI observability and evaluation engineering**.

> **Current milestone:** M0 — Scaffolding  
> The agent, tools, and Langfuse integration are built incrementally across milestones.

---

## What this project teaches

- Agentic AI application architecture (LangGraph)
- Production LLM observability: traces, spans, generations, sessions, users
- Tool-call observability and agent trajectory analysis
- Token usage, latency, and cost monitoring
- Prompt management and versioning
- Offline and online evaluation (deterministic + LLM-as-judge + human feedback)
- Regression detection and evaluation-driven CI
- Production debugging workflows using trace data
- Privacy and security considerations for AI observability

See [docs/architecture.md](docs/architecture.md) for the full architecture.  
See [docs/decisions/](docs/decisions/) for the architectural decision records.

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
# Start the full Langfuse stack (added in Milestone 1)
make langfuse-up

# Open the UI
open http://localhost:3000

# Stop
make langfuse-down
```

Create a project in the Langfuse UI, copy the API keys into `.env`, and the application will automatically send traces there.

### Optional: Langfuse Cloud

To use [Langfuse Cloud](https://cloud.langfuse.com) instead, change three values in `.env`:

```env
LANGFUSE_PUBLIC_KEY=pk-lf-<your-cloud-key>
LANGFUSE_SECRET_KEY=sk-lf-<your-cloud-key>
LANGFUSE_HOST=https://cloud.langfuse.com
```

No code changes required.

---

## Development

```bash
make test           # run all tests
make test-unit      # unit tests only (no infrastructure required)
make lint           # ruff check
make format         # ruff format
make typecheck      # mypy
make check          # lint + format-check + typecheck
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
├── observability/   — Langfuse integration (Milestone 2)
└── evaluation/      — Evaluators and runners (Milestone 9)

docs/
├── architecture.md
├── decisions/       — Architecture Decision Records (ADRs)
└── PROJECT_SPEC.md  — Full specification

data/
├── synthetic/       — Synthetic travel data (Milestone 4)
└── evaluation/      — Evaluation datasets (Milestone 9)
```

---

## Milestones

| # | Description |
|---|-------------|
| M0 | Scaffolding, config, health API ✅ |
| M1 | Local Langfuse deployment |
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

This project was designed and implemented by Antonio de Castro, with AI-assisted development using Claude Code (model Sonnet4.6).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
