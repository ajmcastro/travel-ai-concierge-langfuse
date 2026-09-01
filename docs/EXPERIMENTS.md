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

---

## 2026-08-31 — M11: FakeJudgeProvider's derived scores actually reflect the underlying evaluator signal, verified end-to-end in both evaluation surfaces

**Hypothesis**: `FakeJudgeProvider`'s scores, though fake, should still be *coherent* with Milestone 9's own evaluator outcomes (since that's literally what they're derived from) — and the same `JudgeProvider` should produce identical scores whether reached through `make evaluate-judged` (the local report) or `run_experiment.py --with-judge` (the Langfuse-linked run), since both call the exact same `judge()` method.

**Configuration**:
- `uv run python scripts/run_evaluation.py --with-judge` — full 39-case run, default `judge_provider="fake"`.
- `uv run python scripts/run_experiment.py --run-name judge-smoke-test --with-judge` — same 39 cases, same fake judge, via the Langfuse experiment path instead.
- Directly inspected `data/evaluation/results/latest-judged.json` for the raw per-case rationale strings.

**Result**: Pass, and the two surfaces agreed exactly, as they should given they share one code path — both runs' average scores: `relevance 3.54`, `helpfulness 5.00`, `groundedness 5.00`, `constraint_satisfaction 4.15`, `itinerary_coherence 3.00 (n=2)`. `itinerary_coherence`'s count of exactly 2 confirms the dimension-applicability filter is working (only the dataset's 2 `itinerary_planning` cases got it, not all 39). `helpfulness`/`groundedness` landing at a flat 5.00 makes sense once traced back to their derivation: `response_is_nonempty` passes on effectively every case (MockProvider never returns a blank response) and `response_references_tool_result` only ever fails when a tool actually ran and ignored its own results, which doesn't happen in this dataset under Mock — so a perfect average here is the *expected* shape of the derivation, not a red flag.

**Interpretation**: because `FakeJudgeProvider`'s rationale field names the exact M9 evaluator + outcome it derived each score from (e.g. `"...'tool_usage_matches_expected' (pass), 'response_references_tool_result' (pass)..."`), a single case's judged output is independently auditable against the very evaluators it's built from — the same "explain, don't just assert" discipline this project has used for every other test double (`MockProvider`'s own docstring, M9's evaluator `detail` strings).

**Surprises**: none — this was designed to be traceable and it was, on the first real run.

**Limitations**: this run says nothing about whether the fake judge's *derivation logic* is a good proxy for what a real judge would say (it isn't meant to be — see `evaluation/judge.py`'s own docstring). The real `AnthropicJudgeProvider` — including the stochasticity check in `tests/integration/test_llm_judge.py` — is not exercised in this environment (no `ANTHROPIC_API_KEY` configured, the same gap as every prior milestone's real-provider testing).

---

## 2026-08-31 — M12: Human feedback verified end-to-end — real HTTP, real score write, and a live browser walkthrough

**Hypothesis**: `POST /feedback`, given a `message_id` from a prior `/chat` response, resolves it back to a real `trace_id` and successfully writes a Langfuse score — and the Streamlit UI's `st.feedback` widget, wired to that route, behaves correctly both on the click that submits feedback and on every later, unrelated rerun (where a naive implementation would resubmit the same rating).

**Configuration**:
- `make serve` (real uvicorn) — two sequential real HTTP calls: `POST /chat`, then `POST /feedback` with the returned `message_id`, via `curl`.
- `make test-integration` — `tests/integration/test_feedback_score.py`, a real `create_score()` + `flush()` round trip against `make langfuse-up`.
- `mcp__Claude_Browser__preview_start` against a new `.claude/launch.json` `"ui"` config running `make ui` (`streamlit run ui/streamlit_app.py --server.headless true`) — a full interactive browser session: sent a chat message, clicked thumbs down, typed and sent an optional comment, then sent a second, unrelated chat message to check the feedback widget didn't resubmit.
- `tests/unit/test_feedback_route.py` (`_RecordingLangfuseClient`, 8 cases) and `tests/unit/test_ui_chat.py`'s 5 new feedback tests (`AppTest`).

**Result**: Pass, on all four verification paths. The curl round trip returned `{"recorded": true}` and a `201`; the integration test passed in 3.38s against real Langfuse. In the browser: the thumbs-down click showed the optional comment box immediately (no page reload — same script-rerun mechanism as the rest of the UI); typing and submitting a comment sent a second `/feedback` call carrying `thumbs_up: false` and the comment together, matching `test_score_id_is_deterministic_per_message_so_a_followup_comment_updates_it`'s assumption about what a same-`score_id` follow-up looks like from the client's side; sending a second, unrelated chat message afterward did **not** re-fire `/feedback` — confirming the `feedback_submitted` session-state guard actually works live, not just under `AppTest`.

**Interpretation**: the `message_id`/`trace_id` split (see `docs/RATIONALE_PER_MILESTONE.md`, Milestone 12) works as designed under a real HTTP round trip, not just inside `TestClient` — `find_turn()` correctly resolves an opaque id the client never has to treat as meaningful. `st.feedback`'s stateful-widget behavior, anticipated from general Streamlit widget knowledge *before* writing the guard code, was confirmed rather than discovered — both by the `AppTest` regression test (passed on first write) and now by this live walkthrough, which is a stronger claim than a simulated harness alone.

**Surprises**:
- `mcp__Claude_Browser__preview_start`, using a `.claude/launch.json` config file, successfully opened and drove a real, interactive view of `localhost:8501` — screenshots, clicks, typing, all working. This is worth recording specifically because Milestone 6's own `EXPERIMENTS.md` entry (browser-based UI verification, if attempted then) had found `mcp__Claude_Browser__navigate` unable to reach `localhost` directly; `preview_start` with a launch config succeeds where a bare `navigate` call did not. Future milestones needing live browser verification of a local dev server should use this approach first.
- After submitting a comment, the comment form's text input and "Send comment" button remained visible in that same screenshot rather than disappearing immediately. Investigated rather than assumed correct: this is expected Streamlit behavior, not a bug — the form's own non-button content is drawn during the script pass *before* the submit button's click-handling and the resulting state change are reflected, so the form only actually disappears on the *next* rerun. Confirmed by triggering one more rerun (sending another chat message) and observing the form correctly gone at that point.

**Limitations**: score-level upsert-by-`score_id` (does a second `create_score()` call with the same `score_id` update the first, rather than create a duplicate?) could not be verified by reading scores back — this deployment's "events_only" Langfuse mode has no read API (the same limitation M1 first found for traces, and M10 worked around for dataset items by observing write-time conflict errors instead, which scores don't raise). The deterministic `score_id` is shipped as best-effort correct behavior, documented as unverified in both the route's docstring and `docs/RATIONALE_PER_MILESTONE.md`, not confirmed by this or any other test in this environment. `AnthropicProvider` was not exercised through this flow (still no `ANTHROPIC_API_KEY`, the same gap as every prior milestone). **This "Result: Pass" turned out to be checking the wrong thing — see the following entry.**

---

## 2026-08-31 — M12 follow-up: the "Pass" above was wrong — no score was actually reaching Langfuse

**What happened**: after the milestone report above was delivered, the user tested it live in the browser — sent a message, clicked thumbs up, added a comment, thumbs down on a second message — then opened both traces directly in the Langfuse UI. Neither showed a score. Nothing in the entry above caught this, despite four separate "verification paths," because every one of them checked that the write *call* succeeded (`{"recorded": true}`, `flush()` not raising, no exception in the browser) and none of them checked that the write actually *landed*.

**Root cause, found by direct reproduction**: `POST /feedback` called `create_score(trace_id=turn.trace_id, session_id=request.session_id, ...)` — both at once. Calling Langfuse's `/api/public/ingestion` endpoint directly with that same shape returns a real `400`:

```
"Provide exactly one of the following: traceId (with optional observationId), sessionId or
datasetRunId. ObservationId requires traceId."
```

The SDK's `create_score()` accepts both as keyword arguments without complaint — its batch export runs on a background thread, and when that thread's own POST to `/api/public/ingestion` comes back with per-item errors, it only logs them (`langfuse:ERROR API errors occurred: Bad request...` — visible in the server's own stderr, easy to miss), it never raises anything the caller could catch. `client.flush()` returning cleanly proves the batch was *sent*, not that it was *accepted*. This is exactly why `inspect.getsource`-checking the SDK signature (the project's standard verification habit since M1) wasn't enough this time: it can only tell you what the *client* will let you call, never what the *server* will do with it.

