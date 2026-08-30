# Rationale Per Milestone

Why each milestone was built the way it was — the reasoning that doesn't fit in code comments or the README. See `docs/decisions/` for the more formal ADRs; this document is the narrative connecting them to what actually got built.

---

## Milestone 0 — Scaffolding

**Goal**: a project a developer can clone, install, and run a health check against, with the four foundational architecture decisions made and recorded before any agent or Langfuse code exists.

**What we chose and why**:
- **LangGraph** over transparent Python or CrewAI/AutoGen (ADR-001) — because its graph topology is the observability model: a node maps to a span, a conditional edge maps to a routing decision visible in the trace.
- **Streamlit** over Gradio or React (ADR-002) — the UI is a vehicle for the observability learning objective, not the objective itself.
- **A thin Protocol-based LLM provider abstraction** (ADR-003) — Langfuse instrumentation lives inside each concrete provider, not behind the abstraction, so it stays inspectable rather than becoming magic.
- **Self-hosted Langfuse by default, Cloud via three env vars** (ADR-004) — no-cost, no-credentials path to start learning; Cloud is a configuration change, not a code branch.

Deliberately not built: agent, tools, any actual Langfuse SDK call, LLM providers, UI. Milestone 0 is the skeleton these attach to.

---

## Milestone 1 — Local Langfuse

**Goal**: prove the observability substrate actually works end-to-end on this machine before building anything that depends on it — a real trace, created by our code, visible in the real UI.

**What we chose and why**:

- **The official self-hosted docker-compose, fetched and verified, not reconstructed from memory.** The project spec explicitly warns against inventing a simplified deployment that drifts from Langfuse's actual requirements. Rather than trust training-data recollection of what the compose file looks like (which turned out to be a major version behind — v3 assumptions, v4 reality), we fetched `github.com/langfuse/langfuse/blob/main/docker-compose.yml` directly and adapted that. This is the same reasoning applied to the SDK: before writing any code against `langfuse` v4.15.1, we introspected the installed package directly (`dir(Langfuse)`, `inspect.signature(...)`) rather than assuming the pre-OTel v2 API most training data would suggest. Both calls paid off — the real API differs from what memory alone would have produced (see the trace_id timing bug caught in `docs/EXPERIMENTS.md`).

- **Headless initialization over manual UI signup as the default** (ADR-005) — reproducibility was already a stated project value (`.env.example`, `make env`); requiring every contributor to click through a signup flow to get working API keys works against that. The manual flow is preserved and documented, not removed.

- **`get_langfuse_client()` builds the client explicitly from `Settings`, not from the SDK's env-var auto-discovery** — pydantic-settings parses `.env` into the `Settings` object without mutating `os.environ`, so the SDK's own `get_client()` would silently see nothing. This keeps the project's single source of configuration truth intact (everything flows through `Settings`) rather than introducing a second, parallel config path that happens to work today.

- **A real client is always returned, never `None`, when Langfuse is disabled** — `tracing_enabled=False` is passed through to the SDK rather than skipping client construction. Call sites never need an `if langfuse_enabled:` branch, which is what "observability must not become a hard runtime dependency" (ADR-004) looks like in practice rather than in principle.

- **Integration tests are marker-excluded by default (`-m "not integration"`), not skipped-by-decorator.** A decorator-based skip (`@pytest.mark.skipif(not langfuse_running())`) would require writing a live-connectivity probe just to decide whether to skip — extra code whose only job is deciding whether to run other code. A pytest marker with a default exclusion filter needs no such probe: `make test` never touches the network, `make test-integration` explicitly opts in.

**Surprises worth carrying forward**: the Langfuse self-hosted stack is now v4 (image registry moved to `docker.langfuse.com`), and its REST API for fetching a trace by ID (`GET /api/public/traces/{id}`) is unavailable in this version's default ingestion mode. Full detail in `docs/EXPERIMENTS.md`. Neither blocks anything in this milestone, but the second one will matter whenever a later milestone (e.g. `make eval-ci`) needs to programmatically verify trace contents rather than just create them.

Deliberately not built: any connection between the agent/API and Langfuse — that's Milestone 2. This milestone only proves the substrate; nothing in the FastAPI app calls `get_langfuse_client()` yet.

---

## Milestone 2 — Minimal concierge with tracing

