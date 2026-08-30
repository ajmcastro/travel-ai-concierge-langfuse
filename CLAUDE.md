# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Travel AI Concierge — a production-quality educational project demonstrating Agentic AI with Langfuse observability. Python 3.12, FastAPI, Streamlit UI, LangGraph, uv for all package management.

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

make generate-data        # (re)writes data/synthetic/*.json from scripts/generate_data.py
make tools-smoke-test     # call the 3 travel tools directly (scripts/smoke_test_tools.py)
make agent-smoke-test     # compare "simple chatbot" vs "tool-using agent" traces, no server needed
make conversation-smoke-test  # real 3-turn conversation + GET /sessions/{id} (scripts/smoke_test_conversation.py)
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
- `api/routes/chat.py` — `POST /chat`. Opens one root span (`travel_concierge_turn`) per request, sets `session_id`/`user_id`/`environment`/`tags`/`metadata`/`version` via `propagate_attributes(...)` (M6: `tags=["agent"|"direct-llm", "provider:<name>"]`, `metadata={"agent_enabled", "llm_provider", "history_turns"}`, `version=Settings.agent_version` only on the agent path — see `docs/TRACE_DESIGN.md`). Fetches prior turns from `get_conversation_store()` before building `messages` and replays them as alternating user/assistant messages ahead of the current one (M7); appends the new turn to the store only after a successful response — a call that raised is never remembered. By default (`Settings.agent_enabled`) delegates to `get_agent_graph().ainvoke(...)`; with `AGENT_ENABLED=false` calls the provider directly instead (the M2 shape, kept intentionally — see `agent_enabled` below). The agent/provider call is wrapped in `try/except`: any exception sets `level="ERROR"`/`status_message` on the root span before re-raising unchanged (M6 — HTTP behavior is still a plain 500). `trace_id` in the response body is `None` unless `Settings.debug`; `client.flush()` is likewise only called in debug mode — never on the unconditional request path (see ADR-004). **Gotcha**: with the default `DEBUG=true`, calling `/chat` before `make langfuse-up` costs a measured ~2.5s per request (flush retry/backoff against an unreachable host), not a fast failure — start Langfuse first.
- `api/routes/sessions.py` — `GET /sessions/{session_id}` (M7). Reads `get_conversation_store()`, 404 if the session has no history. `trace_id` per turn is `None` unless `Settings.debug`, same convention as `ChatResponse`.
- `api/schemas/chat.py` — `ChatRequest`/`ChatResponse` Pydantic models.
- `api/schemas/sessions.py` — `SessionTurn`/`SessionResponse` Pydantic models (M7).
- `conversation/store.py` — `ConversationStore` (M7): in-memory `dict[session_id, list[Turn]]` behind an `asyncio.Lock`, `get_history()`/`append_turn(..., max_turns)`. `append_turn` trims to the most recent `max_turns` (oldest dropped first) — **not** a database; state is per-process and lost on restart, a deliberate choice documented in `docs/architecture.md`'s "Conversation Memory" section, not an oversight.
- `conversation/__init__.py` — `get_conversation_store()`, lru_cache'd. **Unlike every other lru_cache singleton in this codebase, this one is stateful, not just cached config** — tests that hit `/chat` or `/sessions` must clear it (`get_conversation_store.cache_clear()`) in the same fixture that clears `get_settings`/`get_llm_provider`/etc., or a `session_id` reused across two tests will carry real conversation history between them.
- `logging_config.py` — structlog, JSON in production, coloured key=value in TTY
- `observability/langfuse_client.py` — `get_langfuse_client()`, lru_cache'd, built explicitly from `Settings` (SDK's own env-var auto-discovery won't see `.env` — pydantic-settings doesn't mutate `os.environ`). Always returns a real client, even when `langfuse_enabled=False` (passes `tracing_enabled=False` through) — call sites never need an `if enabled:` branch. **Its `lru_cache` is separate from `get_settings()`'s** — tests that monkeypatch Langfuse-related env vars must clear both caches (`get_settings.cache_clear()` and `get_langfuse_client.cache_clear()`), or they'll silently reuse whichever client config the first test in the run happened to construct.
- `providers/llm/base.py` — `LLMProvider` Protocol (now declares a `model: str` attribute too — needed once `chat.py` reads `provider.model` polymorphically), `Message`/`LLMResponse`/`Usage`/`ToolCall`/`ToolSpec` models. `complete()` takes an optional `tools: list[ToolSpec] | None` (Milestone 5); `Message`/`LLMResponse` carry `tool_calls`.
- `providers/llm/mock.py` — `MockProvider`, deterministic word-count-based token usage, still opens its own `llm_call` generation span (same shape as the real provider). Since M5: a fixed keyword-trigger table (`_MOCK_TOOL_TRIGGERS`) decides whether to "call" a tool — a test double for reasoning, not an attempt at one. Recognizes a `role="tool"` message already in context and synthesizes a final answer from it, so it exercises the full agent loop (both hops), not just the first.
- `providers/llm/anthropic_provider.py` — `AnthropicProvider`. The installed `anthropic` SDK's `messages.create()` has **no `temperature` parameter** — verified by introspection, not assumed; `Settings.llm_temperature` is unused here. Since M5: `_to_anthropic_messages()`/`_to_anthropic_tools()` translate our provider-agnostic shapes to Anthropic's real ones (verified via SDK type introspection — `ToolParam`, `ToolUseBlockParam`, `ToolResultBlockParam`). **Anthropic has no "tool" role** — a tool result must be sent as a *user* message containing a `tool_result` content block; getting this wrong would likely fail silently rather than raise. Unverified against the live API in this environment (no `ANTHROPIC_API_KEY`); pinned by 6 offline unit tests (`tests/unit/test_anthropic_translation.py`) plus a skip-by-default integration test that will exercise it for real once a key exists.
- `providers/llm/__init__.py` — `get_llm_provider()`, lru_cache'd, selects Mock vs Anthropic from `Settings.llm_provider`.
- `domain/models.py` — `Destination`, `Hotel` Pydantic models; `PriceBand` (`"budget"|"mid"|"luxury"`) and `price_band_at_most()` for ceiling-style filtering.
- `tools/data.py` — `get_destinations()`/`get_hotels()`, lru_cache'd, load `data/synthetic/*.json`. Path resolved via `Path(__file__).resolve().parents[3]` (repo root), not cwd — same pattern as `tests/unit/test_ui_chat.py`'s `APP_PATH`.
- `tools/travel_tools.py` — `search_destinations`, `search_hotels`, `get_destination_information`. Plain sync functions (nothing to await), each opens its own Langfuse observation with **`as_type="tool"`** — a real, distinct Langfuse type (confirmed by SDK introspection, M1), not just a naming convention. Called standalone (root trace) or, since M5, from `agent/nodes.py`'s `tools_node` (nests under the active trace) — same code either way, no branching on caller.
- `tools/specs.py` — `TOOL_SPECS` (JSON Schema `ToolSpec` list, matches Anthropic's `tools` param shape directly) and `TOOL_REGISTRY` (name → callable), both consumed by `agent/nodes.py`.
- `agent/state.py` — `AgentState` TypedDict: `messages: list[Message]`, `iterations: int`. Nodes return whole-list replacements, not `Annotated` reducers — explicit over LangGraph's merge convenience.
- `agent/nodes.py` — `agent_node` (one LLM call with tools offered, `as_type="agent"` span) and `tools_node` (executes every requested tool call inside one `execute_tools` span, catches per-call exceptions so a hallucinated tool call becomes an error message the agent sees, not a 500). **Gotcha**: `agent_node`'s tools-withholding check is `state["iterations"] + 1 >= agent_max_iterations`, not `>=` — tracing the exact call sequence by hand showed the more obvious formula makes that branch unreachable, since routing's own hard cap (in `graph.py`) would always fire one call earlier at the same threshold. See `docs/EXPERIMENTS.md`, Milestone 5, before touching either threshold. **Gotcha (M6)**: a tool call with a missing/malformed required argument raises during `func(**call.arguments)`'s own argument binding — *before* the tool function's own `with` block (and its `tool` observation) ever opens — so `tools_node` is the only place that failure can be recorded at all; it now tracks failed call names and marks `execute_tools` `level="ERROR"` with a `status_message`, in addition to the pre-existing text-based recovery the agent sees.
- `agent/graph.py` — `build_graph()` (hand-wired `StateGraph`, no `langgraph.prebuilt`) and `_route_after_agent()` — the **second**, independent safety net: hard-stops the loop at `agent_max_iterations` regardless of what the last message contains, so a provider that ignores `tools=None` still can't loop forever.
- `agent/__init__.py` — `get_agent_graph()`, lru_cache'd (a compiled graph is stateless and reusable — state travels via `ainvoke()`, never stored on the graph object).

`ui/streamlit_app.py` (not under `src/` — run via `streamlit run`, not imported as a package) — the Chat UI. Talks to the API only via `httpx2.post(f"{settings.api_base_url}/chat", ...)`, never by importing agent/provider code. Since M7, the sidebar's disclaimer caption reflects real server-side memory (`Settings.max_history_turns`) instead of the old "stateless request" wording — update it again if `max_history_turns`' semantics ever change, since it's read dynamically via `settings.max_history_turns` in the f-string, not hardcoded. **Gotcha 1**: the sidebar debug panel is rendered *before* the `chat_input` handling block in the script's top-to-bottom order, so after a successful exchange the code calls `st.rerun()` before returning — without it, the debug panel would always show the previous turn's trace/model/latency, one interaction behind (`st.session_state` mutations don't retroactively re-render earlier widgets in the same pass). **Gotcha 2**: the sidebar's `get_langfuse_client().get_trace_url(...)` call is wrapped in a broad `except Exception` — verified live (pointed a real server+UI at an unreachable `LANGFUSE_HOST`) that this call raises different exception types depending on failure mode (`httpx2.ConnectError` unreachable, `langfuse.api.commons.errors.UnauthorizedError` bad keys, `httpx2.TimeoutException` slow network); narrower catches would still leak a raw traceback into the UI for the cases not caught. Tested with Streamlit's own `streamlit.testing.v1.AppTest` harness (`tests/unit/test_ui_chat.py`), with `httpx2.post` monkeypatched to stay offline.