**Fix**: `api/routes/feedback.py` now scores `trace_id` only. Nothing is lost — the scored trace already carries `session_id` from when the turn itself was created (`chat.py`, Milestone 2), so a score is still findable per-session in Langfuse's UI; confirmed live (see Verification below), not assumed.

**Verification, done properly this time**:
- Re-ran the exact curl sequence from the entry above. This time the server log showed no `langfuse:ERROR` line.
- Opened the resulting trace directly in a real browser (`mcp__Claude_Browser__navigate` to the trace URL, not just `preview_start` against localhost): the trace tree shows `user_thumbs: 1.00` directly under the trace name, the trace header shows `Session: debug-session-2`, and the Scores tab lists the score with its timestamp, value, and comment (`"fixed now"`) — the first time in this milestone a score was actually *seen* in Langfuse, not just inferred from a non-error response.
- `tests/integration/test_feedback_score.py` gained a second test that bypasses the SDK entirely and posts the route's exact score shape straight to `/api/public/ingestion`, asserting `response.json()["errors"] == []` — the one place in this "events_only" deployment a rejected score is actually observable synchronously, and a check the original integration test never performed.
- `tests/unit/test_feedback_route.py`'s recording-client test now also asserts `"session_id" not in score`, so a regression back to sending both would fail a unit test, not just require a human to notice a missing UI element again.

**Interpretation**: the general lesson isn't specific to Langfuse — "the call didn't raise" and "the call succeeded" are different claims, and a fire-and-forget async/batched API can make the gap between them invisible to every layer of testing except a human looking at the actual result. `docs/architecture.md` calls this out explicitly for UI work ("Type checking and test suites verify code correctness, not feature correctness"); this is the same principle showing up on the backend side of an async write path instead.

