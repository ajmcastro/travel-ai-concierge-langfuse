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

---

## 2026-08-29 — M5: Agent/tools loop, verified as a nested trace and a genuine `agent` observation type

**Hypothesis**: A hand-written LangGraph `agent ↔ tools` loop — no `langgraph.prebuilt` — correctly routes between calling a tool and producing a final answer, terminates in both the zero-tool and one-tool cases, and produces the nested trace shape designed on paper: `travel_concierge_turn → agent → llm_call`, and (when a tool is needed) `→ execute_tools → search_hotels (tool) → agent → llm_call`.

**Configuration**:
- A toy 2-node LangGraph (`agent`/`tools`, TypedDict state, whole-list message replacement) run standalone first, before writing any real code, to validate the loop mechanics
- `scripts/smoke_test_agent.py` — calls both the direct-provider path and the graph path with the same message, in-process, printing both trace URLs for direct comparison
- Real HTTP round trip via `POST /chat` (both `AGENT_ENABLED=true` default and `=false`)

**Result**: Pass, verified at every layer. The toy graph confirmed the `agent → tools → agent → END` mechanic before any real node existed. The real graph, called via `/chat` over HTTP with `"find me a hotel"`, produced exactly the designed trace tree in the Langfuse UI: `travel_concierge_turn → agent → llm_call`, then `execute_tools → search_hotels` (wrench icon, real `tool` type), then a second `agent → llm_call`, all nested under one trace — not five separate traces. Separately confirmed `agent` is a genuine distinct Langfuse **Type** facet value (button labelled `AGENT agent (2/2)` in the UI's own trace-graph panel), the same principle Milestone 4 established for `tool`.

**Interpretation**: `as_type="agent"` and `as_type="tool"` compose the same way regular spans do — nesting is purely a function of which span is "current" in the OTel context when a child span opens, so a node written to work standalone (M4's tools, this milestone's toy graph) needs zero changes to work correctly once called from within a live request trace. This is the second time this exact property has paid off without modification, which is a stronger validation of the M1 design than either instance alone.

**Surprises**:
- Real bug, caught by hand-tracing before running anything: an early design used two independent "stop the loop" checks — `agent_node` withholding tools once `iterations >= agent_max_iterations` (to force a clean final answer), and `_route_after_agent` hard-stopping once `iterations >= agent_max_iterations` (to survive a misbehaving provider). Both compared the *same* threshold, but one checked pre-increment and the other post-increment iteration counts — meaning the routing hard-stop always fired one call before the tools-withholding branch could ever run, making it dead code. Fixed by changing the withholding check to `iterations + 1 >= max` (`"is this about to be the last allowed call?"`), then confirmed with two purpose-built fake providers: one that ignores `tools=None` entirely (proves the routing hard-stop is a real, provider-independent backstop) and one that respects it (proves the withholding branch is now actually reachable and produces real text, not an empty-content dead end).
- `AsyncAnthropic`'s tool-calling shapes (`ToolParam`, `ToolUseBlockParam`, `ToolResultBlockParam`) were introspected from the installed SDK before writing `_to_anthropic_messages`/`_to_anthropic_tools` — confirmed Anthropic has no native "tool" role; a tool result must be sent back as a *user* message containing a `tool_result` content block. This is unverified against the live API in this environment (no `ANTHROPIC_API_KEY` configured) but is pinned by 6 offline unit tests asserting the exact translated shape, plus a new integration test (`test_anthropic_provider_can_request_a_real_tool_call`) that will exercise it for real the moment a key is added.

**Limitations**: `MockProvider`'s tool-selection is a fixed keyword-trigger table (`"hotel"` → `search_hotels`, `"destination"` → `search_destinations`), not real reasoning — sufficient to exercise the loop mechanics deterministically, not a stand-in for judging real tool-selection quality (that starts with evaluation in Milestone 9+). The agent has no conversational memory across separate `/chat` calls, same limitation as every milestone since M2 (still Milestone 7's job) — within a single `/chat` call, though, the full tool round-trip now has real, working short-term memory (the tool result is genuinely in context for the final answer).

---

## 2026-08-30 — M6: Trace attributes verified against real OTel span output, not just "the code ran"

**Hypothesis**: `propagate_attributes(tags=..., metadata=..., version=...)` and `.update(level="ERROR", status_message=...)` produce the exact Langfuse-specific OTel span attributes documented in the SDK, and a tool call failing during argument binding (before its own `tool` span opens) is otherwise invisible at every observation level.

