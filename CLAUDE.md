# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Travel AI Concierge — a production-quality educational project demonstrating Agentic AI with Langfuse observability. Python 3.12, FastAPI, LangGraph (M5+), Streamlit UI (M3+), uv for all package management.

## Commands

```bash
make install        # uv sync --all-groups
make env            # copy .env.example → .env if missing
make serve          # uvicorn with auto-reload (port 8000)
make health         # curl /health

make test           # all tests
make test-unit      # tests/unit only (no infrastructure)
make lint           # ruff check
make format         # ruff format
make typecheck      # mypy
make check          # lint + format-check + typecheck

make langfuse-up    # start local Langfuse stack (M1+)
make langfuse-down  # stop it
```

Run a single test file:

```bash
uv run pytest tests/unit/test_health.py -v
```

## Package structure

Source lives in `src/travel_ai_concierge/` (src layout, installed as editable). Key modules:

- `config/settings.py` — `Settings` via Pydantic Settings; `get_settings()` is lru_cache'd. Override with env vars or `.env`.
- `api/app.py` — `create_app()` returns the FastAPI instance; `app` is the module-level singleton used by uvicorn.
- `api/routes/health.py` — `GET /health`
- `logging_config.py` — structlog, JSON in production, coloured key=value in TTY

## Architecture

One chat turn → one Langfuse trace → spans for each agent node → generations for each LLM call. See `docs/architecture.md` for diagrams and `docs/decisions/` for ADRs.

LangGraph is the agent framework (M5). LLM provider is a Protocol with `MockProvider` (tests) and `AnthropicProvider` (real). Langfuse is self-hosted via Docker Compose by default; switch to Cloud by changing `LANGFUSE_HOST` in `.env`.

## Langfuse env vars

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000     # or https://cloud.langfuse.com
```

## Stop hook

`.claude/settings.json` runs `scripts/export_chat.py` after every response, exporting the session to `docs/CHAT_HISTORY.md`.