**Goal**: a real `POST /chat` endpoint, backed by a real LLM provider abstraction, where every request produces a correctly-shaped Langfuse trace — the first milestone where the agent/API and the observability substrate actually meet.

**What we chose and why**:

- **Introspect the installed `anthropic` SDK before writing `AnthropicProvider`, exactly as Milestone 1 did for `langfuse`.** This paid off again: the installed version's `messages.create()` has no `temperature` parameter at all — a detail no amount of remembering "how the Anthropic API works" would have caught, since it used to have one. `Settings.llm_temperature` stays in the schema (a future provider may use it) but `AnthropicProvider` explicitly doesn't pass it, with a comment explaining why rather than a parameter that silently does nothing.

- **Both `MockProvider` and `AnthropicProvider` open their own Langfuse `generation` span, with identical shape.** This was a deliberate consistency requirement, not just "both happen to use Langfuse": ADR-003 already committed to instrumentation living inside each provider rather than behind the Protocol, and the payoff is that a trace produced while iterating offline against the mock looks structurally identical to one produced against the real model — same span name (`llm_call`), same `usage_details` key convention (`input`/`output`, matching what Milestone 1 already verified renders correctly in the UI). A developer learning to read traces doesn't have to learn two different shapes depending on which provider happens to be configured.

- **`user_id` is never fabricated when absent from a request.** The alternative — generating a synthetic ID per anonymous request — would actively work against the reason `user_id` exists in Langfuse: aggregating cost/behavior for the *same* identity across time. A fabricated one-shot ID pollutes that aggregation with noise. Leaving it unset when the caller doesn't provide one is the more honest choice, even though it means some traces simply have no user attribution.

- **`trace_id` is only returned to the client when `Settings.debug` is true**, matching the project spec's explicit guidance ("desirable in development... do not necessarily expose it in a real production client"). This reused an existing pattern already established for `/docs` and `/redoc` in Milestone 0 rather than inventing a new one.

- **`client.flush()` is called conditionally on `debug`, never unconditionally.** Spans batch and export asynchronously by design (Milestone 1) — forcing a synchronous flush on every production request would reintroduce exactly the hard dependency on Langfuse's availability that ADR-004 rules out. In debug mode, the trade favors immediate visibility over the (here, negligible) latency cost, because the whole point of debug mode is a developer watching the trace appear right after the request returns.

- **A second smoke-test script, hitting the running server over real HTTP** (`scripts/smoke_test_chat.py`), rather than only relying on FastAPI's in-process `TestClient` in the automated tests. `TestClient` proves the route logic works; it doesn't prove request routing, real JSON serialization over a socket, or that `make serve` actually starts something reachable. Both are worth having, for different reasons — see `docs/EXPERIMENTS.md` for how this caught nothing wrong here, but the Milestone 1 equivalent caught a real bug, so the pattern is now a habit.

**Surprises worth carrying forward**: writing this milestone's tests surfaced a real caching bug before it shipped — `get_langfuse_client()` is a separate `lru_cache` singleton from `get_settings()`, and a test fixture clearing only the latter would silently reuse a stale Langfuse client config depending on test execution order. Full detail in `docs/EXPERIMENTS.md`.

Deliberately not built: conversation memory/history across turns (each request is stateless beyond a shared `session_id` label), tools, an actual travel domain, and the LangGraph agent graph itself — all still ahead in Milestones 4–5. `AnthropicProvider` exists and is unit-tested for wiring, but has not been exercised against the real API in this environment (no `ANTHROPIC_API_KEY` configured) — its integration test skips itself cleanly rather than failing.

---

## Milestone 3 — Chat UI

**Goal**: a real, usable chat interface — multi-turn transcript, session reset, feedback placeholders, an optional debug panel — that talks to the Milestone 2 API exclusively over HTTP, proving the "API and UI remain separate" requirement in code rather than just in an architecture diagram.

**What we chose and why**:

- **Streamlit talks to FastAPI over real HTTP (`httpx2.post` to `Settings.api_base_url`), never by importing agent or provider code.** This was the one hard constraint the project spec named explicitly for this milestone. It also means the UI process and API process can be started, stopped, and even deployed independently — a genuine architectural property, not just a file-organization convention. The cost is exactly what you'd expect: the UI has to handle the API being unreachable as a first-class case (see "displaying errors cleanly" below), the same as any other HTTP client would.