**Configuration**:
- Introspected `langfuse._client.attributes` for the real OTel attribute keys (`langfuse.trace.tags`, `langfuse.trace.metadata.<key>`, `langfuse.version`, `langfuse.observation.level`, `langfuse.observation.status_message`) before writing any assertions against them.
- A one-off experiment script: constructed a real `Langfuse(public_key=..., secret_key=..., span_exporter=InMemorySpanExporter(), tracing_enabled=True)`, opened a root span, called `propagate_attributes(tags=["a","b"], metadata={"k":"v"}, version="9.9.9")`, opened a child `tool`-type span, called `child.update(output="ok", level="ERROR", status_message="boom")`, flushed, and printed every finished span's `.attributes`.
- `tests/unit/test_trace_design.py`: same pattern, wired into `/chat` and the agent's `tools_node` via monkeypatched `get_langfuse_client()`, asserting on the real exported attributes for both the success and failure paths.

**Result**: Pass. The experiment script confirmed the exact attribute names and shapes on the first try (list values for tags, flattened dotted keys for metadata, plain string values for `version`/`level`/`status_message`) — no surprises in the attribute layer itself. `LangfuseResourceManager` (the class actually holding the OTel tracer + exporter) turned out to be a singleton keyed by `public_key` alone (confirmed by reading its `__new__`): passing a different `span_exporter` for a `public_key` already seen in the process silently returns the *first* instance, exporter and all. Each test therefore uses a unique throwaway `public_key` (e.g. `"pk-test-chat-attrs"`) rather than one shared client, to guarantee a fresh in-memory exporter per test.

The argument-binding hypothesis also confirmed directly: a fake provider that requests `search_hotels` with `arguments={}` reaches `agent/nodes.py`'s existing `except Exception` around `func(**call.arguments)` — proving that failure never reaches `search_hotels`'s own `with client.start_as_current_observation(...)` block at all, so before this milestone's `execute_tools`-level fix, nothing in Langfuse would have recorded it as an error at any level.

