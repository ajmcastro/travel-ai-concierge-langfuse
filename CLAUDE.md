# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Travel AI Concierge — a production-quality educational project demonstrating Agentic AI with Langfuse observability. Python 3.12, FastAPI, Streamlit UI, LangGraph (M5+), uv for all package management.

## Commands

```bash
make install        # uv sync --all-groups
make env            # copy .env.example → .env if missing
make serve          # uvicorn with auto-reload (port 8000)
make health         # curl /health
make ui             # Streamlit chat UI (port 8501), requires `make serve` running separately

make test           # all tests
make test-unit      # tests/unit only (no infrastructure)
make lint           # ruff check
make format         # ruff format
make typecheck      # mypy
make check          # lint + format-check + typecheck

make langfuse-up          # start local Langfuse stack (postgres/clickhouse/redis/minio/web/worker)
make langfuse-down        # stop it
make langfuse-smoke-test  # create a real trace, print its URL (scripts/smoke_test_langfuse.py)
make chat-smoke-test      # POST /chat over real HTTP against a running `make serve` (scripts/smoke_test_chat.py)
make test-integration     # tests/integration — requires langfuse-up first
```

Run a single test file:

```bash
uv run pytest tests/unit/test_health.py -v
```

## Package structure

Source lives in `src/travel_ai_concierge/` (src layout, installed as editable). Key modules:

- `config/settings.py` — `Settings` via Pydantic Settings; `get_settings()` is lru_cache'd. Override with env vars or `.env`.
- `api/app.py` — `create_app()` returns the FastAPI instance; `app` is the module-level singleton used by uvicorn. Flushes the Langfuse client on shutdown if `langfuse_flush_at_shutdown`.
- `api/routes/health.py` — `GET /health`
- `api/routes/chat.py` — `POST /chat`. Opens one root span (`travel_concierge_turn`) per request, sets `session_id`/`user_id`/`environment` via `propagate_attributes(...)`, calls the configured LLM provider. `trace_id` in the response body is `None` unless `Settings.debug`; `client.flush()` is likewise only called in debug mode — never on the unconditional request path (see ADR-004). **Gotcha**: with the default `DEBUG=true`, calling `/chat` before `make langfuse-up` costs a measured ~2.5s per request (flush retry/backoff against an unreachable host), not a fast failure — start Langfuse first.
- `api/schemas/chat.py` — `ChatRequest`/`ChatResponse` Pydantic models.
- `logging_config.py` — structlog, JSON in production, coloured key=value in TTY
- `observability/langfuse_client.py` — `get_langfuse_client()`, lru_cache'd, built explicitly from `Settings` (SDK's own env-var auto-discovery won't see `.env` — pydantic-settings doesn't mutate `os.environ`). Always returns a real client, even when `langfuse_enabled=False` (passes `tracing_enabled=False` through) — call sites never need an `if enabled:` branch. **Its `lru_cache` is separate from `get_settings()`'s** — tests that monkeypatch Langfuse-related env vars must clear both caches (`get_settings.cache_clear()` and `get_langfuse_client.cache_clear()`), or they'll silently reuse whichever client config the first test in the run happened to construct.
- `providers/llm/base.py` — `LLMProvider` Protocol, `Message`/`LLMResponse`/`Usage` models.
- `providers/llm/mock.py` — `MockProvider`, deterministic word-count-based token usage, still opens its own `llm_call` generation span (same shape as the real provider).
- `providers/llm/anthropic_provider.py` — `AnthropicProvider`. The installed `anthropic` SDK's `messages.create()` has **no `temperature` parameter** — verified by introspection, not assumed; `Settings.llm_temperature` is unused here.
- `providers/llm/__init__.py` — `get_llm_provider()`, lru_cache'd, selects Mock vs Anthropic from `Settings.llm_provider`.

`ui/streamlit_app.py` (not under `src/` — run via `streamlit run`, not imported as a package) — the Chat UI. Talks to the API only via `httpx2.post(f"{settings.api_base_url}/chat", ...)`, never by importing agent/provider code. **Gotcha 1**: the sidebar debug panel is rendered *before* the `chat_input` handling block in the script's top-to-bottom order, so after a successful exchange the code calls `st.rerun()` before returning — without it, the debug panel would always show the previous turn's trace/model/latency, one interaction behind (`st.session_state` mutations don't retroactively re-render earlier widgets in the same pass). **Gotcha 2**: the sidebar's `get_langfuse_client().get_trace_url(...)` call is wrapped in a broad `except Exception` — verified live (pointed a real server+UI at an unreachable `LANGFUSE_HOST`) that this call raises different exception types depending on failure mode (`httpx2.ConnectError` unreachable, `langfuse.api.commons.errors.UnauthorizedError` bad keys, `httpx2.TimeoutException` slow network); narrower catches would still leak a raw traceback into the UI for the cases not caught. Tested with Streamlit's own `streamlit.testing.v1.AppTest` harness (`tests/unit/test_ui_chat.py`), with `httpx2.post` monkeypatched to stay offline.

## Architecture

One chat turn → one Langfuse trace. As of M2 that's `travel_concierge_turn` (root span) → one `llm_call` generation; from M5 onward the agent graph adds a span per node in between. See `docs/architecture.md` for diagrams (including the current-vs-target trace shape), `docs/langfuse.md` for the self-hosted deployment reference, and `docs/decisions/` for ADRs.

LangGraph is the agent framework (M5, not built yet — `/chat` calls the LLM provider directly today). LLM provider is a Protocol (`LLM_PROVIDER` env var) with `MockProvider` (default, offline, deterministic) and `AnthropicProvider` (real). Langfuse is self-hosted via Docker Compose by default (v4 — see `docker-compose.yml`); switch to Cloud by changing `LANGFUSE_HOST` in `.env`.

Langfuse SDK is v4, OTel-based: `Langfuse(...)` construction does no network I/O; spans batch and export on `flush()`/shutdown. Trace-level attributes (`session_id`, `user_id`, `tags`, `environment`) are set via `propagate_attributes(...)` (a module-level import from `langfuse`, not a client method) — there is no `update_current_trace()`. Capture `span.trace_id` while still inside the `with start_as_current_observation(...)` block; `get_current_trace_id()` returns `None` after it exits. `usage_details` dict keys should be `"input"`/`"output"` — verified to render correctly in the UI; the docstring's own example (`prompt_tokens`/`completion_tokens`) is unverified, don't assume it also works.

## Langfuse env vars

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000     # or https://cloud.langfuse.com
LANGFUSE_WEB_PORT=3000                  # override if 3000 is taken locally
```

Integration tests (`tests/integration/`) require `make langfuse-up` and are excluded from `make test`/`make test-unit` by default (`-m "not integration"` in `pyproject.toml`). Run them with `make test-integration`.

## Stop hook

`.claude/settings.json` runs `scripts/export_chat.py` after every response, exporting the session to `docs/CHAT_HISTORY.md`.
