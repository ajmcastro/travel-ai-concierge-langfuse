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

---

## 2026-08-29 — M3: Chat UI wired to the real API, verified live in a browser

**Hypothesis**: A Streamlit app talking to the FastAPI backend exclusively over HTTP (never importing agent/provider code directly) can support multi-turn chat, session reset, feedback placeholders, and a debug panel with a working Langfuse trace link — and Streamlit's own `AppTest` harness is a viable way to test it without a live server.

**Configuration**:
- `make serve` (real uvicorn) + `make ui` (real Streamlit), driven through an actual browser — not just `AppTest`
- `tests/unit/test_ui_chat.py` using `streamlit.testing.v1.AppTest`, with `httpx2.post` monkeypatched so tests stay offline

**Result**: Pass, both automated and live. `AppTest` correctly runs the real script, simulates `chat_input`/`button`/`feedback` interactions, and follows through an `st.rerun()` inside `.run()`, confirmed by test assertions that only hold true *after* the rerun happens. Live in the browser: sent a message, got a mock response, thumbs-down feedback fired the placeholder toast, the sidebar showed `Model: mock-echo-v1` and `Latency (client-measured): 87 ms`, and "View trace in Langfuse" linked to a real, working trace (`http://localhost:3001/project/travel-ai-concierge-dev/traces/efdb36707e23d9a3efe326e88a4a6b86`). "New conversation" correctly reset the session ID and cleared history.

**Interpretation**: `AppTest` is a legitimate first-party alternative to skipping UI tests or mocking Streamlit's internals — it runs the actual script in a simulated runtime rather than requiring a rewrite into "testable" helper functions. `get_langfuse_client()`'s internal `_project_id` caching (confirmed by reading the SDK source, not assumed) means the debug panel's trace-URL construction costs one network call per UI *process* lifetime, not one per Streamlit rerun — otherwise a chat UI that reruns its whole script on every interaction would hit Langfuse's API on every single click just to build a link.

**Surprises**:
- Writing the `AppTest` for the trace-link debug panel caught a real UX bug before it shipped, not just a test-mocking wrinkle: the sidebar (which reads `st.session_state.messages` to find the "last assistant" turn) is rendered *earlier* in the script's top-to-bottom order than the `chat_input` handling block that appends the new message. Streamlit doesn't retroactively re-render earlier widgets within the same script pass when `session_state` changes mid-script — so without an explicit `st.rerun()` after a successful exchange, the debug panel would always show the *previous* turn's model/latency/trace, one interaction behind. Fixed with `st.rerun()` right after appending the new message (a standard, cheap pattern here — a rerun re-executes the script against the now-updated `session_state`; it does not re-invoke `st.chat_input`, so it cannot resend the message).
- `st.feedback("thumbs", ...)` is a real first-party Streamlit widget purpose-built for exactly this ("commonly used in chat and AI apps to allow users to rate responses" per its own docstring) — better than hand-rolling two `st.button` calls, and it comes with its own `AppTest` element type (`at.feedback[i].set_value(...)`), so it was testable for free.
- A documentation review pass (re-reading the shipped code as a user would, not just re-checking prose) found a second real bug the original `AppTest` suite didn't catch: `get_trace_url()` in the sidebar was called with no exception handling at all. Reproduced live by pointing a real server + real Streamlit process at an unreachable `LANGFUSE_HOST` and sending a message — the chat itself worked fine (span creation needs no network), but the moment the sidebar tried to resolve the trace URL, a raw `httpx2.ConnectError` traceback rendered directly in the UI. Checking further, an unreachable host isn't the only failure mode: wrong API keys raise a completely different type (`langfuse.api.commons.errors.UnauthorizedError`), and a slow network would raise `httpx2.TimeoutException`. Given the diversity of exception types from what is explicitly a non-critical debug convenience (the core chat feature already works without Langfuse), the fix catches broadly (`except Exception`) rather than enumerating SDK exception types one at a time — verified fixed by the same live reproduction, then locked in with a regression test using a plain `ConnectionError` specifically to prove the catch isn't narrowly matching the one exception type first observed.

**Limitations**: Feedback is a visual placeholder only — clicking thumbs up/down shows a toast and nothing is sent to Langfuse yet; that's Milestone 12's job. The UI has no memory across turns for the same reason the API doesn't (Milestone 7): each `/chat` call still carries only the latest message, so a real LLM provider would not "remember" an earlier turn in the same UI conversation, even though the UI visually displays the full transcript. `AnthropicProvider` was not exercised through the UI (still no `ANTHROPIC_API_KEY` in this environment).

---

## 2026-08-29 — M4: Synthetic travel tools, verified as real Langfuse `tool` observations

**Hypothesis**: Three typed tool functions (`search_destinations`, `search_hotels`, `get_destination_information`), backed by a small hand-authored dataset, each produce a genuine Langfuse **tool** observation (not a generic span) — and, called standalone with no parent trace active, each becomes its own root trace, exactly as `start_as_current_observation`'s context-propagation behavior (confirmed back in Milestone 1) would predict.

**Configuration**:
- `data/synthetic/destinations.json` (8 entries), `data/synthetic/hotels.json` (18 entries), generated by `scripts/generate_data.py`
- `scripts/smoke_test_tools.py` — 3 direct calls to the tools, no LLM or HTTP involved, no parent span

**Result**: Pass, verified visually in the UI, not just via non-error returns. The Tracing view's **Type** filter facet showed a genuine third observation type — `TOOL` (35 observations), alongside `SPAN` and `GENERATION` — each rendered with a wrench icon distinct from a generation's diamond. Opened `get_destination_information`'s trace directly: `Input: {"destination_id": "kyoto"}`, `Output: {"found": true}`, a two-node graph (`__start__ → get_destination_information → __end__`), `Environment: development`, `Release: 0.1.0` — all correctly propagated through the same `get_langfuse_client()` used everywhere else in this project, with zero tool-specific observability code beyond `as_type="tool"`.

**Interpretation**: `as_type="tool"` is a real, distinct Langfuse concept, not cosmetic naming (`tool.search_hotels` as a plain span name would have looked similar in a table view, but would not populate the dedicated `TOOL` filter facet the UI ships). Because each tool function only opens a `start_as_current_observation(...)` block and never touches trace-level plumbing (session_id, environment, propagation), the exact same code will nest correctly under a `travel_concierge_turn` trace the moment Milestone 5's agent calls it from within an active request — this was designed in, not verified live yet, since no caller exists until M5.

**Surprises**: None this milestone — the `as_type="tool"` literal was already known from Milestone 1's SDK introspection, and the filtering logic (tag overlap via set intersection, price-band ordering via a small lookup table) needed no debugging once written; all 15 unit tests passed on the first run.

**Limitations**: Not wired into `/chat` or any LLM decision loop — see `docs/RATIONALE_PER_MILESTONE.md` for why this is a deliberate M4/M5 boundary, not an oversight. The dataset is intentionally small (8 destinations, 18 hotels) and hand-authored, not randomly generated at scale; sufficient to exercise every filter combination in tests, not sufficient to stress-test performance or represent real-world travel inventory diversity.