**Separately, the same live session also addressed the comment-form UX question the user raised**: the form staying visible for one extra rerun after "Send comment" was already investigated and explained in the entry above (Streamlit draws the form before that click's own state change takes effect). It wasn't wrong, but it was avoidable — `ui/streamlit_app.py` now calls `st.rerun()` right after a successful comment submission, the same pattern already used after a chat response, so the form disappears on the very next render instead of waiting for an unrelated interaction. `test_optional_comment_sent_after_feedback_reuses_the_recorded_rating` now also asserts `len(at.text_input) == 0` immediately after that click, so a regression back to the lingering-form behavior would fail a unit test, not require a human to notice it again.

**A further follow-up, from the user actually reading the Scores tab**: after finally seeing `user_thumbs` in the UI, the user asked why its **Observation** and **Session** columns are empty. Both are expected, and by design, not further bugs: **Observation** is empty because the route never passes `observation_id` (the feedback is about the whole response, not one internal span — nothing to attach it to more specifically); **Session** is empty because of the same single-identifier ingestion constraint this entry is about — the *score* itself never carries `session_id`, only `trace_id`. Confirmed directly by reading the Scores table's raw data (`get_page_text`, not just a screenshot): rows for M9's deterministic evaluators (`response_is_nonempty`, `tool_usage_matches_expected`, etc., which score a specific observation) show both Trace *and* Observation populated, while every `user_thumbs` row shows Trace only — exactly matching what each code path actually sends. The score is still reachable per-session in the UI (the trace it's attached to already carries `session_id` from creation), just not via that particular column.

---

## 2026-08-31 — M13: re-reading the existing 39-case dataset through a trajectory lens, before writing any new code

**Hypothesis**: before designing Milestone 13's trajectory metrics, check whether the *existing* 39-case dataset (built for Milestone 9's Layer 1 pass/fail checks) already contains real, live instances of the spec's own "good answer ≠ good trajectory" and "poor answer despite reasonable trajectory" claims — rather than assuming new dataset cases would be needed to demonstrate either.

**Configuration**: `uv run python scripts/run_evaluation.py --ci` against the unmodified dataset, `LLM_PROVIDER=mock` (default), read every reported failure by hand and cross-referenced each against the case's own `message`/`expected_tools`/`expects_clarification`.

**Result**: two real, live divergence cases found, no new dataset entries needed. `requires-clarification-002` (*"I want to book a hotel."*, `expected_tools=[]`, `expects_clarification=True`) and `impossible-constraint-001` (*"I want to book a hotel on the Moon."*, `expected_tools=[]`) both contain the literal keyword `"hotel"`, which `_MOCK_TOOL_TRIGGERS` (`providers/llm/mock.py`) matches regardless of the rest of the sentence — so `MockProvider` calls `search_hotels` in both, producing `tool_usage_matches_expected: fail` (and, for the first, `clarifying_question_when_expected: fail` too). In both cases the resulting text — `"[mock] Based on the tool result: [...]"` — is non-empty and contains the raw tool JSON verbatim, so `response_is_nonempty` and the groundedness proxy both **pass**. That is a live, unmodified-dataset instance of "good answer ≠ good trajectory," confirmed by an actual run, not constructed for the demonstration.

Checking the *opposite* direction empirically: across all 39 cases, `response_is_nonempty` and the groundedness proxy **never fail**, in any case, for any reason. Every case that fails does so on a tool-selection or clarification check — never on the two evaluators this milestone treats as the "final answer" axis. This is the concrete, measured confirmation (not just a read of `mock.py`'s source) that "poor answer despite reasonable trajectory" cannot occur under `LLM_PROVIDER=mock`: `_decide()` only ever produces text by echoing the input message or echoing a tool's own JSON output, so a correct trajectory and a non-empty, tool-grounded answer are structurally the same event under Mock — they cannot come apart.

**Interpretation**: this changed the actual implementation plan. Rather than authoring new dataset cases specifically to manufacture a "good answer ≠ good trajectory" example (the initial instinct), the milestone surfaces the divergence that was already there, via a new report (`trajectory_report.py`'s `classify_divergence()`) rather than new fixtures. For the other quadrant, since it's now confirmed — not assumed — to be unreachable live, it's demonstrated with one clean, explicitly-labeled hand-built fixture in `tests/unit/test_trajectory.py` instead of a live case, and the trajectory report's own rendered output says so directly rather than silently having zero examples with no explanation.

**Verification of the built metrics**: `uv run python scripts/run_evaluation.py` on the real 39-case run reported `average_tool_precision=0.90`, `average_tool_recall=0.59`, `average_agent_steps=1.51`, `16 aligned / 23 good_answer_poor_trajectory / 0 poor_answer_good_trajectory` — the 0 in the last bucket matches the empirical finding above exactly, not a coincidence. Also verified against a real Langfuse dataset run (`run_named_experiment(run_name="m13-manual-check")`, then opened the resulting `dataset_run_url` in a real browser): `trajectory_tool_recall`, `trajectory_agent_steps`, `trajectory_healthy`, and (where applicable) `trajectory_tool_precision` all appear as real Evaluations on the run, alongside Layer 1's existing scores, confirming the new `_trajectory_evaluator` composes correctly with the SDK's `run_experiment()` the same way M10/M11's adapters already do.

**Surprises**: none in the sense of a bug — the interesting finding here was methodological (re-reading the existing data before designing new code) rather than a mistake caught after the fact. Worth carrying forward as a habit for later milestones: check what the data already shows before assuming new fixtures/cases are needed.

**Limitations**: everything above is under `LLM_PROVIDER=mock`. A real reasoning model could plausibly repeat tool calls, call unnecessary ones alongside a coherent answer, or produce a fluent-but-wrong response despite a correct trajectory — none of which Mock can do by construction. Not exercised in this environment (no `ANTHROPIC_API_KEY`), the same gap as every prior milestone's real-provider testing.

---

## 2026-08-31 — Experiment C / M14: single-agent vs explicit planning step, measured locally because Langfuse's own read API isn't available here

**Hypothesis**: `AGENT_MAX_ITERATIONS=1` forces the agent to answer every case in exactly one LLM call, never offering a tool — comparing that against the default (`5`, up to two real steps for tool-requiring cases) should show a genuine, measurable quality-vs-cost trade-off, entirely under `LLM_PROVIDER=mock`, using locally-captured token/latency numbers rather than anything read back from Langfuse.

**Configuration**:
- `uv run python scripts/run_cost_latency_experiment.py` (`make cost-latency-experiment`) — runs the full 39-case dataset twice, once per config, in one process (env var + `get_settings.cache_clear()` between runs).
- `UsageTrackingProvider` (`evaluation/cost_latency.py`) installed via a scoped monkey-patch of `agent.nodes.get_llm_provider`, restored immediately after each case.
- Quality reused unchanged from Layer 1 (`evaluators.py`, M9) and Milestone 13's trajectory-healthy rate — no new quality logic written for this experiment.

**Result**: Pass, and a real, interpretable trade-off:

```
metric                                   single-step    multi-step (default)
----------------------------------------------------------------------------
cases                                             39                      39
quality (Layer 1 pass rate)                    54.2%                   70.1%
trajectory healthy rate                         2.6%                   41.0%
p50 latency (ms)                               0.087                   0.183
p95 latency (ms)                               0.142                   0.260
avg LLM calls / case                            1.00                    1.51
avg input tokens / case                         43.1                    95.0
avg output tokens / case                        12.1                    38.5
avg estimated cost / case                        n/a                     n/a
```

Multi-step wins meaningfully on quality (+15.9 percentage points on Layer 1 pass rate, +38.5 points on trajectory health) at a real, measurable cost: p50 latency 2.1x single-step's, tokens 2.42x per case. Cost itself is `n/a` for both — `MockProvider`'s `"mock-echo-v1"` has no entry in `MODEL_PRICING`, correctly, since it has no real inference cost.

**Interpretation**: the trajectory-healthy-rate gap (2.6% -> 41.0%) is far larger than the Layer 1 pass-rate gap (54.2% -> 70.1%) — expected, and worth naming explicitly: Layer 1's `tool_usage_matches_expected` only fails when a tool *was* expected and wasn't called (or vice versa) for cases where the trigger keyword happens to be present; trajectory health additionally penalizes clarification-direction mistakes and (structurally, though not observed under Mock — see M13) repeated calls, so it's a strictly stricter bar. Both numbers move in the same direction here, which is itself a useful sanity check that the two metrics aren't measuring contradictory things.

**Surprises**: the comparison table's first real render put two config-name columns directly adjacent with no separating whitespace at all — `"single-step (max_iter=1)multi-step (max_iter=5, default)"` — because the column-width constant (`22`) was picked to look reasonable for short example names during writing, and the actual config names used were longer. Caught immediately by running the script for real against the full dataset before writing any tests for the renderer, not by guessing at a safe width. Fixed by computing the column width from the actual longest config name plus a guaranteed 2-space gap, and pinned with `test_render_comparison_header_separates_long_config_names`, which deliberately uses names longer than the old fixed width so this specific class of regression can't silently return.

**Limitations**: latency numbers here (fractions of a millisecond) reflect `MockProvider`'s near-instant synthetic responses, not real LLM latency — useful for proving the p50/p95/measurement machinery itself works correctly, not for drawing real performance conclusions. Cost is `n/a` throughout for the same reason. A live "small model vs larger model" comparison (Experiment B) needs `LLM_PROVIDER=anthropic`; not exercised here, no `ANTHROPIC_API_KEY` configured, the same gap as every prior milestone's real-provider testing — `MODEL_PRICING`'s tiers and `estimate_cost_usd()` are unit-tested and ready for that case, just unexercised against a real run.

---

## 2026-08-31 — M14 follow-up: making the comparison visible inside Langfuse, not only in the script's own report

**What happened**: after the milestone report above, the user asked directly whether Langfuse was being used at all for this experiment, and how to check — a fair question the report hadn't actually made easy to answer. Checking live rather than answering from memory: a real trace from the comparison run, opened in Langfuse's UI, had tags `evaluation` + the case's `query_class` and nothing else — no way to tell it apart from any other evaluation trace, let alone tell which of the two configs produced it. Langfuse's own built-in "Langfuse Cost Dashboard" (`Dashboards`) was also checked directly: its "Cost by Model Name" chart shows `mock-echo-v1` at a flat `$0.00`, confirming Langfuse's own native cost tracking has exactly the same "no pricing data for this model" gap our own `estimate_cost_usd()` already reports as `n/a` — a nice, unplanned cross-check that the two independent cost stories agree.

**Fix, verified live in both directions**:
- `run_case()` gained `extra_tags`/`extra_metadata` (both default `None`, additive only); `run_case_with_metrics(case, config_name=...)` now passes `["cost-latency-experiment", config_name]` / `{"cost_latency_config": config_name}` through. Ran one case directly (`config_name="single-step"`), captured its real `trace_id`, opened it in the browser: **Tags: `evaluation`, `demo`, `cost-latency-experim...`, `single-step`**; **Metadata: `cost_latency_config: "single-step"`** — both present, exactly as intended.
- A new opt-in `--push-to-langfuse` flag additionally pushes each config as a named Langfuse Dataset Experiment run, reusing `run_named_experiment()` (Milestone 10) completely unchanged. Ran it for real (`make sync-eval-dataset` first, then the flag): got two real `dataset_run_url`s back. Opened one, then used Langfuse's own "Experiment selection" to add the second as a comparison alongside the baseline — both configs' per-case scores appeared side by side in the same table, including the M13 trajectory scores (`trajectory_healthy`, `trajectory_tool_recall`, etc.) riding along automatically since `_trajectory_evaluator` was already wired into `run_named_experiment()` unconditionally before this milestone even started. Exactly the native, no-code-needed comparison UI Milestone 10 already established for prompt v1 vs v2.

**Interpretation**: this is a case where a limitation reasoned through and written down (docs/RATIONALE_PER_MILESTONE.md's original M14 entry called the missing trace tags "a deliberate, documented gap, not an oversight") turned out to be a real usability problem once a person actually tried to use it — documenting a trade-off honestly doesn't make it the right trade-off. The fix cost two new optional keyword arguments on one already-shared function, guarded by regression tests proving the addition is strictly additive (see below) — smaller than the original design discussion had implied it would be.

**Tests added**: `tests/unit/test_evaluation_runner.py` gained two `InMemorySpanExporter`-based tests (the same real-attribute-verification pattern `test_trace_design.py` established for Milestone 6) — one proving `extra_tags`/`extra_metadata` merge additively with the base `["evaluation", query_class]` tagging, one proving that omitting them reproduces the exact prior behavior byte-for-byte, so no other caller (`run_evaluation.py`, `experiment.py`) is affected. `tests/unit/test_cost_latency.py` gained two more, spying on `run_case()` to confirm `run_case_with_metrics()` computes the right `extra_tags`/`extra_metadata` from `config_name` (and passes nothing extra when it's omitted). 208 tests total pass (was 204).

**Limitations**: `--push-to-langfuse`'s traces don't carry local cost/latency metrics (no `UsageTrackingProvider` in that path) — the printed comparison report remains the one authoritative source for those numbers; the Langfuse-native view is for browsing the same 39 cases per config, not a second measurement of the same thing. Its own per-item "Latency" figure (89ms, observed live) is real but not comparable to the script's own p50/p95 numbers (tenths of a millisecond) — it includes Langfuse SDK/network overhead the local measurement never sees, a genuinely different quantity, not a discrepancy to reconcile.

---

## 2026-08-31 — M15: fault injection lab — real trace evidence for every named failure mode, plus one real bug found by reading the SDK source first

**Hypothesis**: before writing any fault-injection code, check what the existing error-handling paths (M2, M6) actually cover for each of the spec's six named fault types, and whether the resulting Langfuse traces actually show what a debugging engineer would need — not by reasoning about the code, but by reading the real SDK source and then running real faults through the real agent graph.

**Configuration**: `uv run python scripts/fault_injection_lab.py` (`make fault-injection-lab`) — runs one message ("find me a hotel") through the real agent graph under each fault, plus a direct `search_hotels("atlantis")` call for "no results" and a `LANGFUSE_HOST=http://localhost:1` run for "Langfuse unavailable". `LLM_PROVIDER=mock` (default).

**Result — real output from this environment**:

```
=== Baseline (no fault) ===
  Result: HTTP 200 (would-be) — the request completed

=== LLM timeout ===
  Result: HTTP 500 (would-be) — raised TimeoutError: simulated llm timeout

=== LLM provider unavailable ===
  Result: HTTP 500 (would-be) — raised ConnectionError: simulated llm provider unavailable

=== Malformed model output (tool call missing arguments) ===
  Result: HTTP 200 (would-be) — the request completed
  Response: [mock] Based on the tool result: Error executing search_hotels: search_hotels()
            missing 1 required positional argument: 'destination_id'

=== Tool exception (travel provider error) ===
  Result: HTTP 200 (would-be) — the request completed
  Response: [mock] Based on the tool result: Error executing search_hotels: simulated tool
            exception in 'search_hotels'

=== Tool timeout ===
  Result: HTTP 200 (would-be) — the request completed
  Response: [mock] Based on the tool result: Error executing search_hotels: simulated tool
            timeout in 'search_hotels'

=== No search results (real tool call, no fault injected) ===
  Result: HTTP 200 (would-be) — 0 hotels found (empty is not an error)

=== Langfuse unavailable (LANGFUSE_HOST=http://localhost:1) ===
  Result: HTTP 200 (would-be) — completed in 4.9ms despite Langfuse being unreachable
```

Every tool-layer fault (malformed output, tool exception, tool timeout) recovered to a real HTTP 200 with a coherent (if apologetic) answer. Both LLM-layer faults produced a clean HTTP 500. "No results" and "Langfuse unavailable" needed no fault injection at all — both were already the system's normal behavior.

**A real bug found and fixed as a direct result of this investigation, before the lab script was even written**: reading Langfuse's own `_start_as_current_otel_span_with_processed_media` source (not assuming, per this project's standing discipline since M1) showed it's a bare `try/finally` with no `except` — it never marks a span `level="ERROR"` just because an exception propagated through it. `AnthropicProvider.complete()`'s own `generation.update(...)` call sits *after* the real API call, so a real timeout or connection failure would leave the `llm_call` generation span completely unmarked — only the root trace (via `chat.py`'s M6-era `try/except`) would show anything went wrong. Fixed by wrapping both `AnthropicProvider` and `MockProvider`'s completion calls in `try/except`, marking the generation `ERROR` before re-raising — the same pattern `tools_node` already used for tool failures since M6, just missing from the LLM-call layer until now. Verified live: opened the real trace from the "LLM timeout" run above — the `llm_call` generation now shows a red **Error** banner reading `simulated llm timeout`, exactly where it previously would have shown nothing.

**A second, smaller finding — this time in the test suite, not the app**: writing a `/chat`-level test to prove tool-layer recovery required patching `agent.nodes.get_langfuse_client` in addition to `chat.py`'s own copy — omitting it silently sent `agent`/`execute_tools` spans to the real, differently-configured cached Langfuse client instead of the test's `InMemorySpanExporter`, so the assertion failed with a `KeyError` rather than a wrong value. `test_trace_design.py`'s own existing chat-level tests never hit this because they never assert on those child spans — not a bug there, just a sharp edge the new resilience tests had to work around and now document.

**Verification of the single most emphasized resilience claim in the spec** ("Langfuse unavailable... This last case is particularly important"): `tests/integration/test_langfuse_unavailable.py` points `LANGFUSE_HOST` at `http://localhost:1` (a closed local port — fast ECONNREFUSED, no slow DNS lookup) and confirms `/chat` still returns 200 in under 2 seconds, non-debug mode. Ran it live: 1.61s total test time, response returned before the SDK's own background retry/backoff log lines even appeared. This claim had been asserted in ADR-004 since Milestone 1 but never actually end-to-end tested until this milestone.

**Interpretation**: the real, substantive finding of this milestone is the asymmetry between tool-layer and LLM-layer failures — one recovers automatically via the agent loop's own second chance, the other doesn't and shouldn't be assumed to. Documenting that plainly (in `docs/DEBUGGING_WORKFLOWS.md`) is more useful to someone debugging a real incident than a uniform "the system degrades gracefully" claim would have been.

**Limitations**: `tool_timeout` doesn't exercise a real execution-preemption mechanism, because none exists — today's tools have no real blocking I/O to time out on (see RATIONALE_PER_MILESTONE.md for why this wasn't built anyway). "Travel provider error" has no real second provider to demonstrate a fallback *to* — this project has only ever had the local synthetic data source; that specific spec example (M18's territory) isn't fully exercisable here yet.

---

## 2026-08-31 — M16: observability-driven debugging exercise — a real agent regression, diagnosed from a Langfuse trace, then fixed and measured

**Where the injected bug had to live, and why**: the spec's own examples ("poor tool description causing wrong tool selection," "prompt causing excessive tool calls," "context causing hallucination") all describe failures in an LLM's *reasoning*. This deployment has no `ANTHROPIC_API_KEY` (the same gap noted in every prior milestone's real-provider testing), so the only reasoning this repo can exercise fully offline and reproducibly is `MockProvider`'s keyword-trigger table — already documented since Milestone 1 as "a test double for reasoning, not an attempt at one." Rather than fabricate a bug nobody would actually write, the bug injected here is the realistic version *for this specific mechanism*: a naive trigger-table edit, the direct analogue of a naive prompt or tool-description edit in a real system, with the identical failure shape — an over-broad match that fires when it shouldn't.

**The bug, as it would really happen**: `culture-001` ("I want a trip full of culture, museums, and history.") was already failing `tool_usage_matches_expected` — neither "hotel" nor "destination" appear in the message, so `MockProvider` never called `search_destinations` at all. A plausible fix: add `"trip"` as a second trigger keyword, copying the existing `"destination"` trigger's shape (`("search_destinations", {"tags": ["beach"]})`) verbatim.

```python
_MOCK_TOOL_TRIGGERS: dict[str, tuple[str, dict[str, object]]] = {
    "hotel": ("search_hotels", {"destination_id": "algarve", "family_friendly": True}),
    "destination": ("search_destinations", {"tags": ["beach"]}),
    "trip": ("search_destinations", {"tags": ["beach"]}),   # <- the bug
}
```

**Generating traces and running the eval**: `make evaluate` immediately after this change looked, at the aggregate level, like an *improvement* — overall Layer 1 pass count went **82 → 83** (out of 195 evaluator runs). That's the trap this milestone is really about: an aggregate pass count is not enough to catch a regression that trades one failure for a different one.

Per-case diff told the real story:

```
culture-001          | tool_calls [] -> ['search_destinations']
   tool_usage_matches_expected            fail -> pass
   tool_arguments_satisfy_constraints     skip -> fail   (wrong tags: hardcoded ["beach"], not ["culture"])

vague-request-002     | tool_calls [] -> ['search_destinations']
   tool_usage_matches_expected            pass -> fail   (regression: unexpected tool call)
```

`vague-request-002` ("Help me plan a trip.") expects a clarifying question with **zero** tool calls — the system prompt itself says "Ask clarifying questions when important details (destination, dates, budget, travellers) are missing." The new `"trip"` trigger fired anyway. Milestone 13's trajectory metrics caught the net damage the Layer 1 aggregate hid: `average_tool_precision` dropped **0.900 → 0.864**, `total_unnecessary_tool_calls` rose **2 → 3**.

**Diagnosing from a real Langfuse trace** (`make langfuse-up` already running; trace opened at `/project/travel-ai-concierge-dev/traces/<trace_id>`, tags `evaluation` + `vague_request`): the `agent` → `llm_call` generation span for this case showed

```
System:    "...Ask clarifying questions when important details
            (destination, dates, budget, travellers) are missing..."
User:      "Help me plan a trip."
Assistant: [tool_calls: ['search_destinations']]
```

— the model's own decision, sitting right next to the system prompt that told it not to do this, directly contradicting it. Exactly the trace shape a real "poor tool description / overeager prompt" bug produces: the failure isn't visible as an error (`level` stays unset — nothing raised), only as a wrong decision, which is why this needs a human reading the trace, not just a `level == ERROR` filter.

**The fix**: not a revert (that would just bring back `culture-001`'s original failure) — the underlying cause is that neither `"trip"` nor `"destination"` alone means "the user gave a concrete preference." The fix makes the trigger require an actual content signal, and reports it accurately instead of a hardcoded guess:

```python
_DESTINATION_TRIGGER_WORDS = ("destination", "trip")
_KNOWN_TAGS = ("beach", "culture", "quiet", "food", "nightlife",
               "nature", "romantic", "family", "adventure", "wine")

if "search_destinations" in available and any(w in lowered for w in _DESTINATION_TRIGGER_WORDS):
    detected_tags = [t for t in _KNOWN_TAGS if t in lowered]
    if detected_tags:
        # fire, with the *detected* tags
```

**Measurable improvement — re-ran the full 39-case suite, compared against the true original baseline (before the bug was ever introduced), not just against the buggy intermediate state**:

```
                                   baseline   with bug   after fix
Layer 1 overall pass (of 195)         82         83         87
average_tool_precision               0.900      0.864      0.905
total_unnecessary_tool_calls           2          3          2
total_missing_tool_calls              17         16         16
aligned (trajectory)                  16         17         17
```

`vague-request-002` is back to byte-for-byte the same result as the original baseline (confirmed by diffing the machine-readable reports) — the injected regression is fully undone, not just masked. `culture-001` is now a full pass across all three applicable evaluators (previously a fail). Two other pre-existing failures resolved as a genuine side effect of replacing the hardcoded `["beach"]` with real tag detection: `destination-recommendation-001` and `couples-holiday-001` now report their actually-detected tags (`["food", "wine", "quiet"]` and `["romantic"]`) instead of always `["beach"]`. Verified live in Langfuse too: the fixed trace for `vague-request-002` is just `travel_concierge_turn` → `agent` → `llm_call`, output `"[mock] I heard: Help me plan a trip."` — no `execute_tools` span at all, matching the pre-bug trace shape exactly.

**Tests added**: `tests/unit/test_llm_providers.py` gained three regression tests — `test_mock_provider_vague_trip_request_asks_no_tool_call` (pins the exact bug: no tag word present, no tool call), `test_mock_provider_trip_with_a_known_tag_calls_search_destinations` (pins the fix actually detecting and passing the right tag, not just suppressing the trigger), `test_mock_provider_hotel_trigger_is_unaffected_by_the_fix` (the unrelated `"hotel"` trigger — a separate, already-documented Mock limitation from Milestone 13 — is untouched by this change). 225 tests total pass (was 222).

**Interpretation**: this milestone's real lesson isn't the specific bug — it's that an aggregate pass-rate number moved in the *wrong direction to notice* (up, not down) while a real regression was introduced, and only per-case diffing plus Milestone 13's trajectory metrics (`tool_precision`, `unnecessary_tool_calls`) caught it. A CI gate watching only the aggregate pass count, as Milestone 17 is about to build, would need to watch more than one number, or watch per-case results, to catch this class of regression — worth keeping in mind going into that milestone.

**Limitations**: the bug and its diagnosis are both scoped to `MockProvider`'s trigger table, not the system prompt or `TOOL_SPECS`' tool descriptions — those *do* affect `AnthropicProvider`'s real reasoning, but exercising that path needs a real `ANTHROPIC_API_KEY`, unavailable in this environment (the same gap noted in Milestones 2, 5, and 14). The mechanism is different from a real prompt bug; the failure shape and the diagnostic workflow (trace shows a decision contradicting the system prompt, not an error) are the same, and would look identical in a real trace from a real model.

---

## 2026-08-31 — M17: regression detection — a real CI gate, verified to actually fail on a known-weaker configuration

**Hypothesis**: a `make eval-ci` gate comparing two metrics (`quality_pass_rate`, `trajectory_healthy_rate`) against a committed baseline can both (a) pass cleanly on the current, known-good code and (b) actually exit non-zero on a real, previously-measured "known weaker version" — not just in theory, run for real.

**Configuration**: baseline recorded via `make eval-baseline` against the current (post-Milestone-16) code, `LLM_PROVIDER=mock` (default). "Known weaker version" reused directly from Milestone 14's own comparison rather than inventing a new one: `AGENT_MAX_ITERATIONS=1` (forces exactly one LLM call, the agent can never request a tool).

**Step 1 — establish the baseline** (`make eval-baseline`):

```
Baseline recorded: data/evaluation/baseline.json
  quality_pass_rate=0.7310924369747899, trajectory_healthy_rate=0.4358974358974359
```

**Step 2 — run evaluation against the same, unmodified code** (`make eval-ci`):

```
Regression Check (Milestone 17)
========================================
Baseline: recorded 2026-08-31T20:04:09.629558+00:00  provider=mock  cases=39

  quality_pass_rate          baseline=0.731  current=0.731  delta=+0.000  max_drop=0.050  [ok]
  trajectory_healthy_rate    baseline=0.436  current=0.436  delta=+0.000  max_drop=0.050  [ok]

Verdict: PASS
```

Exit code: `0`.

**Step 3 — introduce the known weaker version and run the exact same gate** (`AGENT_MAX_ITERATIONS=1 uv run python scripts/run_evaluation.py --ci`, no code changes, one env var):

```
Regression Check (Milestone 17)
========================================
Baseline: recorded 2026-08-31T20:04:09.629558+00:00  provider=mock  cases=39

  quality_pass_rate          baseline=0.731  current=0.542  delta=-0.189  max_drop=0.050  [REGRESSED]
  trajectory_healthy_rate    baseline=0.436  current=0.026  delta=-0.410  max_drop=0.050  [REGRESSED]

Verdict: FAIL
```

Exit code: `1`, confirmed via `echo $?` immediately after the run, not inferred from the printed text.

**Result**: the gate did exactly what a CI quality gate needs to do — silent and green on the code that's actually shipping, loud and non-zero the moment a real configuration regression (already measured and documented back in Milestone 14: -15.9pp quality, -38.5pp trajectory health at the time, now -18.9pp/-41.0pp against the current, larger baseline) is reintroduced, with no code edited and no test file touched. `AGENT_MAX_ITERATIONS=1` was chosen specifically *because* it's a real, previously-measured, one-env-var "known weaker version" rather than a contrived one — exactly the kind of accidental change (a bad default, a misconfigured deploy) a real CI gate exists to catch.

**Interpretation**: both metrics regressed together here, which doesn't prove the two-metric design was *necessary* for this particular demonstration — a single-step config breaks tool selection so thoroughly that even the aggregate Layer 1 pass rate drops. The two-metric design earns its keep on the *other* shape of regression, the one Milestone 16 actually produced live: quality moving the *right* direction while trajectory health quietly drops. `tests/unit/test_regression.py`'s `test_trajectory_drop_past_threshold_fails_even_when_quality_improves` pins that exact shape with a hand-built fixture, since MockProvider's real behavior doesn't currently produce it live in this run.

**Limitations**: no `--push-to-langfuse`-style integration with Langfuse's own UI for this milestone — the spec asks for a CI gate (`make eval-ci`, exit code, configurable thresholds), which is fully local/scriptable by design, the same reasoning Milestone 9's `make eval-ci` crashed-case check never needed a Langfuse-side view either. The demonstration above used `AGENT_MAX_ITERATIONS=1`, a config regression — a real *prompt* or *tool-trigger* regression (Milestone 16's own bug shape) would be caught the same way, just not re-demonstrated here to avoid re-editing already-fixed production code for a second time.

---

## 2026-08-31 — M18: optional Travel AI Search integration — a real HTTP round trip, and a real circular import found by running the tests

**Hypothesis**: a `TravelSearchProvider` Protocol (mirroring `LLMProvider`, ADR-003) can swap the travel tools onto a separately running Travel AI Search backend with a single `Settings` change, produce the exact trace shape the spec's own diagram asks for (`agent → search tool → Travel AI Search API → results → agent`), and still leave the default (local, no external services) path completely unchanged — verified by the existing 15-test `test_travel_tools.py` suite passing byte-for-byte unmodified after the refactor.

**A real circular import, found by running the tests, not anticipated**: the natural implementation reuses `tools/data.py`'s JSON loader inside the new `LocalSyntheticTravelSearchProvider`. But `tools/travel_tools.py` needs to import `providers.travel_search` (for `get_travel_search_provider()`), and importing anything from `tools.data` first runs `tools/__init__.py`, which eagerly imports `travel_tools.py` — a genuine cycle, not a hypothetical one:

```
providers/travel_search/__init__.py -> local.py -> tools.data
  -> (forces) tools/__init__.py -> specs.py -> travel_tools.py
  -> providers.travel_search  (still mid-import — ImportError)
```

Fixed by moving the loader to `providers/travel_search/data.py` (bumping its repo-root path resolution from `parents[3]` to `parents[4]`) — which is also the more architecturally honest home for it: loading the local dataset is a concern of the *local search provider* now, not the tool-wrapping layer above it. `test_travel_tools.py`'s own import updated to match; all 15 of its tests still pass unmodified otherwise.

**Configuration — the refactor is behavior-preserving**:

```bash
uv run pytest tests/unit/test_travel_tools.py -q
# 15 passed  (unchanged from before the refactor)
make check && make test
# 253 passed, 12 deselected  (was 238 before this milestone — +15 new tests)
```

**The spec's own trace diagram, run for real, not simulated**: a small in-process fake HTTP server (`http.server.ThreadingHTTPServer`, `tests/integration/test_travel_ai_search_provider.py`) implements the assumed Travel AI Search contract (`GET /destinations`, `GET /hotels`, `GET /destinations/{id}`), serving from this project's own synthetic dataset so both providers can be cross-checked against each other for the same query. A real `/chat` request, with `TRAVEL_SEARCH_PROVIDER=travel_ai_search_api` pointed at that server, produced this exact trace (captured live, `trace_id=78db017586c375a4ca3bc1c08bad9ee6`):

```
travel_concierge_turn
├── agent          (iteration 0)
│   └── llm_call
├── execute_tools
│   └── search_hotels
│       └── travel_search_backend   input: {op: search_hotels, destination_id: algarve, family_friendly: true}
│                                   output: {result_count: 3}
│                                   metadata.backend: "travel_ai_search_api"
└── agent          (iteration 1)
    └── llm_call    -> final answer, built from the 3 hotels returned over real HTTP
```

Exactly the spec's own diagram: `Concierge agent → search tool → Travel AI Search API → results → agent`. `metadata.backend` is the one field distinguishing this from the local provider's identical trace shape — same span name (`travel_search_backend`) either way, the same "structural consistency across providers" reasoning `MockProvider`/`AnthropicProvider` established for `llm_call` back in Milestones 2/5.

**Cross-checked against the local provider for the same query**: `tests/integration/test_travel_ai_search_provider.py::test_search_hotels_matches_the_local_provider` asserts the API-backed and local-backed results are identical (`api_results == local_results`) for `search_hotels("algarve", family_friendly=True)` — the same business answer, two different mechanisms, exactly what "service composition without creating a hard dependency" should mean in practice.

**Real numbers**:

```
make test              238 -> 253 passed (12 deselected, unchanged)
make test-integration  7 -> 11 passed (5 skipped, unchanged) — the 4 new
                        Travel AI Search tests are NOT skip-by-default,
                        unlike the Anthropic integration tests: no paid
                        credential is needed, only a loopback HTTP server
                        this file starts and stops itself.
make tools-smoke-test  unchanged output — confirms the default (local)
                        path is byte-for-byte the same as before M18.
```

**Interpretation**: the real finding of this milestone isn't the HTTP client code itself — it's that the "swap providers with zero call-site changes" pattern from ADR-003 transferred cleanly to a second, unrelated domain (search vs. LLM completions), and that the one real wrinkle it hit (the import cycle) came from an incidental detail — where a JSON loader happened to live — not from the abstraction design itself. The abstraction was validated by refactoring around an existing, working, well-tested system and having its behavior provably not change, not by building something new in isolation.

**Limitations**: `TravelAISearchAPIProvider`'s HTTP contract is *designed*, not *confirmed* — this repo has no access to the real Travel AI Search project, so the endpoint shapes, query parameter names, and response schema are this project's own best guess, validated only against itself (the fake server in the integration test implements the same assumption the client makes). A real deployment of that project may differ; `Destination.model_validate(...)`/`Hotel.model_validate(...)` would raise a clear error rather than silently misbehave if it does. No automatic fallback from `travel_ai_search_api` to `local` on failure was built — deliberately out of scope, see ADR-006.

---

## 2026-09-01 — M19: Langfuse Cloud — proving a switch that already worked, not building a new one

**Hypothesis**: `get_langfuse_client()` already threads `Settings.langfuse_host` through with zero branching (unchanged since Milestone 1) — if true, the exact same connectivity test suite should pass unmodified regardless of which real host it's pointed at, and a Cloud-shaped host should construct a client offline exactly as uneventfully as a local one.

**Configuration**: this environment's real `.env` (`LANGFUSE_HOST=http://localhost:3001` — a non-default port, from a real port-3000 conflict logged back in Milestone 1) plus `make langfuse-up`'s running stack. No Langfuse Cloud account is configured anywhere in this environment.

**Step 1 — grep for hardcoded hosts, before writing anything**:

```bash
grep -rn "localhost:3000\|localhost:3001\|cloud.langfuse.com" src/ ui/ scripts/ tests/
```

One hit: `Settings.langfuse_host`'s own default. No other file references a host literally — the "no duplicate instrumentation code" claim was already true, confirmed rather than assumed.

**Step 2 — offline construction, a real Cloud-shaped host, no network**:

```
tests/unit/test_langfuse_client.py::test_construction_does_not_raise_with_a_cloud_shaped_host PASSED
```

`LANGFUSE_HOST=https://cloud.langfuse.com` + placeholder keys, `get_langfuse_client()` called after clearing both caches — succeeds identically to the default-host case, no exception, no network I/O (construction was already established as local-only back in Milestone 1).

**Step 3 — real connectivity, against this environment's own real, non-default host**:

```python
client = get_langfuse_client()
# configured host: http://localhost:3001
with client.start_as_current_observation(name="m19_verification_trace") as span:
    trace_id = span.trace_id
client.flush()
client.get_trace_url(trace_id=trace_id)
# -> http://localhost:3001/project/travel-ai-concierge-dev/traces/af940bef522c350bc5034ed9ece0ff3f
```

The returned URL starts with the exact configured host — not the `3000` default nobody's `.env` in this environment actually uses. `tests/integration/test_langfuse_connectivity.py`'s two tests, reframed (not rewritten) to state this explicitly, pass against this real target:

```
test_auth_check_succeeds_against_the_configured_langfuse_target PASSED
test_can_create_and_flush_a_trace_and_it_lands_at_the_configured_host PASSED
```

**Result**:

```
make check              clean
make test               254 passed, 16 deselected  (was 253 before this milestone — +1 new unit test)
make test-integration   11 passed, 5 skipped  (unchanged — no new integration test file, two existing ones reframed + one new assertion)
```

**Interpretation**: the real finding of this milestone is procedural, not technical — "document and test" turned out to mean "verify an already-correct design, and make an already-adequate test suite say so explicitly," not "add a mechanism." The temptation to write a separate `test_langfuse_cloud.py` with its own throwaway client construction was real and was rejected specifically because it would have been the exact duplication the spec's own last line warns against — the *existing* connectivity tests already are the Cloud test, once framed honestly as testing "whichever target is configured" instead of "the local instance."

**Limitations**: no real Langfuse Cloud account is configured in this environment, so the actual round trip to `cloud.langfuse.com` was never executed — the same "no credential here" gap this project has been explicit about for the Anthropic provider and the real LLM judge since Milestones 2 and 11. What's verified instead: (1) offline, that construction never depends on the host's value, and (2) live, that the exact same code and the exact same tests correctly reach and confirm a real, non-default host that isn't the one every default `.env` shares — the strongest evidence available without a paid account, not a substitute for the real thing, and stated as such rather than blurred.

---

## 2026-09-01 — M21: final experiment suite — a real 4-config matrix, composing seven milestones' worth of measurement into one report

**Hypothesis**: every metric the spec's "Report" list names (deterministic score, LLM judge score, human feedback where available, tool accuracy, groundedness, latency, cost) already has a real, tested measurement mechanism somewhere in this project (M9, M11, M12, M13, M14) — composing them into one N-config comparison should need no new measurement code, only a new aggregation/rendering layer, the same "reuse, don't duplicate" discipline this project has held since Milestone 10.

**A real tagging bug found and fixed before the suite even ran once**: `run_case_with_metrics()` (M14) hardcoded `extra_tags=["cost-latency-experiment", config_name]` — reusing it unchanged for this milestone's own script would have mislabeled every M21 trace as an M14 trace in Langfuse's UI. Fixed by adding a keyword-only `experiment_tag: str = "cost-latency-experiment"` parameter (default preserves M14's exact existing behavior — `tests/unit/test_cost_latency.py`'s 12 tests all still pass unmodified), with this milestone's script passing `experiment_tag="final-experiment-suite"`. Verified live, not just by the tests: opened a real trace afterward and confirmed its tags read `evaluation`, `<query_class>`, `final-experiment-suite`, `<config-name>` — not `cost-latency-experiment`.

**Configuration**: the spec's own example matrix crosses prompt version against two different models plus a tool-description variant — this environment has no `ANTHROPIC_API_KEY` (the same recurring gap as every real-provider comparison since Milestone 2), so a second real model can't be exercised live here. The matrix run instead crosses the two axes that are actually live and differentiable under `LLM_PROVIDER=mock` in this environment:

```
prod-v1 x multi-step     (PROMPT_LABEL=production, AGENT_MAX_ITERATIONS=5 — the project default)
staging-v2 x multi-step  (PROMPT_LABEL=staging,    AGENT_MAX_ITERATIONS=5)
prod-v1 x single-step    (PROMPT_LABEL=production, AGENT_MAX_ITERATIONS=1)
staging-v2 x single-step (PROMPT_LABEL=staging,    AGENT_MAX_ITERATIONS=1)
```

**Result — real output from this environment** (`make final-experiment-suite`):

```
metric                                prod-v1 x multi-step   staging-v2 x multi-step     prod-v1 x single-step  staging-v2 x single-step
----------------------------------------------------------------------------------------------------------------------------------------
deterministic score (Layer 1)                        73.1%                     73.1%                     54.2%                     54.2%
judge: constraint_satisfaction                        4.31                      4.31                      5.00                      5.00
judge: groundedness                                   5.00                      5.00                      5.00                      5.00
judge: helpfulness                                    5.00                      5.00                      5.00                      5.00
judge: itinerary_coherence                            3.00                      3.00                      3.00                      3.00
judge: relevance                                      3.62                      3.62                      2.46                      2.46
human feedback                                         n/a                       n/a                       n/a                       n/a
tool precision                                       90.5%                     90.5%                       n/a                       n/a
tool recall                                          61.5%                     61.5%                     15.4%                     15.4%
groundedness (proxy)                                100.0%                    100.0%                       n/a                       n/a
trajectory healthy rate                              43.6%                     43.6%                      2.6%                      2.6%
p50 latency (ms)                                     0.178                     0.177                     0.093                     0.105
p95 latency (ms)                                     0.299                     0.217                     0.189                     0.191
avg estimated cost / case                              n/a                       n/a                       n/a                       n/a

Final Engineering Analysis
========================================
Recommended: 'prod-v1 x multi-step' — highest deterministic quality (73.1%) and trajectory
health (43.6%) among the 4 configurations compared.
  Cost of that choice: p50 latency 0.178ms, ~148 tokens/case, estimated cost n/a/case.
  Runner-up 'staging-v2 x multi-step': 73.1% quality at 1.00x the winner's p50 latency.
```

**Two independent, mutually-reinforcing findings, both exactly as predicted before the run** — the strongest kind of validation a comparison harness can get, because the harness didn't know in advance which pairs should match and which shouldn't:

1. **The two prompt-version pairs are statistically identical** (73.1%/73.1% and 54.2%/54.2%, every judge dimension matching to two decimal places) — confirmed, not assumed: `providers/llm/mock.py`'s `_decide()` extracts only the last *user* message, never reads the system prompt at all. Prompt content is structurally invisible to Mock, so identical results are the *correct*, expected outcome, not a null result.
2. **`AGENT_MAX_ITERATIONS` produces a large, consistent gap regardless of prompt version** (73.1%→54.2% quality, 43.6%→2.6% trajectory health, 61.5%→15.4% tool recall) — re-confirming Milestone 14/17's own already-established finding in a new, independently-built harness, not just repeating the same script.

`prod-v1 x multi-step`'s own numbers (`quality_pass_rate=0.7310924369747899`) match Milestone 17's committed baseline (`data/evaluation/baseline.json`) to the full floating-point digit — expected, since this config *is* the project's own default, and a genuine cross-check that this new, independently-built harness measures the same thing the existing regression gate does.

**The auto-generated final analysis correctly avoided a wrong conclusion**: with four configs producing two identical pairs, a naive "rank all four, declare a winner" approach could have appeared to prefer `prod-v1` over `staging-v2` by pure floating-point noise in the tied pair. `render_final_analysis()`'s ranking key is `(quality_pass_rate, trajectory_healthy_rate)` — both configs in the winning pair tie exactly, so the reported "recommendation" is really "either prompt version, running multi-step" — and the analysis's own caveat paragraph states the Mock-invariance fact explicitly rather than letting the reader infer a false prompt-quality signal from noise.

**Result — sanity checks after the change**:

```
make check              clean
make test               266 passed, 16 deselected  (was 254 before this milestone — +12 new tests)
make test-integration   11 passed, 5 skipped  (unchanged)
make eval-ci            PASS, zero drift from the committed M17 baseline
```

**Interpretation**: this milestone's real test wasn't whether the script ran — it was whether a genuinely new, independently-composed measurement path (`final_suite.py`, built without looking at `cost_latency_report.py`'s internals beyond its public functions) would reproduce numbers three earlier milestones (M14, M17, and implicitly M9/M11/M13) already established, or silently diverge from them. It reproduced them exactly, which is a stronger form of "the reused modules are correct" evidence than any of those modules' own unit tests could provide alone — an integration-level cross-check none of M9-M17 individually could have run, because none of them had a reason to combine every prior metric into one report until this milestone asked for one.

**Limitations**: no real second model (`ANTHROPIC_API_KEY` unavailable, as stated above) and no "improved tool descriptions" variant — `MockProvider` reads tool *names* only, never descriptions (same `_decide()` fact as the prompt-content finding), so a tool-description axis would be exactly as inert here as the prompt axis turned out to be; building one would only prove the same structural fact twice. The judge scores above are `FakeJudgeProvider`'s (default, offline, free) — its own module docstring is explicit that its scores are *derived from* Layer 1's evaluator outcomes, not an independent read of quality, so "judge: relevance" and "deterministic score" moving together here is not independent confirmation, it's the same underlying signal restated; a real, independent judge score needs `JUDGE_PROVIDER=anthropic`, unexercised live for the same credential reason. "Human feedback" is correctly `n/a` throughout — no human has ever rated any of these 39 synthetic cases; that column would only populate from real `/chat` traffic (Milestone 12), a fundamentally different data source than this offline suite.

---

## 2026-09-01 — Real Anthropic provider, at last: the prompt-invariance ceiling breaks, and something more interesting than "prompt v2 wins" shows up

**Context**: every real-provider comparison since Milestone 2 has carried the same caveat — "unverified live, no `ANTHROPIC_API_KEY` in this environment." That gap closes here. The user configured `LLM_PROVIDER=anthropic` / `LLM_MODEL=claude-sonnet-4-6` and `JUDGE_PROVIDER=anthropic` / `JUDGE_MODEL=claude-sonnet-5` in their own `.env` and ran, in order: `make test-integration`, `make evaluate-judged`, `make experiment-prompt-v1`, `make experiment-prompt-v2`, `make final-experiment-suite`. Model names are used exactly as configured; this entry does not independently verify them against Anthropic's current public model catalog, the same "illustrative, not verified" stance `MODEL_PRICING`'s own docstring already takes in `evaluation/cost_latency.py`.

**A real bug found mid-run, before any results existed to write down**: the first `make final-experiment-suite` attempt crashed on case ~29 of the third config, with a live judge response `{"dimension": "constraint_satisfaction": 5, ...}` — a genuine LLM formatting slip (an extra colon, missing the `"score"` key) that `_parse_judgments()` correctly rejected as invalid JSON, exactly the "never silently fabricate a score" behavior `judge.py`'s own docstring promises. The real gap was one layer up: `scripts/run_final_experiment_suite.py` had no resilience around a single bad judge response, so it threw away the two already-completed (and already-paid-for) configs along with it, and never persisted anything until all four configs finished. Fixed with two small, targeted changes: retry once on `JudgeParseError` (the failure is stochastic, not deterministic), skip just that one case's judge score if it fails twice (matching the existing "return `None`/omit rather than fabricate" convention `estimate_cost_usd()` already uses), and write `latest-final-suite.json` after every config instead of only at the end. The re-run afterward judged all 39 cases in all 4 configs cleanly — either the retry worked or the flaky response simply didn't recur, but the resilience is real regardless.

**Result 1 — real cost and latency, for the first time in this project.** Previously every cost/latency table read `n/a`/`$0.00` under `MockProvider`. From `make final-experiment-suite`'s `data/evaluation/results/latest-final-suite.json`:

```
metric                          prod-v1 x multi-step   staging-v2 x multi-step   prod-v1 x single-step   staging-v2 x single-step
--------------------------------------------------------------------------------------------------------------------------------
quality (Layer 1 pass rate)                    88.1%                    87.4%                    60.2%                    60.2%
trajectory healthy rate                        56.4%                    51.3%                    12.8%                    12.8%
tool precision                                 81.5%                    79.0%                      n/a                      n/a
tool recall                                    84.6%                    84.6%                    15.4%                    15.4%
groundedness (proxy)                          100.0%                   100.0%                      n/a                      n/a
p50 latency                                   8.35s                    8.79s                    6.12s                    5.83s
p95 latency                                  17.44s                   13.39s                    8.54s                    8.73s
total tokens (in+out)                         93,552                  101,658                    12,264                    13,040
estimated cost (39 cases)                    $0.4331                  $0.4683                   $0.1513                   $0.1479
avg cost / case                             $0.0111                  $0.0120                   $0.0039                   $0.0038
judge: relevance                                4.82                     4.79                     4.28                     4.05
judge: helpfulness                              4.49                     4.51                     3.72                     3.67
judge: groundedness                             4.72                     4.49                     4.69                     4.74
judge: constraint_satisfaction                  4.67                     4.67                     4.51                     4.28
```

The `AGENT_MAX_ITERATIONS` gap this project has now reproduced four separate times (M14, M17's regression demo, M21 under Mock, and here under a real model) holds again, and is now priced for the first time: multi-step costs ~2.9x single-step per case for a real, substantial quality/trajectory gain — a genuine, previously-only-hypothetical cost/quality trade-off Mock's `$0.00` could never show.

**Result 2 — prompt v1 vs v2 finally produce different numbers. But the size, and even the direction, of that difference depends on which of three separate real-model runs you look at — and that instability is itself the finding.**

Three independent measurements exist, all nominally comparing the same two prompt labels:

*(a) `make final-experiment-suite`* — both prompts evaluated inside one script execution (the table above): `prod-v1` slightly ahead on quality (88.1% vs 87.4%), trajectory (56.4% vs 51.3%), and tool precision (81.5% vs 79.0%); tied on tool recall (84.6%).

*(b) `make experiment-prompt-v1` / `make experiment-prompt-v2`* — Milestone 10's native Langfuse `run_experiment()` path, two separate script executions, real output:

```
                                  prompt-v1 (production)   prompt-v2 (staging)
tool_usage_matches_expected                        51.3%                 61.5%
trajectory_healthy                                 48.7%                 59.0%
trajectory_tool_recall                             79.5%                 89.7%
trajectory_tool_precision                          78.7%                 81.0%
trajectory_agent_steps                             1.718                 1.821
```
Dataset runs: `http://localhost:3001/project/travel-ai-concierge-dev/datasets/cmtg6587u000ipj07rv4u6rsq/runs/fbbc248a8cb44b08` (v1), `.../runs/69bbd953ced5f1d2` (v2).

Here `staging-v2` is ahead by ~10 percentage points on every trajectory-related metric — the **opposite** ranking from (a).

*(c) `make evaluate-judged`* — a third separate execution, at the project's default settings (`PROMPT_LABEL=production`, `AGENT_MAX_ITERATIONS=5`) — nominally the *same config* as (a)'s `prod-v1 x multi-step` and (b)'s `prompt-v1` run. `data/evaluation/results/latest.json`/`latest-trajectory.json`: quality 87.6% (120 pass / 17 fail), trajectory healthy 56.4% (matches (a) exactly — 22/39), `tool_usage_matches_expected` 59.0% (23/39) — 7.7 points higher than run (b)'s 51.3% for the same nominal config.

**Interpretation**: `MockProvider` is 100% deterministic — it never produces this kind of spread on repeat runs of the same config, which is exactly why every prompt-comparison result before this entry (M10, M11, M21) came back byte-identical or structurally explainable. A real model doesn't have that property, and the spread here isn't small: run (b)'s within-session v1-vs-v2 gap on `trajectory_healthy` (10.3 points) is the same order of magnitude as the cross-run noise on the *same* config between (b) and (c) (7.7 points on `tool_usage_matches_expected`). That means a single real-model run cannot distinguish "prompt v2 is meaningfully better" from "this is what run-to-run variance looks like" — and indeed, runs (a) and (b) disagree on which prompt wins at all. The evaluation harness this project has built (M9-M21) runs each case exactly once per config; nothing here repeats a config to average out this noise. That is a genuine, previously-invisible-under-Mock limitation of the harness as it stands, not a bug in any single run — repeated runs per config (with a variance/significance check) would be the natural next step, and is explicitly not built here. One contributing factor worth naming: `clarifying_question_when_expected` is only applicable to ~5 of the 39 cases (34 skips in run (c)) — a metric with that few applicable cases can swing 20 points from a single case flipping, which is part of why small aggregate differences on some evaluators should be read cautiously regardless of provider.

A secondary, structural observation: under `AGENT_MAX_ITERATIONS=1` (single-step), `prod-v1` and `staging-v2` tie *exactly* on both `quality` (60.2%) and `trajectory_healthy` (12.8%) in run (a), even though the judge scores for the two configs genuinely differ (e.g. relevance 4.28 vs 4.05) — the real generated text is different, but the binary Layer 1 pass/fail pattern happens to land identically. `agent_node`'s tools-withholding check (`iterations + 1 >= agent_max_iterations`) means tools are withheld from the very first call when `agent_max_iterations=1`, so prompt content has far less surface area to affect an evaluator that mostly hinges on whether/which tool was called — a plausible, not fully confirmed, explanation for why the tie is exact rather than approximate.

**A second real bug found — this time in `make test`, not the new script.** After the changes above, `make test` (the "offline, no credentials" unit suite) started failing 4 tests: two in `test_agent.py`, two in `test_trace_design.py`. All four call `get_agent_graph()` directly and rely on `MockProvider`'s deterministic "find me a hotel" → `search_hotels` trigger — but neither file's autouse cache-clearing fixture ever pinned `LLM_PROVIDER=mock`; they simply relied on `.env`'s own default being `mock`, which every `.env` in this project's history had been until this session. The moment a real `.env` set `LLM_PROVIDER=anthropic` for live use, these "offline" tests silently started making real, non-deterministic API calls instead — one test's `search_hotels`-span assertion failed because the real model didn't call that tool for that exact input this time. `test_agent.py`'s own module docstring explicitly promises "Offline via `MockProvider`'s deterministic tool-trigger heuristic... no network, no credentials" — a promise the test file wasn't actually structurally enforcing. Fixed by adding `monkeypatch.setenv("LLM_PROVIDER", "mock")` to both files' autouse fixtures, the same explicit-pin pattern `test_trace_design.py`'s own `_chat_test_client` helper and `test_resilience.py` already used elsewhere in this test suite — `make test` is back to 266/266 passed. This is the kind of gap Mock's total determinism structurally hides: every other `.env` this project has ever run against happened to make the missing isolation invisible.

**Result — sanity checks**:

```
make test-integration    16 passed, 0 skipped  (previously 11 passed, 5 skipped — this closes the last of them)
make test                266 passed, 16 deselected  (4 failures found and fixed — see above)
make check                clean
```

**Limitations**: still the same 39-case synthetic dataset every prior milestone used — a real second model comparison exists now, but a real second *tool-description* variant still doesn't (`MockProvider`'s finding that tool descriptions are structurally invisible was never about the real provider, so this remains genuinely untested). Only one repeat per config was run for each of the three harnesses above; the variance discussion in Result 2 is drawn from comparing *different* harnesses/executions against each other, not from a designed repeated-trials experiment — suggestive, not a rigorous variance estimate. `JUDGE_PROVIDER=anthropic` judging `LLM_PROVIDER=anthropic`'s own output remains the same-model-family self-preference risk `judge.py`'s docstring and [docs/FINAL_QUESTIONS.md](FINAL_QUESTIONS.md) Q17 already name — unaddressed here, just no longer hypothetical.