**Interpretation**: for observability code specifically, "the test passed" and "the attribute is actually on the span" are different claims — a test that only calls `.update(level="ERROR")` and checks no exception was raised would pass even if the SDK silently dropped the value (which it does, by design, for some invalid inputs per the `propagate_attributes` docstring's own validation notes). Asserting on `exporter.get_finished_spans()[i].attributes` closes that gap without needing live infrastructure.

**Limitations**: this environment's self-hosted Langfuse stack runs in v4 "events_only" mode, which returns an explicit error message for `GET /api/public/traces/{id}` rather than data — the usual "verify live, screenshot the UI" step from Milestones 1–5 wasn't available here for a final visual check, and the sandboxed browser pane in this environment cannot reach the host machine's `localhost` ports either. The in-memory-exporter tests verify the literal attributes Langfuse receives, which is a stronger check of the *code*, but don't confirm how the Langfuse UI itself renders `version`/`tags`/`level` — worth a manual look in a browser that does have access to `localhost:3001`.

---

## 2026-08-30 — M7: Real multi-turn memory, verified via a message-count-recording fake provider and a live 3-turn conversation

**Hypothesis**: replaying stored history into `messages` before each `/chat` call gives the agent genuine cross-turn memory (message count grows turn-over-turn within a session, resets for a different session, trims once `max_history_turns` is exceeded, and is skipped for any turn that raised) — and this is invisible to `MockProvider`'s own reply text, so proving it needs a different kind of test double.

**Configuration**:
- `RecordingProvider` (unit test only): a fake `LLMProvider` that returns `content=f"msg_count={len(messages)}"` instead of doing anything with the messages — turns "did history get replayed" into a plain, assertable integer instead of something you'd have to infer from prose.
- `tests/unit/test_chat_route.py` / `test_conversation_store.py` / `test_sessions_route.py`: session isolation, trimming at `max_history_turns`, and the failed-turn-not-remembered case, all offline.
- `scripts/smoke_test_conversation.py` (`make conversation-smoke-test`): 3 real turns over real HTTP against the mock provider (which can't demonstrate memory through its own text, since it only ever echoes the latest message), followed by a real `GET /sessions/{id}` call to inspect this app's own stored record independent of what Langfuse shows.

**Result**: Pass, at every layer including live. `RecordingProvider` confirmed the exact expected growth: turn 1 → `msg_count=2` (`[system, user]`), turn 2 in the same session → `msg_count=4` (`[system, user1, assistant1, user2]`), a different `session_id` → back to `msg_count=2`, and with `MAX_HISTORY_TURNS=1`, a third turn → `msg_count=4` (only the immediately preceding turn survives, not both). The live 3-turn smoke test round-tripped through the real server and Langfuse: `GET /sessions/{id}` afterward returned all 3 turns' content correctly, matching what was actually sent and received over HTTP.

**Interpretation**: `MockProvider._decide()` needed zero code changes to work correctly with real multi-turn history — it was already written to look only at `messages[-1]`/the last user message, so a longer list upstream is simply invisible to it. This is the same "nesting composes for free" property M4 and M5 found for Langfuse span nesting, showing up again here for a completely different mechanism (message-list length) — worth noting as a pattern, not a coincidence: code written to only care about the *tail* of a sequence doesn't need to know or care how long the sequence in front of it is.

**Surprises**: none in the sense of a bug found during implementation — the one genuine design risk (replaying a turn's internal tool-calling messages across a turn boundary, and whether that would violate Anthropic's tool_use/tool_result adjacency rules) was designed around up front by storing only the clean `[user, assistant]` pair per turn, rather than discovered by testing something broken. Recorded here because it was a real decision point, not because it produced a defect.

**Limitations**: this store is in-memory and per-process — running the API with multiple workers (e.g. `uvicorn --workers 4`) would silently fragment conversation history across whichever worker happens to handle each request, since nothing here is shared. Not exercised in this environment (single-worker `make serve` throughout this project), but worth stating plainly rather than leaving as an implicit assumption a reader could miss.

---

## 2026-08-30 — M8: Prompt fallback, labeling, and linking verified against the real SDK — including a rule the docstring doesn't fully spell out

**Hypothesis**: `client.get_prompt(name, label=..., fallback=...)` returns a usable local prompt (not an exception) when Langfuse is unreachable; `Settings.prompt_label` genuinely selects which version is fetched; and `propagate_attributes(prompt=...)` links a turn's generation to the prompt that produced it — all verifiable offline, without `make langfuse-up`.

**Configuration**:
- `tests/unit/test_prompts.py`: a real (non-mocked) `Langfuse` client pointed at `http://localhost:1` — a port that refuses connections instantly, no DNS/timeout wait — so the SDK's actual fallback/retry code path runs for real, not simulated.
- A one-off timing check (`pytest --durations=15`) run against the first draft of that file.
- Live: `make seed-prompts` against the real local Langfuse stack, then `/chat` with no `PROMPT_LABEL` set, then restarted with `PROMPT_LABEL=staging`, confirmed both requests succeed.

**Result**: Mostly pass on the first attempt, with two real findings along the way (see Surprises). Fallback behavior confirmed: `get_system_prompt()` against the unreachable host returns `.is_fallback=True` with the exact local fallback text, and — a detail worth stating because it's easy to assume otherwise — the fallback `PromptClient` still carries whatever `label` was requested (`.labels == ["staging"]` when `PROMPT_LABEL=staging`), even though nothing was actually fetched. Live: `make seed-prompts` created `travel-concierge-system` v1/v2; `/chat` used v1 by default and v2 after restarting with `PROMPT_LABEL=staging`, both producing normal responses (expected — `MockProvider` doesn't read prompt content at all, see Milestone 8's RATIONALE entry).

**Surprises**:
- **Real timing cost, found via `pytest --durations` before it became "the test suite is randomly slow" folklore**: the SDK's default `max_retries=2` with exponential backoff applies even when the underlying failure (`ConnectionRefusedError`) is instant — three tests hitting the unreachable-host client cost ~2.9s total, not milliseconds. Fixed with a test-only `Langfuse` subclass forcing `max_retries=0`/`fetch_timeout_seconds=1` on `get_prompt()` calls specifically for that unreachable client, cutting the file from ~2.9s to ~0.02s. Deliberately not changed in `get_system_prompt()` itself — production code keeps the SDK's real retry defaults, since a genuine transient network blip *should* retry, and this is purely a test-environment problem (an always-instantly-refused localhost port), not a production one.
- **"Fallback prompts are never linked" — a real, load-bearing rule found by reading `propagate_attributes`'s actual source** (`_extract_propagated_prompt` in `langfuse/_client/propagation.py`), not by re-reading the public docstring more carefully. The first version of the prompt-linking test used the fallback-triggering client and got a `KeyError` — no `langfuse.observation.prompt.name` attribute appeared on the generation at all. Reading the source (rather than assuming a bug in our own `propagate_attributes(prompt=prompt)` call) confirmed this is intentional: the SDK explicitly checks `is_fallback` and skips linking. Re-verified correctly with two tests: one confirming a fallback prompt produces no link, one confirming a plain `{"name": ..., "version": ...}` mapping (standing in for a genuinely-fetched, non-fallback prompt, per the docstring's own documented support for dict input) does produce the link.
- **`create_prompt()` silently also applies a `"latest"` label** in addition to whatever labels were explicitly requested — visible directly in `scripts/seed_prompts.py`'s own printed output (`labels=['production', 'latest']`). Not a problem for this app (which only ever requests `production`/`staging` by name), but worth knowing before writing code that assumes a prompt's `.labels` list contains only what was explicitly passed to `create_prompt(labels=...)`.

**Limitations**: `make prompts-smoke-test` only proves the retrieval/labeling/linking mechanism, not that v2 is actually better — `MockProvider` never reads system prompt content, so both versions produce byte-identical replies under the default offline setup. The real content comparison lives in `tests/integration/test_prompt_versions.py`, gated on both `make seed-prompts` having been run and a real `ANTHROPIC_API_KEY`, and even that test deliberately stops at "both versions are distinct and both work," not "one is better" — see Milestone 8's RATIONALE entry for why declaring a winner here would be exactly what the project spec warns against.

---

## 2026-08-30 — M9: Full evaluation pipeline run end-to-end against the real agent, live traces confirmed, honest MockProvider ceiling found in the results themselves

**Hypothesis**: a 39-case deterministic dataset run through the real `get_agent_graph()` (not a shortcut), scored by five Layer 1 evaluators, produces a coherent, correctly-aggregated report in both JSON and human-readable form — and, under the default `MockProvider`, a *specific, explicable* pattern of failures rather than either a suspiciously perfect score or an opaque wall of red.

**Configuration**:
- `make evaluate` run against the real local Langfuse stack (`make langfuse-up` already running), default settings (`LLM_PROVIDER=mock`, `AGENT_ENABLED` irrelevant since the runner always uses the agent graph directly).
- `make eval-ci` run separately to confirm the exit-code contract (0 on any evaluator failures, would be 1 only on a crashed case — none crashed).
- Inspected `data/evaluation/results/latest.json` directly (`python3 -m json.tool`) to confirm the machine-readable shape matches the human-readable summary numbers exactly.

**Result**: Pass, and the specific failure pattern confirmed the hypothesis rather than just "the code ran without crashing." 82 pass / 35 fail / 78 skip across 195 evaluator runs. Every failure traced back to one of two well-understood MockProvider limits: (1) its keyword trigger only fires on the literal substrings `"hotel"` or `"destination"` appearing in the message — cases like `beach-001` ("I want a beach vacation...") or `city-001` ("a city break...") contain neither word, so Mock never calls a tool at all, correctly flagged by `tool_usage_matches_expected`; (2) when `"hotel"` does appear, Mock's trigger is a single hardcoded call (`destination_id="algarve", family_friendly=True`) regardless of what destination or constraints the message actually named — e.g. `hotel-recommendation-002` ("hotels in Kyoto") correctly fails on `destination_id: expected 'kyoto', got 'algarve'`. Both are exactly the documented, intentional shape of MockProvider's fixed trigger table (see `providers/llm/mock.py`), not new information — but seeing the failure *reasons* line up precisely with that known shape, case by case, is a much stronger confirmation than "we expected some failures and got some failures."

One genuinely interesting result: `impossible-constraint-001` ("I want to book a hotel on the Moon") failed `tool_usage_matches_expected` by calling `search_hotels` — Mock's keyword match on `"hotel"` fires regardless of the request's actual plausibility, which is a fair, honest illustration of exactly why a keyword-trigger table isn't a stand-in for reasoning: it has no way to notice a request is absurd.

**Interpretation**: a pass/fail/skip evaluation report is only trustworthy if a reader can explain *why* the specific failures happened, not just that some fraction did. Because every failure here maps cleanly onto a documented, pre-existing MockProvider limitation rather than a surprise, this run is evidence the harness is measuring the right thing (agent behavior against real expectations) rather than something arbitrary (e.g., a bug in how tool arguments get extracted from the graph's return state) — the same principle M6's InMemorySpanExporter tests and M8's real-SDK-fallback tests both leaned on: verify against the real thing and let the *shape* of the result confirm or deny the hypothesis, not just its pass/fail bit.

**Limitations**: this run does not establish whether the evaluators themselves are *correct* in any absolute sense — that's what `tests/unit/test_evaluators.py`'s hand-built fixtures are for (deliberately not relying on this live run for that). It also doesn't tell us anything about real agent quality, by design — that requires `LLM_PROVIDER=anthropic`, not exercised in this environment for the same reason M8's real-provider prompt comparison wasn't: no `ANTHROPIC_API_KEY` configured here.

---

## 2026-08-30 — M10: Langfuse's own `run_experiment()` API discovered and verified with a toy dataset before any real code was written

**Hypothesis**: before assuming we'd need to hand-roll dataset-item creation, trace-to-item linking, and score submission ourselves, check whether the installed Langfuse SDK already has a purpose-built mechanism for "run a dataset through a task function and record evaluator scores against each item's trace."

**Configuration**:
- Introspected `Langfuse`/`DatasetClient` for dataset- and experiment-related methods, found `create_dataset`, `create_dataset_item`, `get_dataset`, and — the significant one — `run_experiment` (module `langfuse.experiment`, with `TaskFunction`/`EvaluatorFunction`/`Evaluation`/`ExperimentResult` types).
- A standalone toy script (not part of the app): `create_dataset("toy-dataset-m10-experiment")` → `create_dataset_item(id="toy-item-1", ...)` → `get_dataset(...).run_experiment(task=toy_task, evaluators=[toy_evaluator])`, where `toy_task` deliberately opened its own nested `start_as_current_observation` span, against the real local Langfuse stack.
- Full live round trip: `make sync-eval-dataset` (39 real cases) → `make experiment-prompt-v1` → `make experiment-prompt-v2`, then a real 409-conflict repro (see Surprises) while writing the integration test.

**Result**: Pass, and the toy script answered every open design question in one shot. `run_experiment` (despite accepting an `async def task`) is itself a plain **synchronous** method — calling it with `await` raises `TypeError: object ExperimentResult can't be used in 'await' expression`; the SDK manages the task's own event loop internally. The nested span opened inside `toy_task` caused no errors and the run still produced a real `dataset_run_url` — confirming nested tracing composes correctly with the SDK's own dataset-run linking without any special handling on our side. `result.format()` produced a genuinely useful human-readable summary (including automatic per-evaluator score averaging) with zero rendering code of our own.

The full 39-case run against `MockProvider` reproduced the exact same explicable failure pattern M9 already found locally (`tool_usage_matches_expected` averaging 0.513, `tool_arguments_satisfy_constraints` at 0.312, both prompt-v1 and prompt-v2 runs numerically identical since Mock ignores prompt content) — a second, independent confirmation (via a completely different code path — the Langfuse SDK's own scoring, not our local `report.py`) that M9's evaluators measure what they claim to measure.

**Surprises**:
- **`make help`'s target-filter regex has excluded digits since it was written**: `grep -E '^[a-zA-Z_-]+:.*?## .*$$'` — no target before this milestone had ever contained a digit, so this silent gap was never exercised. `experiment-prompt-v1`/`experiment-prompt-v2` (both containing `1`/`2`) simply didn't appear in `make help`'s output at all — no error, no warning, just absence. Root-caused by testing the grep pattern directly against the bare target name (`echo 'experiment-prompt-v1' | grep -E '^[a-zA-Z_-]+$'` → no match) rather than assuming the new targets were somehow malformed. Fixed by widening the class to `[a-zA-Z0-9_-]+`.
- **Dataset item ids are unique per Langfuse *project*, not per dataset** — confirmed the hard way, not from documentation. The integration test's first version used a fixed item id (`"hotel-case"`) alongside a randomized *dataset* name per run; running the test twice produced a real `409 LangfuseConflictError` from the actual API on the second run — `"item ids are unique per project across datasets... Use a different id or target dataset <id>"` — because the id collided with the leftover item from the first run's now-orphaned dataset. Fixed by suffixing item ids with the same per-run random token used for the dataset name.

**Limitations**: `experiment-prompt-v1`/`-v2` only demonstrate the *mechanism* under `MockProvider`, same limitation as M9's local report — both runs score identically since Mock never reads prompt content. A real prompt-v1-vs-v2 quality comparison needs `LLM_PROVIDER=anthropic`, not exercised here (no `ANTHROPIC_API_KEY` configured in this environment, consistent with every prior milestone's real-provider gap).
