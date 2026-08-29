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
