# Experiments

A record of things we tried and measured. Most entries from Milestone 9 onward will be quality/cost/latency experiments over the evaluation dataset; this milestone's entry is an infrastructure verification instead — there's no agent or evaluation dataset yet.

Each entry: hypothesis, configuration, result, interpretation, surprises, limitations.

---

## 2026-08-29 — M1: Local Langfuse ingestion verification

**Hypothesis**: The self-hosted Langfuse stack (docker-compose.yml), our client factory (`get_langfuse_client()`), and the OTel-based SDK v4 correctly deliver a trace with nested spans, session/user attribution, and token usage from Python code to the Langfuse UI, end-to-end, on a fresh local machine.

**Configuration**:
- Stack: `docker compose up -d` (postgres, clickhouse, redis, minio, langfuse-worker, langfuse-web — all `:4`)
- Client: `travel_ai_concierge.observability.get_langfuse_client()`
- Script: `scripts/smoke_test_langfuse.py` — one root span (`travel_concierge_turn`) wrapping one `generation`-type span (`mock_llm_call`), with `session_id`, `user_id`, `tags=["milestone-1","smoke-test"]`, `environment` set via `propagate_attributes(...)`.

**Result**: Pass. `auth_check()` succeeded; the trace appeared in the UI within ~1s of `flush()` with correct latency (0.05s), session chip, user chip, environment, release (`0.1.0` — from `Settings.app_version`), tags, and the nested generation showing token counts (10 → 12). Verified visually via the browser, not just via `get_trace_url()` returning a non-null URL.

**Interpretation**: The full observability path — Settings → explicit `Langfuse(...)` construction → OTel span batching → self-hosted ingestion pipeline (web → redis → worker → clickhouse) → UI query — works as designed. `propagate_attributes()` is confirmed as the correct mechanism for trace-level attributes (there is no `update_current_trace()` method on the client; this cost some investigation — see Surprises).

**Surprises**:
- The installed SDK is a major version ahead of what the original architecture doc (ADR-004) assumed: Langfuse self-hosted is now **v4** (`docker.langfuse.com/langfuse/*:4`), not v3. Image registry also moved from Docker Hub to `docker.langfuse.com`.
- `Langfuse.get_current_trace_id()` returns `None` once you've exited the `with start_as_current_observation(...)` block that created the trace — the trace_id must be captured from the span object (`span.trace_id`) *while still inside* the context, not read back afterward. This would have been a silent bug (script prints "Trace ID: None") if not caught by direct SDK introspection before writing the script.
- `GET /api/public/traces/{id}` returns `"This endpoint is not available on deployments running in Langfuse v4 events_only mode"` — the classic REST trace-fetch endpoint is gone/changed in v4. Verification had to fall back to the UI directly rather than a REST round-trip. Worth revisiting once we need programmatic trace verification (e.g. for `make eval-ci` in later milestones).
- A pre-existing, unrelated container (`open-webui`) was already bound to host port 3000, which is Langfuse's documented default. Solved with a `LANGFUSE_WEB_PORT` override rather than hardcoding a different default for everyone — see ADR-005 and `docs/langfuse.md`.

**Limitations**: This validates plumbing, not product behavior — there's no real LLM call, no real travel data, and nothing evaluated for quality. That starts in Milestone 2.

---

## 2026-08-29 — M2: End-to-end chat request with real HTTP, sessions, and provider-level generations

**Hypothesis**: `POST /chat` — routed through `MockProvider` by default — produces a correctly-shaped Langfuse trace (root span + nested generation) with session/user/environment attribution, over a real HTTP request (not an in-process call), and the same code path works unmodified against the real Anthropic API.

**Configuration**:
- `make serve` (real uvicorn process) + `scripts/smoke_test_chat.py` (real `httpx` client, not `TestClient`)
- Two sequential `/chat` calls sharing one `session_id`, second call carrying `user_id=curl-test-user`
- Provider: `MockProvider` (default `LLM_PROVIDER=mock`)

**Result**: Pass, verified visually in the UI, not just via non-error responses. The Sessions view showed `session-6b06b001e1b5` with **Total traces: 2** and **User ID: curl-test-user** at the session level (only the second of the two calls included `user_id`), and both `travel_concierge_turn` traces expanded to show their nested `llm_call` generation with the exact system/user/assistant content. `make chat-smoke-test` against a live server round-tripped correctly and printed a working trace URL.

**Interpretation**: `propagate_attributes` composes correctly across multiple independent traces sharing a `session_id` — session-level aggregation (trace count, cost) works exactly as the Langfuse data model promises. Keeping generation-instrumentation code identical between `MockProvider` and `AnthropicProvider` (ADR-003) pays off immediately: the trace shape a developer inspects while iterating offline is the same shape production traces have.

**Surprises**:
- The installed `anthropic` SDK (`1.2.0`) has **no `temperature` parameter** on `messages.create()` — confirmed by introspecting the installed package (`inspect.signature`), not assumed. `Settings.llm_temperature` exists but `AnthropicProvider` silently ignores it. A new `output_config.effort` parameter (`low`/`medium`/`high`/`xhigh`/`max`) appears to be the model family's current control surface instead — not wired up, since M2 didn't ask for it, but worth remembering if a later milestone wants to experiment with reasoning effort as a quality/cost/latency lever.
- The `anthropic` SDK depends on `httpx2`, not `httpx` — consistent with the `httpx2` swap already made in this repo's dev dependencies during Milestone 0 to silence a Starlette deprecation warning. Two unrelated decisions turned out to point the same direction.
- Writing the mock/real provider tests surfaced a real caching bug before it shipped: `get_langfuse_client()` is its own `lru_cache` singleton, separate from `get_settings()`. A test fixture that clears the Settings cache but not the Langfuse client cache would silently reuse whichever `tracing_enabled`/`host` config the *first* test in the run happened to construct — flaky in a way that would only surface depending on test execution order. Caught by reasoning through the fixture, not by a failure; fixed by clearing all three caches (`get_settings`, `get_llm_provider`, `get_langfuse_client`) together.
- Measured, not assumed: calling `client.flush()` with `tracing_enabled=True` against an unreachable host takes **2.54s** (retry + backoff before giving up), versus **0.00s** when `tracing_enabled=False` (confirmed no network attempt is made at all). Concretely, this means a fresh clone that runs `make serve` and hits `/chat` *before* `make langfuse-up` — a very plausible first-run ordering, since Quick start and Chat API were adjacent in the README — pays a real ~2.5s tax per request (plus noisy stderr from the SDK's own retry logging), not a fast failure. Fixed by reordering the README so the Langfuse section comes before Chat API, with an explicit warning, rather than by changing `flush()`'s behavior — the latency is Langfuse actually not being there yet, not a bug in how we call it.

**Limitations**: Only one system prompt, no conversation history/memory across turns (each `/chat` call is stateless beyond the shared `session_id` label), no tools, no real travel data. `AnthropicProvider` is implemented and unit-tested for wiring, but its integration test is skipped in this environment (no `ANTHROPIC_API_KEY` configured) — it has not actually been exercised against the live Anthropic API in this run.