## Architecture

One chat turn → one Langfuse trace. By default (`agent_enabled=True`): `travel_concierge_turn` → `agent` (`as_type="agent"`) → `llm_call` generation, and — only if the model requests a tool — `execute_tools` → the tool's own `as_type="tool"` observation → another `agent`/`llm_call` pair, looping until a final text answer or `agent_max_iterations` is hit. With `AGENT_ENABLED=false`: just `travel_concierge_turn` → `llm_call` (the M2 shape, kept as a live comparison, not deleted). Since Milestone 6, every trace also carries `tags`/`metadata`/(on the agent path) `agent_version`, and the relevant observation gets `level="ERROR"`/`status_message` on failure — see `docs/TRACE_DESIGN.md` for the full taxonomy and a real good-vs-poor example. Since Milestone 7, `messages` sent into that first `llm_call` of a turn already include up to `Settings.max_history_turns` prior exchanges from the same `session_id`, replayed by `chat.py` before the graph/provider is ever called — the agent/graph code itself has no special-casing for this, it just receives a longer `messages` list on later turns. See `docs/architecture.md` for full diagrams, `docs/langfuse.md` for the self-hosted deployment reference, and `docs/decisions/` for ADRs.

LangGraph is the agent framework — a hand-written 2-node (`agent`/`tools`) graph in `agent/`, no `langgraph.prebuilt`. LLM provider is a Protocol (`LLM_PROVIDER` env var) with `MockProvider` (default, offline, deterministic) and `AnthropicProvider` (real); both support tool-calling since M5. Travel tools (M4) are called from the agent's `tools_node` — same unnested-until-called-from-a-trace code as when run standalone. Langfuse is self-hosted via Docker Compose by default (v4 — see `docker-compose.yml`); switch to Cloud by changing `LANGFUSE_HOST` in `.env`.

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