- **`st.feedback("thumbs", ...)` over hand-rolled buttons.** Streamlit ships a widget purpose-built for this ("commonly used in chat and AI apps to allow users to rate responses" — its own docstring). Discovering this by checking the installed Streamlit's actual API (rather than assuming two `st.button` calls was the only option) meant less code, an idiomatic result, and a widget that came with its own `AppTest` test element for free.

- **Feedback is a real, visible interaction with no backend effect yet — deliberately.** The project spec calls this out explicitly as a "placeholder" for Milestone 3; wiring it to an actual Langfuse score is Milestone 12's job, which will need to make real decisions this milestone shouldn't pre-empt (score type, scale, whether to collect a comment). Showing a toast that says exactly that ("not yet sent to Langfuse — see Milestone 12") is more honest than either silently doing nothing or quietly wiring up a half-considered version of M12's actual work.

- **A stable, synthetic `user_id` generated once per Streamlit session, not once per message.** This is the correct way to populate `user_id` in a demo/synthetic context, and it's a different situation from the one Milestone 2 already ruled out: M2 said don't fabricate a *fresh* `user_id` when a single API request omits one, because that pollutes cross-request aggregation with noise. Here, the UI *client* deliberately creates one stable identity for the lifetime of a browser session and reuses it consistently — exactly what `user_id` aggregation is for, and exactly what the project spec asks for ("for synthetic/demo scenarios, generate synthetic users").

- **The debug panel is honest about what it's showing.** "Latency (client-measured)" is explicitly labeled as such, not just "Latency" — it's wall-clock time around the HTTP call from the browser's perspective, not the server-side span duration Langfuse itself records for the request. Conflating the two would be a small but real correctness lie in a project whose entire point is teaching people to read observability data accurately.

