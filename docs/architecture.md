# Architecture — Travel AI Concierge

> Last updated: Milestone 17  
> This document evolves with the project. Each milestone adds to it.

## Overview

The Travel AI Concierge is an agentic AI application with comprehensive LLM observability via Langfuse. Its primary purpose is to demonstrate production-quality AI engineering practices using a realistic travel domain as the workload.

As of this writing, everything in the diagram below is real **except** the OpenAI provider and `build_itinerary` tool (shown for scale — future, unimplemented) and the Travel AI Search API integration (Milestone 18, optional). The Chat UI calls `POST /chat` over HTTP, which runs the LangGraph agent by default (`Settings.agent_enabled`, default `True`) — the agent decides whether to answer directly or call a tool, executes it if so, and loops back until it has a final answer. Since Milestone 7, each call also carries real conversation memory: prior turns in the same `session_id` are replayed into context, not just grouped in Langfuse. Since Milestone 8, the system prompt itself is fetched from Langfuse Prompt Management rather than hardcoded — see [Prompt Management](#prompt-management-m8) below. Since Milestone 9, a local deterministic evaluation harness (`make evaluate`) runs a 39-case dataset through this same agent — see "Evaluation Framework" below. Since Milestone 10, that same dataset can also be published to a real Langfuse Dataset and run as a named, comparable experiment (`make sync-eval-dataset`, `make experiment-prompt-v1`/`-v2`) — see "Langfuse Datasets and Experiments" below. Since Milestone 11, cases can also be scored qualitatively by an LLM judge (relevance, helpfulness, groundedness, constraint satisfaction, itinerary coherence) alongside Layer 1's deterministic checks — see "LLM-as-Judge" below. Since Milestone 12, a real user can rate a response too — thumbs up/down plus an optional comment, sent to Langfuse as a genuine score (Layer 3) — see "Human Feedback" below. Since Milestone 13, the evaluation dataset is also scored on the *path* the agent took, not just the final text — see "Agent Trajectory Evaluation" below. Since Milestone 14, two agent configurations can be compared locally on quality, latency, tokens, and estimated cost (`make cost-latency-experiment`) — see "Cost and Latency Experiments" below. Since Milestone 15, controllable fault injection (`make fault-injection-lab`) demonstrates and verifies graceful degradation for the project's named failure modes — see "Failure and Resilience Laboratory" below and [docs/DEBUGGING_WORKFLOWS.md](DEBUGGING_WORKFLOWS.md). Milestone 16 walks through a real, deliberately-injected agent regression diagnosed from a Langfuse trace and fixed with a measurable improvement — see "Observability-Driven Debugging" below and [docs/EXPERIMENTS.md](EXPERIMENTS.md). Since Milestone 17, `make eval-ci` gates on a committed baseline (`quality_pass_rate`/`trajectory_healthy_rate`, both configurable thresholds) instead of only checking for crashed cases — see "Regression Detection" below. See the [Trace Structure](#trace-structure) section for what a real request actually produces, and [Milestone Status](#milestone-status) for what's implemented per milestone.

```
┌─────────────────────────────────────────────────────────────┐
│                        Chat UI (Streamlit)                  │
│         user messages · session continuity · debug panel    │
└───────────────────────┬─────────────────────────────────────┘
                        │ HTTP
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI (port 8000)                      │
│        POST /chat · GET /sessions/{id} · GET /health        │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                  Travel AI Concierge Agent                  │
│               (LangGraph: agent ↔ tools loop)               │
│                                                             │
│             agent ──tool call──▶ execute_tools              │
│                 ▲                         │                 │
│                 └─────────────────────────┘                 │
│                 no tool call ▶ final answer                 │
└─────┬───────────────────────────────────┬───────────────────┘
      │                                   │
      ▼                                   ▼
┌──────────────┐                 ┌────────────────────┐
│  LLM Provider│                 │   Travel Tools     │
│   (Protocol) │                 │                    │
│              │                 │ search_destinations│
│ Anthropic    │                 │ search_hotels      │
│ OpenAI       │                 │ get_destination    │
│ Mock         │                 │ build_itinerary    │
└──────────────┘                 └──────────┬─────────┘
                                            │
                              ┌─────────────┴──────────────┐
                              │                            │
                    ┌─────────▼──────────┐  ┌─────────────▼──────┐
                    │ Synthetic Travel   │  │  Travel AI Search  │
                    │ Provider (local)   │  │  API (optional,    │
                    │                   │  │  Milestone 18)     │
                    └───────────────────┘  └────────────────────┘

Instrumentation (all components above emit to Langfuse):

┌─────────────────────────────────────────────────────────────┐
│                          Langfuse                           │
│                                                             │
│  traces · spans · generations · sessions · users            │
│  prompts · datasets · experiments · scores · evaluations    │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### Chat UI ✅ Implemented (M3)

Streamlit app (`ui/streamlit_app.py`), a separate process that talks to FastAPI exclusively over HTTP — it never imports agent/provider code. Responsible for:
- Multi-turn transcript display (client-side history) — since M7, the backend itself also remembers the conversation server-side, so what the UI displays and what the LLM actually sees are the same content, not just a client-side illusion of memory
- Session continuity (`session_id` persisted per browser session) and reset ("New conversation")
- A stable, synthetic `user_id` per browser session (not per message)
- Debug panel: session/user ID, model, client-measured latency, and a link to the trace in Langfuse
- Thumbs up/down (`st.feedback`) plus an optional comment, sent to Langfuse as a real score (Milestone 12) — see "Human Feedback" below
- Clean error display when the API is unreachable or returns an error, and when the debug panel's Langfuse trace-link lookup fails (unreachable host, bad credentials, timeout — caught broadly since this is a non-critical convenience, not the core chat feature)

### FastAPI ✅ Implemented (M0, M2, M5, M6, M7, M8, M12)

The HTTP boundary. Accepts chat requests, manages session IDs, and returns responses. Does not contain agent logic itself — it delegates. Responsible for:
- Validating request schemas (Pydantic) — `api/schemas/chat.py`
- Opening the root Langfuse trace per request and setting session/user/environment/tags/metadata/version attribution — `api/routes/chat.py` (M6 adds tags, metadata, and the `agent_version` axis; see [TRACE_DESIGN.md](TRACE_DESIGN.md))
- Fetching prior turns from the conversation store and replaying them ahead of the current message before calling the agent/provider, then persisting the new turn on success (M7 — see "Conversation Memory" below)
- Fetching the system prompt from Langfuse Prompt Management before building `messages`, and linking it to the turn's generation(s) (M8 — see [Prompt Management](#prompt-management-m8) below)
- Delegating to the agent graph by default (`Settings.agent_enabled`, M5), or the LLM provider directly when `agent_enabled=False` (the M2 shape, kept as a live comparison point rather than deleted)
- Recording `level="ERROR"`/`status_message` on the root trace if the turn raises, before re-raising (M6)
- Returning trace IDs, but only when `Settings.debug` is true; always returning an opaque `message_id` regardless of debug (M12 — see "Human Feedback" below)
- `GET /sessions/{session_id}` — returns this app's own stored turn history for a session, 404 if none exists (M7)
- `POST /feedback` — thumbs up/down plus an optional comment, sent to Langfuse as a real score (M12)

### Prompt Management (M8)

`src/travel_ai_concierge/prompts.py`'s `get_system_prompt()` fetches the system prompt from Langfuse Prompt Management by name (`travel-concierge-system`) and label (`Settings.prompt_label`, default `"production"`), instead of a hardcoded string. Two versions are seeded by `scripts/seed_prompts.py` (`make seed-prompts`): v1 labeled `production` (the original Milestone 2 text, encourages tool use), v2 labeled `staging` (a more directive version that requires tool use for destination/hotel facts). Flipping `PROMPT_LABEL=staging` switches `/chat` to v2 with no code change — the same "flip a setting" pattern `agent_enabled`/`llm_provider` already use.

**Local fallback, not a hard dependency**: `get_system_prompt()` passes `fallback=SYSTEM_PROMPT_FALLBACK` to the SDK's `get_prompt()` — if Langfuse is unreachable, or the prompt hasn't been seeded yet, the call never raises; it returns a synthetic `PromptClient` (`.is_fallback=True`) carrying the same text as v1. This is the milestone spec's explicit requirement ("do not make the application unable to start if remote prompt retrieval fails"), verified directly in `tests/unit/test_prompts.py` against a real (non-mocked) `Langfuse` client pointed at an intentionally-unreachable host.

**Prompt linking**: `chat.py` passes the fetched prompt to `propagate_attributes(prompt=prompt)`, which the Langfuse backend uses to link every generation in that turn to the exact prompt version that produced it — real Langfuse prompt-usage analytics, not a custom field. One real, non-obvious behavior confirmed by reading the SDK's own propagation source: **fallback prompts are never linked** — when Langfuse is down, the turn still completes correctly, it just has nothing to link to (since a fallback isn't a real served version). `prompt_version`/`prompt_fallback` are also added to trace metadata directly, so this is visible without opening the prompt link.

### Conversation Memory ✅ Implemented (M7)

An in-process, in-memory store (`conversation/store.py`'s `ConversationStore`, `dict[session_id, list[Turn]]` behind an `asyncio.Lock`) giving the agent real multi-turn memory — before this milestone, `session_id` only grouped traces in Langfuse; the LLM itself never saw a prior turn. `api/routes/chat.py` reads a session's history before building the message list, replays it as alternating user/assistant messages ahead of the current one, and appends the new turn only after a successful response (a failed turn is never remembered, so it can't poison every later turn's context).

Bounded by `Settings.max_history_turns` (default 10) — the store keeps only the most recent N turns per session, trimming the oldest first. This is a deliberate answer to the milestone spec's own "did context size grow excessively?" question: unbounded history *is* that failure mode, not just a hypothetical cost concern.

**Deliberately in-memory, not a database**: "semi-durable... appropriate for the educational system" (the spec's own wording) is read here as license to not introduce Postgres/Redis for app-level state when nothing else in this project needs a database. The real, durable record of what happened in a session is already Langfuse's own trace history — this store only needs to survive one running process, not a restart. A real production deployment running multiple worker processes would need shared storage (Redis, a database) instead, since this store is local to whichever process handled the request.

### Travel AI Concierge Agent ✅ Implemented (M5)

A hand-written LangGraph graph (`agent/graph.py`) — no `langgraph.prebuilt` agent, per [ADR-001](decisions/ADR-001-agent-framework.md). Two nodes:
- **`agent`** (`agent/nodes.py`) — one LLM call with the travel tools offered. Opens a real Langfuse **`agent`** observation (a distinct type, like `tool` in M4). If the model requests a tool, routes to `tools`; otherwise the graph ends.
- **`tools`** — executes every tool call the last `agent` message requested, wrapped in one `execute_tools` span so multiple calls in one turn nest together; each individual call is still its own `tool` observation underneath (M4, unchanged). Since M6, `execute_tools` records `level="ERROR"` with a `status_message` naming which call(s) failed — see [TRACE_DESIGN.md](TRACE_DESIGN.md#3-error-metadata) for why this needed to live here rather than inside the individual tool functions.

Two independent safeguards against an unbounded loop (`Settings.agent_max_iterations`, default 5): the `agent` node withholds tools once about to make the last allowed call (so a well-behaved provider produces a clean final answer, not an empty-content dead end), and routing separately hard-stops regardless of the last message's content (so a provider that ignores having no tools still can't loop forever). See [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-5--explicit-agentic-ai-workflow) for the off-by-one bug this design went through before it was correct.

### LLM Provider ✅ Implemented (M2, extended M5)

A Protocol (`providers/llm/base.py`) with two concrete implementations: `MockProvider` (deterministic, offline) and `AnthropicProvider` (real, wraps the Anthropic Messages API). Both record their own Langfuse `generation` for every call — same span name and shape regardless of which is configured (`LLM_PROVIDER` in `.env`), capturing model, tokens, and cost details. `get_llm_provider()` selects between them from `Settings`. Since M5, `complete()` accepts an optional `tools` parameter and `LLMResponse` may carry `tool_calls` — `AnthropicProvider` translates these to/from Anthropic's actual tool-calling shapes (verified via SDK introspection, not assumed); `MockProvider` uses a small fixed keyword-trigger table as a deterministic stand-in for real tool selection.

### Travel Tools ✅ Implemented and connected (M4, wired M5)

Plain, synchronous, typed Python functions (`tools/travel_tools.py`) backed by a small hand-authored synthetic dataset (`data/synthetic/`: 8 destinations, 18 hotels) generated by `scripts/generate_data.py`. Each call opens a real Langfuse **`tool`** observation — a distinct type from `span`/`generation`, with its own UI filter facet — capturing input parameters and a result summary (e.g. `result_count`). Callable standalone (`make tools-smoke-test`) or, since M5, from within the agent's `tools` node — the same code, unchanged, nests correctly under whichever trace is active either way.

Three tools, described to the LLM via `tools/specs.py`'s `TOOL_SPECS` (JSON Schema, matching Anthropic's `tools` parameter format directly):
- `search_destinations(tags, climate, limit)` — filters by tag overlap and/or exact climate match
- `search_hotels(destination_id, family_friendly, max_price_band, limit)` — scoped to one destination, filtered by family fit and a price-band ceiling (`budget ≤ mid ≤ luxury`)
- `get_destination_information(destination_id)` — single-record lookup, `None` if not found

### Evaluation Framework (M9)

`evaluation/` — a local, deterministic evaluation harness, deliberately independent of Langfuse datasets (that's Milestone 10's job; the spec is explicit: "Do not require Langfuse datasets yet for the core evaluation engine"). Three parts:

- **`data/evaluation/cases.json`** (`make generate-eval-dataset` regenerates it from `scripts/generate_evaluation_dataset.py`) — 39 hand-authored cases (`EvaluationCase`) covering all 20 query classes the spec names (destination/hotel recommendation, family/couples holiday, budget/luxury, beach/city/culture/nightlife/quiet/food-wine, itinerary planning, vague requests, multi-constraint, needs-clarification, one-tool, multi-tool, impossible-constraint, contradictory-preferences), grounded in the real synthetic destinations/hotels — real IDs, tags, and price bands, not invented ones.
- **`evaluation/evaluators.py`** — five Layer 1 (deterministic — Layer 2's LLM judge is a separate mechanism, see "LLM-as-Judge" below) evaluators: `tool_usage_matches_expected`, `tool_arguments_satisfy_constraints`, `response_is_nonempty`, `response_references_tool_result` (a groundedness *proxy* — substring match against what a tool actually returned, not semantic scoring), and `clarifying_question_when_expected`. Each returns pass/fail/**skip** — skip for a case a given check doesn't apply to, so out-of-scope cases aren't counted as failures.
- **`evaluation/runner.py`** — runs each case through the *real* agent graph (`get_agent_graph()`, the same singleton `/chat` uses), always the agent path regardless of `Settings.agent_enabled`, since evaluation exists specifically to test tool-selection. Each case gets its own real Langfuse trace (`travel_concierge_turn`, tagged `evaluation` + its query class) — inspectable in Langfuse exactly like production traffic, not a parallel invisible process.

`make evaluate` (`scripts/run_evaluation.py`) runs the full suite, writing both a human-readable console report and a machine-readable JSON report (`data/evaluation/results/latest.json`, gitignored — a run artifact, not part of the dataset). `make eval-ci` adds `--ci`, which exits non-zero if a case *crashed*, and, since Milestone 17, also if `quality_pass_rate` or `trajectory_healthy_rate` regressed past its threshold against the committed baseline — see "Regression Detection" below.

**Honest limitation, printed directly in the report**: under the default `MockProvider`, most tool-usage/constraint/clarification checks fail — not because the agent is broken, but because Mock is a fixed keyword-trigger table, not real reasoning, and never asks a clarifying question (`"hotel"` is still a single hardcoded `search_hotels` call; `"destination"`/`"trip"` detect tags from a small fixed vocabulary as of Milestone 16, but neither is anything like real language understanding). The dataset's expectations describe what a *real* agent should do; a meaningful pass rate needs `LLM_PROVIDER=anthropic`. The evaluator *logic itself* is tested separately and offline against scripted fake providers with known behavior, not against Mock's real limitations — see `tests/unit/test_evaluators.py` and `test_evaluation_runner.py`.

These evaluators only ask "does the text look okay" or "did the agent do the right thing" as flat pass/fail/skip — Milestone 13 separates the two questions explicitly and adds trajectory-specific metrics (precision/recall over tool calls, repeated calls, agent steps) — see "Agent Trajectory Evaluation" below.

### Langfuse Datasets and Experiments (M10)

Publishes the same `data/evaluation/cases.json` used by Milestone 9 into a real Langfuse Dataset, and runs it as a named, comparable experiment — using the SDK's own first-class `run_experiment()` API (`langfuse.experiment`), discovered and verified against the real local stack before designing around it, rather than hand-rolling dataset-item/trace/score linking.

- **`evaluation/langfuse_sync.py`** — `sync_dataset()` (`make sync-eval-dataset`) creates/updates a Dataset named `travel-concierge-eval-cases`, one item per case, upserted by the case's own `id` (the SDK's documented dedup mechanism) — safe to re-run after editing `cases.json`. The local JSON file stays the source of truth; this only mirrors it, per the spec's own framing ("Langfuse is an execution/analysis layer, not the only source of truth for test cases").
- **`evaluation/experiment.py`** — `run_named_experiment(run_name=...)` reuses Milestone 9's `run_case()` and all five evaluators completely unchanged, wrapped in a small adapter that maps a dataset item's `input`/`expected_output`/`metadata` back to an `EvaluationCase` and an `EvaluatorResult` (pass/fail/skip) to the SDK's `Evaluation` shape (`1.0`/`0.0`/no evaluation at all, respectively) so Langfuse's own automatic score-averaging works correctly. Two more evaluator functions are appended to every run beyond that original pair: `_judge_evaluator` (Milestone 11, opt-in via `with_judge=True` — a real LLM call, real cost) and `_trajectory_evaluator` (Milestone 13, always appended, no flag — see "Agent Trajectory Evaluation" below for why the two are treated differently). Each item's task execution is traced and linked to the dataset run automatically by the SDK — nested tracing inside the task function composes correctly with that linking, the same "nesting is free" property established for spans since Milestone 4.
- **The worked example**: `make experiment-prompt-v1` / `make experiment-prompt-v2` run the identical dataset with `PROMPT_LABEL` set to `production`/`staging` respectively, under two different `run_name`s on the same Langfuse dataset — exactly the spec's "Experiment A: Prompt v1 vs Prompt v2", comparable side by side via the printed `dataset_run_url`.

**Deliberately not recomputing cost/token usage locally**: the spec asks to "Record: quality, latency, cost, token usage." Quality comes for free from the SDK's own per-evaluator averaging; cost and token usage are already captured natively per generation (unchanged since Milestone 2) and shown in Langfuse's own dataset-run comparison view — duplicating that arithmetic locally would need plumbing usage totals through `AgentState`, a change well beyond this milestone's actual scope (dataset sync + experiment running), and would directly contradict the spec's own "avoid manually duplicating functionality already handled correctly by the SDK." See [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-10--langfuse-datasets-and-experiments) for the full reasoning.

**Testing**: dataset/experiment creation has no offline fallback (unlike Milestone 8's prompts) — the pure adapter logic is unit-tested offline (`tests/unit/test_experiment_adapters.py`), while the actual sync-and-run flow is a real integration test against a throwaway dataset (`tests/integration/test_langfuse_dataset_experiment.py`), matching the existing `test_langfuse_connectivity.py` precedent.

### LLM-as-Judge (M11)

`evaluation/judge.py` — Layer 2 evaluation (qualitative, not mechanical): a `JudgeProvider` protocol with two implementations, opt-in everywhere (never run by default, since real judging costs latency and money):

- **`FakeJudgeProvider`** (default, `Settings.judge_provider="fake"`) — deterministic, offline, free. Derives its scores directly from Milestone 9's own evaluator outcomes (e.g. `relevance` from `tool_usage_matches_expected` + `response_is_nonempty`), and every rationale says so explicitly — it is a test double for the judge *interface*, not an attempt at real judgment.
- **`AnthropicJudgeProvider`** (`Settings.judge_provider="anthropic"`) — one real LLM call per case (all applicable dimensions scored together, not one call per dimension), instrumented as a genuine Langfuse **`evaluator`** observation — a real, distinct type (verified via SDK introspection), the same principle as `tool`/`agent`. Output is strict JSON, parsed with `_parse_judgments()`; a malformed or out-of-range response raises `JudgeParseError` rather than silently falling back to a placeholder score — "do not blindly trust LLM-as-judge scores" (spec) applies to a broken parse too, not just a suspicious one.

Five dimensions, matching the spec's own M11 list: `relevance`, `helpfulness`, `groundedness`, `constraint_satisfaction` (always scored) and `itinerary_coherence` (only for `itinerary_planning`-class cases — asking a judge to score a dimension that doesn't apply would repeat M9's own mistake-to-avoid with evaluator `skip`).

**Reused, not duplicated**, across both existing evaluation surfaces from M9/M10:
- `make evaluate-judged` (`scripts/run_evaluation.py --with-judge`) — the local report plus a judge summary, written to `data/evaluation/results/latest-judged.json`.
- `run_experiment.py --with-judge` — pushes `judge_<dimension>` scores as additional Evaluations on the same Langfuse dataset run, alongside Layer 1's deterministic ones.

One `JudgeProvider` abstraction, two call sites — the same reuse pattern M10 established for M9's own evaluators.

**Documented methodological limitations** (the spec requires this explicitly, not as an afterthought — full detail in `evaluation/judge.py`'s module docstring):
- **Not an independent model family.** This project has one real LLM vendor (Anthropic) — `AnthropicJudgeProvider` is Anthropic judging Anthropic's own output family, not the "independent judge model family" the spec asks to prefer where possible. `Settings.judge_model` is independently configurable from `Settings.llm_model` as a partial mitigation (a different capability tier, still the same vendor).
- **Self-preference / verbosity bias** — documented in the evaluation literature, not controlled for here.
- **Stochasticity** — `AnthropicProvider.complete()` never sends `temperature` at all (no such parameter exists in the installed SDK version — M2's own finding), so identical inputs are not guaranteed identical scores. `tests/integration/test_llm_judge.py` demonstrates this empirically (judges the same case twice, prints both score sets, asserts nothing about them matching) rather than just asserting the limitation in prose.
- **Judged on the conversation alone** — the judge never sees this project's own `expected_tools`/`expected_arguments` test fixtures, only the user's message, the agent's final response, and the raw tool results. That keeps its "constraint satisfaction" score an independent read of the conversation rather than a check against our own answer key (which Layer 1 already does).

### Human Feedback (M12)

Layer 3 of the project's evaluation architecture (alongside Layer 1's deterministic evaluators, M9, and Layer 2's LLM-as-judge, M11) — a real end user's own opinion, sent to Langfuse as a genuine score rather than the visual-only placeholder Milestone 3 shipped.

- `POST /feedback` (`api/routes/feedback.py`) — `thumbs_up: bool` (required) plus an optional `comment: str`. Creates one `create_score(name="user_thumbs", value=1.0|0.0, data_type="NUMERIC", trace_id=..., ...)` call carrying **`trace_id` only**. An earlier version also passed `session_id` on the same call — the Python SDK's signature accepts both, but Langfuse's ingestion API rejects a score body carrying more than one of `traceId`/`sessionId`/`datasetRunId`, and does so silently from the caller's point of view (`create_score()`'s batch export runs on a background thread and only logs the rejection, never raises) — every score was dropped until this was caught by manually clicking feedback in the UI and finding nothing in Langfuse. Full story in [docs/EXPERIMENTS.md](EXPERIMENTS.md). Nothing is lost by dropping `session_id` from the score itself: the scored trace already carries `session_id` from when the turn was created (`chat.py`, M2), so a low-rated response is still findable either per-trace or rolled up per-conversation in Langfuse's own UI — no custom analytics dashboard built for this, consistent with the project's running principle of not duplicating what the SDK/UI already does correctly (established since M8).
- **The `message_id`/`trace_id` split.** `ChatResponse.trace_id` is deliberately hidden outside `Settings.debug` (a production client shouldn't see raw Langfuse trace IDs), but feedback has to work in production too. `ChatResponse` and `SessionTurn` both now also carry `message_id` — an opaque id (`Turn.turn_id`, a `uuid.uuid4().hex`), always returned regardless of debug mode. `POST /feedback` resolves it back to the real `trace_id` server-side via `ConversationStore.find_turn()` (a new lookup method alongside M7's existing per-session turn list), so the client never needs to know the real trace id at all.
- **Deterministic `score_id`** (`feedback-<message_id>`) — the same id-based-upsert convention `create_dataset_item()` used in M10 — so a comment sent after an initial thumbs click updates that same logical score instead of creating a second, disconnected one. This specific upsert behavior is *not* independently verified against a real Langfuse read (this deployment runs "events_only" mode, which has no read API — see [docs/langfuse.md](langfuse.md)); it's documented as a best-effort assumption, not a confirmed fact.
- **Chat UI**: `st.feedback` (thumbs) plus an `st.form`-wrapped optional comment box. `st.feedback` is a *stateful* widget — unlike `st.button`, it keeps returning the same selection on every later rerun, not just the click's own — so the UI guards submission with a `feedback_submitted` flag in `st.session_state` to avoid resending the same rating on an unrelated later rerun (e.g. sending another chat message). Covered by a dedicated regression test, `test_feedback_is_not_resubmitted_on_a_later_unrelated_rerun`. A successful "Send comment" click also calls `st.rerun()` explicitly, so the comment form disappears on the very next render instead of lingering until an unrelated interaction happens to rerun the script — `test_optional_comment_sent_after_feedback_reuses_the_recorded_rating` pins this with `len(at.text_input) == 0` right after the click.
- **Score linking, corrected in practice**: the score carries `trace_id` only, never also `session_id` — Langfuse's ingestion API accepts exactly one of `traceId`/`sessionId`/`datasetRunId` per score and silently drops (server-side 400, never surfaced by `create_score()`/`flush()`) a score carrying more than one. An earlier version of this route passed both and every score was rejected; caught live in the browser, not by any test — full account in [docs/EXPERIMENTS.md](EXPERIMENTS.md). In Langfuse's own UI, this means a `user_thumbs` score's **Observation** and **Session** columns are always empty by design (no `observation_id` is set either, since the feedback is about the whole response, not one internal step) — the score is still findable per-session because the *trace itself* carries `session_id` from when it was created, not because the score repeats it.
- **Deliberately not built**: a 1-5 star rating (the spec's broader Layer 3 section mentions it, but Milestone 12's own scoped bullet list only asks for thumbs + optional comment); a comment-without-a-rating flow (`create_score()` requires a `value`, so a comment always attaches to an existing thumbs rating); any custom "browse low-rated traces" view (Langfuse's own trace filtering, e.g. `user_thumbs < 1`, already covers this).

### Agent Trajectory Evaluation (M13)

Final-answer checks (Layer 1's `response_is_nonempty`/groundedness proxy) can't tell you *how* the agent got to its answer — an agent that calls the wrong tool, calls one twice, or skips a needed clarification can still produce text that passes every text-quality check. This is the concrete case the project spec asks to demonstrate: *good answer ≠ good trajectory*, and its inverse, *poor answer despite reasonable trajectory*.

- **`evaluation/trajectory.py`** — `TrajectoryMetrics` (`total_tool_calls`, `unique_tools_called`, `missing_tools`, `unnecessary_tools`, `repeated_tools`, `tool_precision`, `tool_recall`, `agent_steps`, plus both directions of clarification correctness) and `compute_trajectory_metrics(case, result)`, a pure function over data `run_case()` already collects — no LLM call, no added cost. Precision/recall are computed over the *unique* tool-name set (so a correct-but-repeated call doesn't itself hurt either score — that's what `repeated_tools` is for); `tool_precision` is `None` (not `0.0`) when no tool was called at all, since precision of zero calls is undefined, while `tool_recall` is `1.0` when no tool was expected (nothing could have been missed) — a deliberate asymmetry, not an inconsistency.
- **`evaluation/trajectory_report.py`** — compares the trajectory axis against Layer 1's own text-quality evaluators (`response_is_nonempty`, groundedness proxy — explicitly *not* the tool-selection evaluators, which would double-count the same signal on both axes) and classifies each case as `aligned`, `good_answer_poor_trajectory`, or `poor_answer_good_trajectory`. Parallels `judge_report.py`'s shape (a separate module, not merged into `report.py`), same reasoning: a different kind of comparison than a flat pass/fail/skip list.
- **Always on, unlike `--with-judge`.** Trajectory metrics cost nothing extra (no LLM call), so `run_evaluation.py` computes and prints them unconditionally on every `make evaluate`/`eval-ci`/`evaluate-judged` run (`data/evaluation/results/latest-trajectory.json`), and `run_named_experiment()` appends a `_trajectory_evaluator` to the evaluator list unconditionally too — the same "free, always computed" treatment Layer 1's own adapters already get, distinct from the judge's real-cost opt-in.
- **Found real divergence in the existing dataset, before writing any new cases.** Re-running `make evaluate` and reading every failure by hand (before designing the metrics) surfaced two already-existing cases — `requires-clarification-002` and `impossible-constraint-001`, both containing the literal keyword `"hotel"` — where `MockProvider` calls an unnecessary tool, yet the resulting text is non-empty and echoes the tool's own JSON, so the text-quality checks pass while the trajectory checks fail: a live, unmodified-dataset instance of *good answer ≠ good trajectory*. Full account in [docs/EXPERIMENTS.md](EXPERIMENTS.md).
- **`poor_answer_good_trajectory` cannot occur live under `MockProvider`, confirmed empirically, not assumed.** Across all 39 cases, `response_is_nonempty`/the groundedness proxy never fail — Mock's text is always derived directly from whatever it just did (echo the message, or echo the tool's JSON), so a correct trajectory and a passing final-answer check are the same event under Mock; they cannot come apart. Demonstrated instead with one explicitly-labeled hand-built fixture (`test_poor_answer_good_trajectory_is_a_hand_built_synthetic_example`, `tests/unit/test_trajectory.py`) — same discipline M9 already established for evaluator-logic tests.
- **Deliberately not built**: any change to `MockProvider` to make it capable of repeats/multiple calls or a genuinely bad answer (tempting, but real scope creep — `MockProvider`'s fixed single-hop behavior is depended on by tests across every earlier milestone); trajectory metrics as a Langfuse *Score* on live production traces (like M12's `user_thumbs`) — the spec frames trajectory evaluation as part of the offline evaluation loop, so this stayed scoped to `run_case()`/the evaluation dataset, not `chat.py`'s live request path.

### Cost and Latency Experiments (M14)

The spec's own **Experiment C** ("single-agent vs explicit planning step") — compare at least two agent configurations on quality, p50/p95 latency, input/output tokens, and estimated cost, and discuss the quality × latency × cost trade-off. This deployment's Langfuse "events_only" mode has no public read API at all (see [Langfuse](#langfuse) below), so unlike M10's "let Langfuse's own comparison view show it," there's no way to pull a side-by-side table back out of Langfuse programmatically — this milestone measures the same underlying data (token usage, latency) locally instead, purely in-process, before it's ever sent to Langfuse.

- **`evaluation/cost_latency.py`** — `UsageTrackingProvider` wraps any real `LLMProvider`, recording each call's `LLMResponse.usage` and wall-clock latency as a side effect, without changing what's sent to the model or what Langfuse itself records (the wrapped provider's own `complete()` still opens its own `llm_call` generation span exactly as before). `run_case_with_metrics()` installs it via a scoped monkey-patch of `agent.nodes.get_llm_provider` — the same single import site the project's own tests already patch (`test_trace_design.py`) — restored in a `finally` immediately after each case, not held across a whole run. `MODEL_PRICING` + `estimate_cost_usd()` give an illustrative, approximate per-model USD estimate (`None`, not a fabricated `$0.00`, for `MockProvider`'s `"mock-echo-v1"`, which has no real inference cost at all).
- **The comparison axis: `AGENT_MAX_ITERATIONS=1` (single-step) vs the default `5` (multi-step).** Verified before designing anything: at `max_iterations=1`, `agent_node`'s existing `forced_final` check (Milestone 5) is already true on the very first call, so the agent can never request a tool — one LLM call, always, guaranteed. Needs zero changes to the agent graph itself, just a `Settings` toggle — the same reuse discipline Milestone 8 established for `PROMPT_LABEL`.
- **`evaluation/cost_latency_report.py`** — `ConfigMetrics` (p50/p95 latency, token totals/averages, estimated cost, Layer 1 quality pass rate, and Milestone 13's trajectory-healthy rate — reused, not reinvented, since a single-step config's inability to call a tool is exactly what trajectory health already catches) and `render_cost_latency_comparison()`, which prints a side-by-side table plus an auto-generated quality/latency/token/cost discussion for exactly two configs.
- **`scripts/run_cost_latency_experiment.py`** (`make cost-latency-experiment`) — runs the full 39-case dataset once per config, in one process, via env var override + `get_settings.cache_clear()` between configs. Each case still opens its own real Langfuse trace via `run_case()`, so every trace remains inspectable in Langfuse exactly like any other evaluation run — and, since a same-day follow-up (a user question: "are we even using Langfuse for this, and can I check?"), each one is now also filterable *by which config produced it*: `run_case()` gained additive-only `extra_tags`/`extra_metadata` parameters (both default `None`, every other caller unaffected), and `run_case_with_metrics(case, config_name=...)` passes `["cost-latency-experiment", config_name]`/`{"cost_latency_config": config_name}` through them. Verified live by opening a real trace afterward. `--push-to-langfuse` additionally pushes each config as a named Langfuse Dataset Experiment run, reusing `run_named_experiment()` (M10) unchanged — gives a real `dataset_run_url` per config, natively comparable side by side in Langfuse's UI (verified live: both configs' per-item scores, including M13's trajectory scores, appeared in the same comparison table). Opt-in, not default: it needs `make sync-eval-dataset` first and doesn't carry local metrics (no `UsageTrackingProvider` in that path) — the printed report stays the one authoritative source of the actual numbers. Full account of the original gap and the fix in [docs/EXPERIMENTS.md](EXPERIMENTS.md).
- **Real result, from this environment**: multi-step wins meaningfully on quality (+15.9pp Layer 1 pass rate, +38.5pp trajectory health) at 2.1x p50 latency and 2.42x tokens per case — a genuine Pareto trade-off, entirely reproducible under `LLM_PROVIDER=mock`. Cost reads `n/a` for both — confirmed consistent with Langfuse's own built-in Cost Dashboard, which independently shows `mock-echo-v1` at a flat $0.00 for the same reason (no pricing data for that model name). Full numbers and discussion in [docs/EXPERIMENTS.md](EXPERIMENTS.md).
- **Deliberately not built**: a live "small model vs larger model" comparison (Experiment B) — needs `LLM_PROVIDER=anthropic`, not exercised here (no `ANTHROPIC_API_KEY`, the recurring gap); the pricing/wrapper machinery is ready for it (swap `CONFIGS` to two `LLM_MODEL` values, no code change). Experiments D/E (tool description versions, temperature) remain unbuilt — out of this milestone's scope, and E specifically would need `AnthropicProvider` to send `temperature` at all, which it currently doesn't (no such SDK parameter — M2's own finding). A generic experiment-config CLI — the spec asks for "at least two" configurations, not a framework; `CONFIGS` is a small, explicit, easily-edited list.

### Failure and Resilience Laboratory (M15)

Controllable fault injection for the spec's named failure modes — LLM timeout, LLM provider unavailable, malformed model output, tool exception, tool timeout, no search results, Langfuse unavailable — verifying each is visible in Langfuse trace data and that the application degrades gracefully rather than crashing. Full runbook: [docs/DEBUGGING_WORKFLOWS.md](DEBUGGING_WORKFLOWS.md).

- **A real bug found before any fault-injection code was written**: reading Langfuse's own `start_as_current_observation` source (not assuming) showed it's a bare `try/finally`, no `except` — it never marks a span `level="ERROR"` just because an exception propagated through it. `AnthropicProvider.complete()`'s `generation.update(...)` call sat *after* the real API call, so a real timeout left the `llm_call` generation span completely unmarked — only the root trace (`chat.py`'s M6-era `try/except`) explained anything. Fixed in both `AnthropicProvider` and `MockProvider`: the completion call is now wrapped in `try/except`, marking the generation `ERROR` before re-raising — the same pattern `tools_node` already used for tool failures since M6, previously missing at the LLM-call layer.
- **`faults.py`** — `FaultInjectingProvider` (LLM-layer: `llm_timeout`, `llm_provider_unavailable` open their own `llm_call` generation span, mark it `ERROR`, and raise before reaching the wrapped provider; `llm_malformed_output` calls the real wrapped provider, then strips a required argument from whatever tool call comes back) and `make_failing_tool()` (tool-layer: returns a function matching a real tool's calling convention that raises immediately). Explicit, scoped wrappers only — deliberately no global `FAULT_INJECTION` setting, which would be exactly the kind of switch that gets left on by accident in a real deployment. Swapped in the same scoped, restored-in-`finally` way M14's `UsageTrackingProvider` already established.
- **Tool-layer and LLM-layer faults behave, and are documented, differently.** A tool failure gets a real second chance — `tools_node` (M6) turns it into a "tool" result message, and the agent's next LLM call produces a coherent answer: **HTTP 200**. An LLM call failing outright has no equivalent recovery — **HTTP 500**, a clean failure (no hang, no crash, no effect on other requests) but not a *recovered* one. No LLM-call retry logic was added; see "Deliberately not built" below.
- **`scripts/fault_injection_lab.py`** (`make fault-injection-lab`) — runs one message through the real agent graph under each fault, no server needed (same pattern as `smoke_test_agent.py`), printing what happened and a real Langfuse trace URL per fault. Real result from this environment: every tool-layer fault recovered to HTTP 200 with a coherent answer; both LLM-layer faults produced a clean HTTP 500; "no results" and "Langfuse unavailable" needed no fault injection at all — both were already the system's normal behavior. Full output in [docs/EXPERIMENTS.md](EXPERIMENTS.md).
- **"No search results"**: demonstrated by calling `search_hotels` directly with a nonexistent destination, not through the mocked agent loop — `MockProvider`'s trigger table always uses a fixed, real `destination_id`, so it can't be steered into a genuinely empty result through a chat message. `output.result_count: 0`, no error level — empty is a valid answer, not a failure (unchanged since M4; M9's evaluators already `skip` rather than fail on this).
- **"Langfuse unavailable"**: the single most emphasized resilience claim in the spec, now given a real, non-negotiable proof rather than only ADR-004's own reasoning. `tests/integration/test_langfuse_unavailable.py` points `LANGFUSE_HOST` at an unreachable local port (`localhost:1` — fast `ECONNREFUSED`, no slow DNS lookup) and confirms `/chat` still returns 200 in under 2 seconds, non-debug mode. Ran live: 1.61s total, response returned before the SDK's own background retry/backoff log lines even appeared.
- **Deliberately not built**: LLM-call retry/backoff logic — real scope creep on the one code path every milestone depends on, and not something the spec's own resilience examples ask for; a real second "travel provider" to fail over *from* — this project has only ever had the local synthetic data source, that fallback has nowhere to point until Milestone 18 (optional); a generic tool execution-timeout wrapper — no real blocking I/O exists yet to time out on; a global fault-injection toggle — rejected as a production footgun.

### Observability-Driven Debugging (M16)

A real, deliberately-injected agent regression, diagnosed from a Langfuse trace (not from reading code), fixed, and measured — see [docs/EXPERIMENTS.md](EXPERIMENTS.md) for the full before/after numbers and [docs/RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-16--observability-driven-debugging-exercise) for the design reasoning.

- **Where the bug had to live**: the spec's own examples (poor tool description, an over-eager prompt, hallucination from context) are all failures of an LLM's reasoning. With no `ANTHROPIC_API_KEY` available in this environment, the only reasoning mechanism this project can exercise fully offline and reproducibly (generate traces, `make evaluate`) is `MockProvider`'s keyword-trigger table (`providers/llm/mock.py`) — explicitly documented since Milestone 1 as a test double for reasoning, not an attempt at one. The bug was injected there: a new trigger keyword (`"trip"`), added to fix one failing eval case, that silently fired on an unrelated case needing a clarifying question instead.
- **Diagnosis was trace-first, and the aggregate pass-count actively misled**: after the bug, `make evaluate`'s overall pass count moved *up* (82 → 83), because the bad trigger fixed one case while breaking another. The regression was only visible via per-case diffing and Milestone 13's trajectory metrics (`average_tool_precision` 0.900 → 0.864), and via reading the actual Langfuse trace: the `llm_call` generation showed a tool call the system prompt's own text said shouldn't happen — no `level=ERROR` anywhere, since nothing raised.
- **The fix addressed the underlying cause**: both `"destination"` and `"trip"` now require an actual detected interest tag (from the same vocabulary `TOOL_SPECS` already documents) before firing at all, and pass the *detected* tags instead of a hardcoded `["beach"]`. Re-running the full 39-case suite against the true original baseline (not just the buggy intermediate state) confirmed the regression was fully undone and two more pre-existing failures resolved as an honest side effect.
- **Deliberately not built**: a live demonstration of the same bug class against `AnthropicProvider` — needs `ANTHROPIC_API_KEY`, unavailable here, the same gap as every real-provider comparison since M2; a permanent regression-testing harness — that's explicitly Milestone 17's job.

### Regression Detection (M17)

`make eval-ci` gates on a committed baseline instead of only checking for crashed cases — see [docs/RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-17--regression-detection) for the design reasoning and [docs/EXPERIMENTS.md](EXPERIMENTS.md) for the live pass/fail demonstration.

- **`evaluation/regression.py`** — `Baseline` (a small Pydantic snapshot: `quality_pass_rate`, `trajectory_healthy_rate`, provider, case count, timestamp), `check_regression(baseline, current metrics, thresholds) -> RegressionCheckResult` (pure logic, no I/O), `load_baseline()`/`save_baseline()`, `render_regression_report()`.
- **Two metrics, gated independently, not one blended score** — `quality_pass_rate` (Layer 1) and `trajectory_healthy_rate` (Milestone 13), the exact pairing Milestone 14 already computes for cross-config comparison (`ConfigMetrics`), now shared via `trajectory_report.py`'s `compute_quality_metrics()` rather than duplicated a third time. Two thresholds because Milestone 16's own regression moved these two metrics in *opposite* directions — a single combined score could have hidden it.
- **A baseline (`data/evaluation/baseline.json`) is a deliberate, committed file** — written only by `make eval-baseline`, never automatically, and never gitignored (unlike `data/evaluation/results/`), the same "a human decides this is the new normal" reasoning `make seed-prompts` (M8) already established. No baseline yet reports `no_baseline`, not a failure — a fresh checkout must not fail CI before a baseline has ever been recorded.
- **Verified live**: baseline recorded from the current code, `make eval-ci` exits `0`. The exact same gate, run against Milestone 14's own already-measured "known weaker version" (`AGENT_MAX_ITERATIONS=1`, one env var, no code change), exits `1` with both metrics reported past threshold.
- **Deliberately not built**: per-case regression tracking (the gate is dataset-wide, matching the spec's own framing); a CI-platform workflow file (the spec asks to demonstrate the exit-code mechanism, which any CI runner can already gate on — this repo has no existing CI config to extend).

### Langfuse

The observability backend. Receives structured trace data from the application. Provides the UI for trace inspection, prompt management, dataset management, evaluation, and experiments.

## Trace Structure

One API request → one top-level Langfuse trace. Every trace carries, since
Milestone 6, `session_id`/`user_id`/`environment` (from M2), plus `tags`,
`metadata`, and — on the agent path — an independent `agent_version`; see
[docs/TRACE_DESIGN.md](TRACE_DESIGN.md) for the full taxonomy and the
error-metadata design (`level`/`status_message`) this milestone also added.
Since Milestone 7, `metadata.history_turns` also records how many prior
turns were replayed into this specific trace's context — the direct,
per-trace answer to "did context size grow excessively," without needing a
custom cost/token dashboard (Langfuse's own per-session aggregation already
covers that; see [TRACE_DESIGN.md](TRACE_DESIGN.md)). Since Milestone 8,
every trace also carries `metadata.prompt_version`/`metadata.prompt_fallback`,
and — when a real (non-fallback) prompt was used — the turn's generation(s)
are linked to that exact prompt version via `propagate_attributes(prompt=...)`.

**What `POST /chat` produces today when no tool is needed** (`agent_enabled=True`, the default — same shape whether the model answers directly or is asked something it doesn't need a tool for):

```
travel_concierge_turn  (trace — session_id, user_id, environment, tags, metadata, agent_version, prompt link via propagate_attributes)
└─ agent                (agent observation, iteration 0)
   └─ llm_call          (generation: model, tokens, latency — linked to the prompt version, unless it was a fallback)
```

**What it produces when the model requests a tool** — verified live via `POST /chat` with `"find me a hotel"`, exactly this shape in the Langfuse UI, not just asserted in tests:

```
travel_concierge_turn        (trace)
├─ agent                     (agent, iteration 0 — requests a tool)
│  └─ llm_call               (generation)
├─ execute_tools             (span — groups every tool call from this turn)
│  └─ search_hotels          (tool: input params, result count)
└─ agent                     (agent, iteration 1 — final answer)
   └─ llm_call               (generation)
```

The loop continues (another `execute_tools` + `agent` pair) if the model requests another tool from the result, up to `Settings.agent_max_iterations` (default 5) — see [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-5--explicit-agentic-ai-workflow) for what happens at that limit.

**With `AGENT_ENABLED=false`** — the Milestone 2 shape, kept as a live comparison point rather than removed:

```
travel_concierge_turn  (trace)
└─ llm_call             (generation — no `agent` span, no tools offered at all)
```

`scripts/smoke_test_agent.py` (`make agent-smoke-test`) produces both of the first two shapes in one run, for exactly this comparison, without needing to restart the server with a different `AGENT_ENABLED` value.

A standalone tool call (`make tools-smoke-test`, or a test calling `search_hotels(...)` directly) still produces its own single-node root trace, unnested — the same code the agent's `tools` node calls, just with no parent trace active. Confirmed unchanged since Milestone 4.

**If a tool call fails** (unknown tool name, or missing/malformed arguments — both realistic outcomes of an LLM hallucinating a call), `execute_tools` gets `level="ERROR"` and a `status_message` naming which call(s) failed, in addition to the graceful text-based recovery the agent already had (see [TRACE_DESIGN.md](TRACE_DESIGN.md#3-error-metadata)) — the agent's *next* LLM call still produces a real answer, HTTP 200. **If the LLM call itself fails** (a real timeout, a connection failure), the `llm_call` generation span gets the same `level="ERROR"` treatment (Milestone 15 — previously this specific span was left unmarked; see [DEBUGGING_WORKFLOWS.md](DEBUGGING_WORKFLOWS.md)) — there's no equivalent recovery here, since the LLM is what makes the next decision. **If anything else raises during a turn**, `travel_concierge_turn` itself gets the same `level="ERROR"` treatment before the exception is re-raised — the HTTP response is a 500 in both of the last two cases, but the trace now says why at the layer that actually failed, not only at the root.

## Configuration

All behaviour is controlled by environment variables via Pydantic Settings.  
See `.env.example` for the full list.

Two Langfuse modes:
- **Local** (default): `LANGFUSE_HOST=http://localhost:${LANGFUSE_WEB_PORT:-3000}` — started via `make langfuse-up`. Full deployment reference: [docs/langfuse.md](langfuse.md).
- **Cloud**: `LANGFUSE_HOST=https://cloud.langfuse.com` — requires Cloud credentials

`src/travel_ai_concierge/observability/langfuse_client.py` builds the Langfuse client explicitly from `Settings` (`get_langfuse_client()`), rather than relying on the SDK's own env-var auto-discovery — see [ADR-004](decisions/ADR-004-langfuse-deployment.md) and [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-1--local-langfuse) for why.

LLM provider selection (`LLM_PROVIDER=mock|anthropic`) is likewise a `Settings`-driven, one-line config change — see [ADR-003](decisions/ADR-003-llm-provider-abstraction.md) and [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-2--minimal-concierge-with-tracing).

The UI reaches the API via `Settings.api_base_url` (`API_BASE_URL` in `.env`) — a separate value from `api_host`/`api_port`, which describe where the server binds, not where a client should connect. See [ADR-002](decisions/ADR-002-ui-technology.md) and [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-3--chat-ui).

The synthetic travel dataset (`data/synthetic/*.json`) is not `Settings`-configurable — its path is resolved relative to the `tools/data.py` module's own location, since it's a fixed part of this repository rather than an environment-specific value. Regenerate it with `make generate-data` after editing `scripts/generate_data.py`.

`Settings.agent_enabled` (default `True`) and `Settings.agent_max_iterations` (default `5`) control the Milestone 5 agent graph — see [RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-5--explicit-agentic-ai-workflow) for why this is a flag rather than two permanent code paths. `agent_max_iterations` doubles as Milestone 14's own comparison axis (`1` forces a single LLM call, no tool ever offered, vs the default `5`) — see "Cost and Latency Experiments" above.

`Settings.agent_version` (default `"1.0.0"`) is Milestone 6's addition — bump it when the agent's own graph/node logic changes materially, independent of `Settings.app_version`. See [docs/TRACE_DESIGN.md](TRACE_DESIGN.md) for the full taxonomy this milestone introduced (tags, metadata, error levels).

`Settings.max_history_turns` (default `10`) bounds how many prior turns Milestone 7's conversation store replays into context per `/chat` call — the oldest turns are trimmed first once a session exceeds this. This is app-level state, in-memory and per-process (not backed by Redis/Postgres) — see "Conversation Memory" above for why that's a deliberate choice for this project rather than a shortcut.

`Settings.prompt_label` (default `"production"`) and `Settings.prompt_cache_ttl_seconds` (default `60`) control Milestone 8's Prompt Management fetch — see [Prompt Management](#prompt-management-m8) above and `docs/RATIONALE_PER_MILESTONE.md` for why `prompt_label`, not a second hardcoded prompt string, is the v1-vs-v2 comparison mechanism.

`Settings.judge_provider` (default `"fake"`) and `Settings.judge_model` (default `"mock"`, only used when `judge_provider="anthropic"`) control Milestone 11's LLM-as-judge — kept a separate setting from `llm_model` on purpose, so the judge can run a different model/tier than the primary application model. See "LLM-as-Judge" above.

## Milestone Status

| Milestone | Description                         | Status      |
|-----------|-------------------------------------|-------------|
| M0        | Scaffolding, config, health API      | ✅ Complete |
| M1        | Local Langfuse deployment            | ✅ Complete |
| M2        | Minimal concierge (LLM + tracing)   | ✅ Complete |
| M3        | Chat UI                              | ✅ Complete |
| M4        | Synthetic travel tools               | ✅ Complete |
| M5        | LangGraph agent workflow             | ✅ Complete |
| M6        | Production-like trace design         | ✅ Complete |
| M7        | Sessions and multi-turn analysis     | ✅ Complete |
| M8        | Prompt management                    | ✅ Complete |
| M9        | Evaluation framework                 | ✅ Complete |
| M10       | Langfuse datasets and experiments    | ✅ Complete |
| M11       | LLM-as-judge                         | ✅ Complete |
| M12       | Human feedback                       | ✅ Complete |
| M13       | Agent trajectory evaluation          | ✅ Complete |
| M14       | Cost and latency experiments         | ✅ Complete |
| M15       | Failure and resilience laboratory    | ✅ Complete |
| M16       | Observability-driven debugging exercise | ✅ Complete |
| M17       | Regression detection                 | ✅ Complete |
| M18       | Optional Travel AI Search integration | ⬜ Next  |
| …         | See PROJECT_SPEC.md for full list    |             |

## Architecture Decision Records

| ADR | Decision |
|-----|----------|
| [ADR-001](decisions/ADR-001-agent-framework.md) | LangGraph for agent orchestration |
| [ADR-002](decisions/ADR-002-ui-technology.md) | Streamlit for chat UI |
| [ADR-003](decisions/ADR-003-llm-provider-abstraction.md) | Protocol-based LLM provider abstraction |
| [ADR-004](decisions/ADR-004-langfuse-deployment.md) | Self-hosted Langfuse as default, Cloud as optional |
| [ADR-005](decisions/ADR-005-headless-initialization.md) | Headless-initialize local Langfuse (org/project/keys) rather than manual signup |