- **The debug panel explicitly tells the user this UI's conversations have no LLM memory yet**, rather than letting a multi-turn-looking chat transcript imply capability that doesn't exist. The UI can *display* a full conversation history because it keeps its own client-side list of messages, but every `/chat` call still only sends the latest message (Milestone 2's contract, unchanged) — a real model would have no idea what was said two turns ago. Silently shipping a UI that looks like it remembers, when the backend doesn't yet, would be the kind of "fake complexity" the project spec explicitly warns against — better to say so directly than let a user discover it by being confused.

- **The trace-URL lookup in the debug panel fails silently into a caption, catching broadly (`except Exception`) rather than a specific SDK exception type.** This was added after finding, by actually reproducing it in a browser rather than just reasoning about it, that `get_trace_url()` has more than one realistic failure mode — an unreachable host raises `httpx2.ConnectError`, wrong API keys raise Langfuse's own `UnauthorizedError`, a slow network raises a timeout. All three are variations on the same underlying situation: this is a non-critical debug convenience, and the chat feature it sits next to already works without Langfuse (span creation needs no network). Enumerating exception types one at a time would leave the door open for the next one nobody thought of; the broad catch matches what this code path actually is — an optional nicety degrading, not the application handling a specific anticipated error.

**Surprises worth carrying forward**: writing the `AppTest` for the debug panel's trace link caught a real bug, not just a test-mocking wrinkle — the sidebar renders earlier in the script's top-to-bottom execution than the code that appends a new message, so without an explicit `st.rerun()` after a successful exchange, the debug panel always lagged one interaction behind (showing the *previous* turn's trace/model/latency). A second real bug — a raw traceback rendering in the UI when Langfuse is unreachable — was caught not by the original test suite but by a subsequent documentation review pass that re-ran the actual code path live instead of only re-reading prose; see `docs/EXPERIMENTS.md` for both, including why `st.rerun()` is safe here (it cannot resend the message — `st.chat_input` isn't re-invoked).

Deliberately not built: any actual conversational memory (Milestone 7), real Langfuse score submission for feedback (Milestone 12), and anything travel-domain-specific (Milestone 4) — the UI is a faithful window onto exactly what Milestone 2's API already does, no more.

---

## Milestone 4 — Synthetic travel tools

**Goal**: real, typed, independently-tested travel tools backed by real (synthetic) data — proven to work and to instrument correctly in Langfuse, before anything wires them into an LLM's decision-making.

**A milestone-boundary question, resolved by reading ahead rather than reading literally**: the project spec's M4 text says "connect them to the agent," but there is no agent yet — LangGraph doesn't exist until Milestone 5. Rather than force a premature wiring decision, I read M5's own spec text for the actual boundary: M5 frames itself as producing the *first* comparison between "simple chatbot" and "tool-using agent" traces. If M4 had already wired tools into `/chat`'s LLM call, that comparison would have nothing new to show in M5 — the tool-using trace would already exist. So M4's real job, consistent with the milestone sequence's own internal logic rather than one ambiguous sentence, is to build and independently verify the tools; M5's job is to make an LLM actually choose to call them. This is the same kind of interpretive call already made for the M2/M3 conversational-memory question — flagging the reasoning here rather than silently picking one reading.

**What we chose and why**:

- **Hand-authored data, not randomly generated, despite the spec calling for "deterministic synthetic data."** At this scale (8 destinations, 18 hotels) a fixed seed buys nothing a human reviewing 26 literal records doesn't already get for free, and hand-authored content reads as real geography rather than obviously-templated Faker output. "Deterministic" is satisfied because running `scripts/generate_data.py` twice produces byte-identical JSON — determinism was never about *how* the values were chosen, only that choosing them again gives the same answer.

- **The generation script is the source of truth; the JSON files are a committed, regenerable artifact.** This mirrors the project's existing bias toward `make`-driven reproducibility (`make langfuse-up`, `make generate-data` now among them) — editing `scripts/generate_data.py` and re-running it is the sanctioned way to change the dataset, not hand-editing JSON that would then disagree with its own generator.

- **`as_type="tool"` instead of a plain `span` named `tool.search_hotels`.** The Langfuse OTel SDK has a first-class `tool` observation type (confirmed by introspection back in Milestone 1, not assumed here) with its own UI filter facet and icon — using it is the difference between a human-readable naming convention and actually telling Langfuse what kind of thing this is. Verified live: the Tracing view's Type facet shows a genuine `TOOL` count alongside `SPAN`/`GENERATION`, not just tool calls with distinctive-looking names.

- **Tool functions are plain, synchronous Python — no `async def`, no dependency on the LLM provider abstraction, no dependency on the API layer.** There is nothing to await (in-memory list filtering over a small JSON-backed dataset); adding `async` where nothing is asynchronous would be exactly the kind of premature-complexity the project spec warns against. This also means the tools have zero coupling to *how* they'll eventually be invoked (native LLM tool-calling vs. a LangGraph node vs. something else) — that decision is now free to be made in Milestone 5 without touching this milestone's code.

- **No tool-schema/JSON-schema representation for LLM consumption yet.** It would be easy to also generate an Anthropic-style `tools` parameter block right now, but that format is a guess at what Milestone 5's actual integration approach wants, made before that approach is chosen. Building it now risks reshaping it later for no benefit today — the tools are fully usable and testable as plain function calls without it.

**Surprises worth carrying forward**: none of substance this milestone — see `docs/EXPERIMENTS.md` for the (uneventful, first-try-correct) verification detail. The one thing worth remembering forward: because each tool only opens its own `start_as_current_observation(...)` block and touches no trace-level state, Milestone 5 should be able to call these functions from inside an active `travel_concierge_turn` trace and see them nest automatically — that nesting is designed in via OTel context propagation, not yet exercised live, since nothing calls these tools from within a live request trace until M5 exists.

Deliberately not built: any connection from `/chat` or the LLM provider to these tools (Milestone 5), tool-selection logic of any kind (heuristic or LLM-driven — both are Milestone 5's job), and a `TravelSearchProvider`/`TravelAISearchAPIProvider` abstraction for a real upstream travel search service (Milestone 18, optional).

---

## Milestone 5 — Explicit Agentic AI workflow

**Goal**: replace `/chat`'s direct LLM call with a real, hand-written LangGraph agent that can decide to call a tool, execute it, and incorporate the result — the wiring Milestone 4 deliberately deferred.

**A second interpretive call, same spirit as Milestone 4's**: the spec's conceptual diagram draws "understand request," "need clarification?," and "select tool(s)" as three separate boxes. I collapsed all three into one node (`agent`): a single LLM call, with tools offered, where the model's own output — plain text vs. a tool request — *is* the routing decision. Forcing a dedicated classifier call to decide "should I clarify?" before even attempting an answer would duplicate work the model already does in one pass, and isn't what the diagram is actually asking for once you read it as intent (a workflow shape) rather than a literal call count. Flagging this the same way as the M4 boundary call, for the same reason: the interpretation is defensible but not the only possible reading.

**What we chose and why**:

- **A hand-written `agent ↔ tools` loop, verified with a toy LangGraph example before any real node existed.** Two nodes, a conditional edge, an edge back from `tools` to `agent` — this is the standard "ReAct-style" shape, and I confirmed the state-passing mechanics (`TypedDict`, nodes returning whole-list replacements rather than relying on LangGraph's `Annotated` reducer convenience) with a throwaway 6-line example before writing `agent_node`/`tools_node` for real. Consistent with this project's running discipline of checking real APIs empirically (Langfuse in M1, Anthropic in M2, LangGraph here) rather than building against a remembered or assumed shape.

- **`LLMProvider.complete()` gained a `tools` parameter and `Message`/`LLMResponse` gained `tool_calls`, built from Anthropic's actual introspected types** (`ToolParam`, `ToolUseBlockParam`, `ToolResultBlockParam`), not from memory of "how tool-calling APIs usually work." This confirmed something non-obvious: Anthropic has no native "tool" role — a tool result must be sent back as a *user* message containing a `tool_result` content block. Getting this wrong would have been a silent, hard-to-spot bug (the API might accept a malformed history in some cases and misbehave, rather than reject it outright) — verified instead via 6 offline unit tests pinning the exact translated shape.

- **`as_type="agent"` for the reasoning node, `as_type="span"` for the tool-execution-batch grouping node.** Same principle Milestone 4 established for `tool`: use Langfuse's real distinct type for the thing that IS one (a reasoning/decision step), and the generic type for a step that's genuinely just coordination (grouping N tool calls from one turn). Verified live: `AGENT` appears as a real, distinct value in Langfuse's own Type filter facet, not just descriptive naming.

- **`MockProvider` gained a small, fixed keyword-trigger table to decide when to "call" a tool.** This is a test double standing in for reasoning, not an attempt at one — its only job is letting the full agent loop be exercised deterministically offline, matching the project's established testing philosophy (no paid API required for `make test`). It also recognizes "I already have a tool result in context" and synthesizes a final answer from it, so the mock exercises the *entire* loop shape (both hops), not just the first.

- **Two independent safety nets against an infinite tool-calling loop, not one.** `agent_node` withholds tools once about to make the last allowed call (so a well-behaved provider naturally produces a clean final answer instead of an empty-content dead end), and `_route_after_agent` separately hard-stops once the iteration cap is reached regardless of what the last message contains (so a provider that ignores `tools=None` — a real possibility for any future non-Anthropic provider — still can't loop forever). Building only the first would leave a genuine production risk (unbounded cost/latency from a misbehaving model); building only the second would produce technically-safe but user-visibly-broken empty responses at the cap. This dual design, and a real off-by-one bug in it, was caught by hand-tracing the exact call sequence for a small `max_iterations` *before* running anything — not by a failing test. Full detail in `docs/EXPERIMENTS.md`.

- **`Settings.agent_enabled` (default `True`) as a one-line way to get the exact comparison the milestone spec asks for** ("compare traces from: simple chatbot, tool-using agent") — flipping it makes `/chat` behave exactly like Milestone 2's direct call, same endpoint, same provider config, no separate code path to maintain in parallel. `scripts/smoke_test_agent.py` demonstrates both shapes in one run without needing to restart the server (a client can't toggle a running server's own env var per-request, so the script calls both code paths directly in-process instead).

**Surprises worth carrying forward**: the max-iterations off-by-one above is the significant one — full detail in `docs/EXPERIMENTS.md`, including the two purpose-built fake providers (one that ignores `tools=None`, one that respects it) used to pin both safety nets independently rather than trusting that a single passing test meant both mechanisms worked.

Deliberately not built: real tool-selection reasoning in the mock path (a fixed trigger table, not a planner — real reasoning is `AnthropicProvider`'s job, unverified live in this environment for lack of an API key), conversational memory across separate `/chat` calls (still Milestone 7), and any Langfuse Prompt Management for `SYSTEM_PROMPT` (Milestone 8) despite it now needing to mention tool use.

---

## Milestone 6 — Production-like trace design

**Goal**: the spec names eight specific taxonomy items — consistent names, metadata, tags, environment, application version, feature flags, agent version, error metadata — plus documenting the taxonomy and showing good vs. poor trace design. Of those eight, three already existed from earlier milestones (consistent names since M1, environment since M2, application version — `release` — since M1); this milestone adds the remaining five and writes down the taxonomy as a first-class document rather than leaving it implicit across five milestones of code.

**What we chose and why**:

- **`version` is a second, independent axis from `release`, not a synonym for it.** Before writing any code, I introspected `propagate_attributes`'s own docstring rather than guessing at the distinction, and it states the intended use directly: *"Version identifier for parts of your application that are independently versioned, e.g. agents."* That's a literal match for what the milestone spec calls "application version" vs. "agent version" as two separate items — `Settings.app_version` stays the client-level `release` (set once, M1), and a new `Settings.agent_version` is propagated per-trace only on the agent path, since the direct-LLM path isn't running agent code at all and has nothing to version.

- **`agent_enabled` becomes both a tag and metadata, not just a Settings flag.** It already existed since M5 as a Python-level branch; this milestone is the first time its value is actually recorded *on the trace itself*. Tag (`"agent"`/`"direct-llm"`) because it's exactly the kind of coarse, binary segment you'd filter the whole trace list by; also in `metadata` alongside `llm_provider`, since metadata is the right place for structured facts you want visible once you're already looking at one trace, distinct from tags' job of bucketing many traces.

- **Error metadata went where the failure actually happens, not where it's caught.** The original design already had `tools_node` catching every tool-call exception and turning it into text the agent could recover from — correct application behavior, but the resulting `execute_tools` span carried no `level`/`status_message` at all. Worse, tracing through the actual call path revealed a case invisible at *any* observation level: a tool call with a missing required argument fails during Python's own `func(**call.arguments)` argument binding, which happens *before* the tool function's own `with` block — and its `tool`-type observation — ever opens. `search_hotels`'s own span never has a chance to record that failure, because it never opens. The fix lives in `tools_node`: track which calls failed (unknown-tool and argument-binding failures both included) and set `level="ERROR"` with a `status_message` naming them on the one observation (`execute_tools`) that's guaranteed to be open regardless of which failure mode occurred. `chat.py` got the same treatment at the trace root, for any exception the agent loop itself doesn't already turn into a graceful message.

- **Verified fully offline, against the real SDK, not a hand-rolled fake.** Testing "did the right Langfuse attributes get set" without either a live Langfuse instance or trusting the code by inspection alone led to introspecting `langfuse._client.attributes` for the actual OTel attribute keys (`langfuse.trace.tags`, `langfuse.trace.metadata.*`, `langfuse.version`, `langfuse.observation.level`), then constructing a real (non-mocked) `Langfuse` client with `span_exporter=InMemorySpanExporter()` — no network call, but the exact same attribute-setting code path production uses. `LangfuseResourceManager` turned out to be a singleton keyed by `public_key` (confirmed by reading its `__new__`), so each test uses its own unique throwaway key to get a fresh in-memory exporter rather than reusing another test's. Full detail, including a one-off experiment script that surfaced this, in `docs/EXPERIMENTS.md`.

**Surprises worth carrying forward**: this environment's self-hosted Langfuse deployment runs in v4 "events_only" mode, which disables the trace-read REST API entirely (`GET /api/public/traces/{id}` returns a 501-style message naming this explicitly) — and the sandboxed browser pane in this environment cannot reach the host's `localhost`, so the usual "verify live via curl + browser screenshot" step from M1–M5 wasn't available here. The in-memory-exporter tests are a strictly stronger form of verification for the attribute-setting logic itself (they assert on the literal wire-format attributes, not a UI rendering of them), but they don't confirm how Langfuse's own UI displays a `version` set via `propagate_attributes` versus one set via `release` — that visual distinction is worth checking manually (see the Milestone 6 report for what to look at).

Deliberately not built: a general-purpose feature-flag *system* (a flags table, remote config, per-user targeting) — `agent_enabled` is this project's only real flag today, and building infrastructure for flags that don't exist yet would be speculative. The taxonomy in `docs/TRACE_DESIGN.md` documents the pattern so a second flag, when one is actually needed, has an established place to go.

---

## Milestone 7 — Sessions and multi-turn analysis

**Goal**: the spec asks for "durable or semi-durable conversational state appropriate for the educational system," multi-turn evaluation examples, and the ability to analyse cost/token-growth/repeated-tools/latency/context-accumulation across a conversation. Going in, the gap was concrete and already flagged by name in this project's own docs: `session_id` has grouped traces in Langfuse since Milestone 2, but the LLM itself never saw a prior turn — every `/chat` call built `[system, user]` from scratch. The Streamlit UI's own sidebar said this outright ("the LLM does not yet see earlier turns").

**A scoping call, disclosed like M4/M5's**: the spec's five "Analyse" bullets (cost per conversation, token growth, repeated tools, total latency, context accumulation) read as analysis *questions to be able to answer*, not five features to build. Langfuse's own Sessions view already aggregates cost/latency/tokens per `session_id` — the FastAPI/Sessions sections of the spec explicitly warn against "manually duplicating functionality already handled correctly by the SDK." So this milestone's actual work was giving the agent real memory (the prerequisite for any of those five questions being interesting at all — a session with one turn has no growth to observe) plus one direct, cheap addition (`metadata.history_turns` per trace) rather than a custom analytics endpoint Langfuse already provides.

**What we chose and why**:

- **In-memory, not a database.** "Semi-durable... appropriate for the educational system" is read here as license to add a `dict[session_id, list[Turn]]` behind an `asyncio.Lock`, not Postgres/Redis. Nothing else in this project has a database; adding one just for conversation memory would be exactly the kind of infrastructure-before-need this project's minimalism elsewhere argues against. The honest cost, documented rather than hidden: state is per-process and gone on restart, and a real multi-worker production deployment would need shared storage instead — Langfuse's own trace history remains the durable record of what actually happened, regardless of what this store remembers.

- **History is replayed as clean `[user, assistant]` pairs, not the full internal agent scratchpad.** A turn's tool-calling round trip (`tool_calls`, `role="tool"` messages) is an implementation detail of producing *that turn's* final answer, not part of the conversation transcript — replaying it into a later turn would also risk violating Anthropic's tool_use/tool_result adjacency requirements across a turn boundary neither Anthropic nor this app's own translation layer was designed to span. Storing only the final exchange per turn (`Turn.user_message`, `Turn.assistant_message`) sidesteps that entirely, at the cost of the replayed history not containing which tools were used to produce a past answer — an acceptable trade for conversational continuity, not something the agent's own tool selection reasoning depends on.

- **`Settings.max_history_turns` (default 10), not unbounded replay.** This is the milestone's own "did context size grow excessively?" question, answered as a real bound rather than left as an observation to make after the fact. `ConversationStore.append_turn` trims the oldest turns first once a session exceeds the limit — a session that runs forever costs a bounded, predictable amount of context per turn, not a linearly growing one.

- **`GET /sessions/{session_id}` is deliberately a different thing from Langfuse's own Session view**, not a thin proxy for it — it returns this app's own stored conversation content (for a client that wants to display or restore a conversation, e.g. after a page reload, without a Langfuse API key), while cost/latency/token analysis stays exactly where the spec says it belongs: Langfuse's native per-session aggregation. Two different questions ("what was said" vs. "how much did it cost"), two different, non-overlapping mechanisms answering them.

- **A failed turn is never remembered.** `chat.py` only calls `store.append_turn(...)` after the try/except around the agent/provider call succeeds — an exception propagates out before that line is ever reached. This matters for the same reason M6's error-metadata work mattered: a turn that failed shouldn't silently poison every later turn's context with a broken or partial exchange.

**Surprises worth carrying forward**: none this time in the sense of a bug caught mid-build — the design questions (in-memory vs. database, full scratchpad vs. clean pairs, bounded vs. unbounded) were resolved before writing code, informed directly by this milestone's own spec wording and the "avoid duplicating the SDK" guidance from earlier in the spec. The one thing worth naming: `MockProvider`'s `_decide()` needed no changes at all to support multi-turn history — it already only ever looked at the *last* user message, so a longer `messages` list upstream was invisible to it by construction. That's a quieter version of the same "nesting composes for free" property M4/M5 found with Langfuse spans — this time for message-list length instead of trace structure.

Deliberately not built: the UI does not fetch `GET /sessions/{id}` to restore history on load — its own client-side `st.session_state.messages` already displays the transcript, and adding a redundant network round trip per rerender for data the UI isn't missing would be scope beyond what this milestone needs. Multi-turn *evaluation* examples (test cases that specifically exercise conversation memory) are deferred to Milestone 9, which is where this project's evaluation framework as a whole begins.
