# Final Project Questions — Answered

> The project spec closes with: *"By completing this project I should be able to answer"* — 28 questions. This document answers each one directly, pointing at the real file, doc section, or command that backs the answer, rather than re-explaining what those already cover. Where this project has a genuine, unsolved limitation instead of a clean answer, that's stated plainly — several of these questions don't have a fully satisfying answer *anywhere* in production LLM engineering yet, and pretending otherwise would be the least useful thing this document could do.
>
> Each answer names the milestone(s) involved — see [docs/RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md) for the full reasoning behind any of them, and [docs/EXPERIMENTS.md](EXPERIMENTS.md) for the real, captured evidence.

---

### 1. What exactly is an LLM trace?

One complete unit of work this application did in response to something — in practice, one `/chat` request. Concretely, it's `travel_concierge_turn`: a root OTel span (Langfuse's SDK v4 is OTel-based) that every other observation for that request nests underneath, carrying `session_id`/`user_id`/`environment`/`tags`/`metadata` set once via `propagate_attributes(...)` (Milestone 6). See [docs/TRACE_DESIGN.md](TRACE_DESIGN.md) and `src/travel_ai_concierge/api/routes/chat.py`.

### 2. What is the difference between a trace, span and generation?

A **trace** is the whole request (see Q1). A **span** is any nested step inside it with no more specific type — this project's `execute_tools` grouping step (Milestone 6) is a plain span. A **generation** is Langfuse's specific type for one real LLM call — `llm_call`, opened inside `MockProvider`/`AnthropicProvider` (Milestones 2/5), the only place that records model name, prompt/completion, and token usage. Langfuse also has `agent` and `tool` as their own first-class types (confirmed via SDK introspection, not assumed — Milestones 1/4/5): `agent` for one LLM-with-tools reasoning step, `tool` for one tool execution. See [docs/TRACE_DESIGN.md](TRACE_DESIGN.md)'s naming table for the complete list.

### 3. How should an Agentic AI trajectory be instrumented?

Every reasoning step and every tool call gets its own typed observation, nested under one trace, not flattened into a single log line: `agent` (`as_type="agent"`) for each LLM decision, `execute_tools` wrapping the tool calls that decision requested, each tool's own `as_type="tool"` observation nested inside that. This shape — `agent → execute_tools → tool → agent → ...` looping until a final answer — is `src/travel_ai_concierge/agent/nodes.py` (Milestone 5), and it's what makes trajectory-level evaluation (Q20) possible after the fact: the trace *is* the trajectory, not a separate record of it.

### 4. How are sessions represented?

A `session_id` (client-supplied or server-generated) is attached to every trace in that conversation via `propagate_attributes(session_id=...)` (Milestone 2) — Langfuse groups traces by it natively, visible under **Sessions** in the UI. Separately, `ConversationStore` (Milestone 7, `src/travel_ai_concierge/conversation/store.py`) replays prior turns from the same `session_id` into the LLM's context on each new request — real short-term memory, not just a UI grouping label. It's in-process and per-process by design (see Q28's "Scaling" pointer for why that's a real production limitation, not an oversight).

### 5. How can user interactions be correlated?

Four separate identifiers, each answering a different "correlate by what" question: `session_id` (one conversation, Q4), `user_id` (one person across sessions, Milestone 2, deliberately omitted rather than fabricated when the caller doesn't supply one), `trace_id` (one request, debug-gated — see `ChatResponse.trace_id`), and `message_id` (one turn, always returned regardless of debug mode — Milestone 12, `POST /feedback` resolves it back to the real `trace_id` server-side, so a client never needs to know the raw trace_id just to rate an answer). See `src/travel_ai_concierge/api/schemas/chat.py` and [docs/TRACE_DESIGN.md](TRACE_DESIGN.md).

### 6. How are tool calls monitored?

Each tool call opens its own `as_type="tool"` observation with real input/output (Milestone 4); `execute_tools` (Milestone 6) marks itself `level="ERROR"` with a `status_message` naming which call(s) failed, including the case where a missing required argument fails *before* the tool's own span ever opens. Beyond per-call visibility, Milestone 13's trajectory metrics (`tool_precision`, `tool_recall`, `missing_tools`, `unnecessary_tools`, `repeated_tools`) turn "was this tool call reasonable" into a real, aggregable number across a whole evaluation run. See `src/travel_ai_concierge/agent/nodes.py` and `src/travel_ai_concierge/evaluation/trajectory.py`.

### 7. How do I inspect token usage?

Per-request: every `llm_call` generation records `usage_details` (`input`/`output` token counts) directly in Langfuse — open the trace, click the generation. Cross-run: this deployment's Langfuse "events_only" mode has no public read API (see Q13's dataset note and [docs/langfuse.md](langfuse.md)), so Milestone 14 built `UsageTrackingProvider` (`src/travel_ai_concierge/evaluation/cost_latency.py`) to capture the same `LLMResponse.usage` locally, before anything reaches Langfuse — `make cost-latency-experiment` / `make final-experiment-suite` print per-config token totals and averages.

### 8. How do I inspect LLM cost?

`estimate_cost_usd()` (Milestone 14, `src/travel_ai_concierge/evaluation/cost_latency.py`) turns token counts into an approximate USD figure from a small, explicitly-labeled-illustrative `MODEL_PRICING` table. It returns `None` (not a fabricated `$0.00`) for any unpriced model — including `MockProvider`'s `mock-echo-v1`, confirmed live to match what Langfuse's own built-in Cost Dashboard independently shows for the same model. A real model under `LLM_PROVIDER=anthropic` would populate a real number; unexercised live here (no `ANTHROPIC_API_KEY`).

### 9. How do I locate latency bottlenecks?

Per-request, open the trace tree and compare span durations directly: `llm_call` (model latency) vs. `travel_search_backend` (Milestone 18's own nested span, isolating the search-backend round trip from everything else) vs. `execute_tools`'s total. Across many requests: `make cost-latency-experiment` / `make final-experiment-suite` report p50/p95 latency per configuration (Milestone 14, linear-interpolation percentiles, no new dependency). The two are complementary — the aggregate tells you *that* a config is slow, the per-trace tree tells you *which specific step* is slow for a given request.

### 10. How do I identify failed agent trajectories?

Two different senses of "failed." A **crashed** trajectory shows up as `level="ERROR"` on `execute_tools` (a tool exception or malformed arguments, Milestone 6) or on `travel_concierge_turn` itself (an unhandled exception, also Milestone 6) — filterable directly in Langfuse by `level == ERROR`. A **structurally wrong but non-crashing** trajectory (right final text, wrong tool sequence) needs Milestone 13's `TrajectoryMetrics.is_healthy` and `classify_divergence()` — this is exactly the "good answer, poor trajectory" case Milestone 16 found live in this project's own traces, invisible to error-level filtering entirely since nothing raised.

### 11. How can prompts be versioned?

Langfuse Prompt Management (Milestone 8) — `scripts/seed_prompts.py` creates named, immutable versions and assigns labels (`production`/`staging`) to them; `Settings.prompt_label` selects which one `get_system_prompt()` fetches, with a local fallback (`SYSTEM_PROMPT_FALLBACK`) if Langfuse is unreachable so the app never fails to start over a prompt fetch. Every call to `messages.create(...)` links back to the specific prompt version that produced it, visible in the generation's own metadata.

### 12. How do I compare two prompts empirically?

`make experiment-prompt-v1` / `make experiment-prompt-v2` (Milestone 10) run the same 39-case dataset under each `PROMPT_LABEL`, publishing each as a named Langfuse Dataset Experiment run — open both `dataset_run_url`s and select one as a comparison baseline in Langfuse's own UI for a native side-by-side view, scores included. **A real, verified caveat**: under the default `MockProvider`, prompt *content* is structurally invisible to the model's own decision logic (`_decide()` only reads the last user message) — Milestone 21's final suite confirmed this live, two prompt-version configs scoring identically to two decimal places on every metric. A meaningful prompt-quality comparison needs `LLM_PROVIDER=anthropic`.

### 13. What is a Langfuse dataset?

A named, versioned collection of test cases stored in Langfuse itself (distinct from this project's own `data/evaluation/cases.json`, which stays the source of truth) — `sync_dataset()` (Milestone 10, `src/travel_ai_concierge/evaluation/langfuse_sync.py`) publishes the 39 local cases to it, upserted by each case's own `id` so re-running after an edit is safe. `make sync-eval-dataset` runs it.

### 14. What is a Langfuse experiment?

One named run of a dataset (Q13) through a task function, with evaluator functions scoring each result — the SDK's own `run_experiment()` API. `run_named_experiment()` (Milestone 10, `src/travel_ai_concierge/evaluation/experiment.py`) adapts this project's own `run_case()`/`EVALUATORS`/trajectory metrics/judge to that shape, so there is exactly one place agent-invocation and scoring logic lives — the local report (Q15) and the Langfuse-native experiment view are two lenses on the same underlying run, not two separate pipelines.

### 15. How do I perform offline evaluation?

`make evaluate` (Milestone 9) — runs all 39 cases through the real agent graph, scores each with five deterministic Layer 1 evaluators (`src/travel_ai_concierge/evaluation/evaluators.py`), and prints/saves both a human-readable and machine-readable report. `make eval-ci` (Milestone 17) does the same but turns the result into a pass/fail exit code — see Q23.

### 16. How do I use LLM-as-judge?

`make evaluate-judged` (Milestone 11) — scores every case on relevance/helpfulness/groundedness/constraint-satisfaction (and itinerary-coherence, where applicable) on a 1-5 scale. `Settings.judge_provider` selects `FakeJudgeProvider` (default, free, deterministic — derives its scores from Layer 1's own outcomes) or `AnthropicJudgeProvider` (real, one call per case, `as_type="evaluator"` observation). See `src/travel_ai_concierge/evaluation/judge.py`.

### 17. What are its methodological weaknesses?

Documented explicitly in `judge.py`'s own module docstring, not glossed over: **not an independent model family** (this project has one real LLM vendor; `AnthropicJudgeProvider` judging Anthropic's own output family is a real, unaddressed self-preference risk, only partially mitigated by `judge_model` being independently configurable from `llm_model`); **self-preference/verbosity bias** (LLM judges are documented in the literature to rate longer, more effusive answers higher regardless of actual quality — not controlled for here); **stochasticity** (no `temperature` parameter exists on the installed Anthropic SDK at all — there's no way to force determinism); **judged without this project's own ground truth** (deliberately — showing the judge `expected_tools`/`expected_arguments` would make it check our own test fixtures instead of reading the conversation independently, which is Layer 1's job). A concrete example of the first weakness in practice: Milestone 21 found that under the default `FakeJudgeProvider`, the "judge: groundedness" score is *mechanically derived from* the same Layer 1 evaluator this report also shows separately — not an independent second opinion, just the same signal restated, until `JUDGE_PROVIDER=anthropic` is actually configured.

### 18. How can user feedback become evaluation data?

`POST /feedback` (Milestone 12) sends a real `user_thumbs` Langfuse score attached to the specific trace, resolved server-side from an opaque `message_id` the client never has to translate into a raw `trace_id`. This is *live-traffic* evaluation data, not offline dataset data — a genuinely different source from Q15/Q16, and Milestone 21's final suite reports it as `n/a` for exactly that reason: no human has ever rated any of the 39 synthetic offline cases, and reporting a fabricated number would be worse than reporting none. See `src/travel_ai_concierge/api/routes/feedback.py`.

### 19. How do I evaluate tool selection?

Layer 1's `evaluate_tool_usage`/`evaluate_tool_arguments` (Milestone 9) check the exact tool(s) called and whether arguments satisfy the case's stated constraints — pass/fail/skip. Milestone 13 adds precision/recall over the *set* of tools called (so a correct-but-repeated call doesn't itself hurt either score — `repeated_tools` catches that separately). See Q6 for the trace-level view of the same question.

### 20. How do I evaluate agent trajectories?

`src/travel_ai_concierge/evaluation/trajectory.py` (Milestone 13): `total_tool_calls`, missing/unnecessary/repeated tool calls, precision/recall, `agent_steps`, and clarification correctness in both directions (asked when it shouldn't have, or didn't ask when it should have). `trajectory_report.py`'s `classify_divergence()` then compares this against final-answer quality to name the interesting cases explicitly — `good_answer_poor_trajectory` and `poor_answer_good_trajectory` — the spec's own "good answer ≠ good trajectory" framing, made concrete.

### 21. How can I detect hallucination?

Two proxies exist, neither a real semantic hallucination detector, and that gap is stated honestly rather than papered over. Layer 1's `response_references_tool_result` (Milestone 9) is a **groundedness proxy**: a literal substring check for whether the final answer mentions something a tool actually returned — cheap, deterministic, and blind to a confidently-stated wrong fact that happens to reuse real vocabulary. The LLM judge's `groundedness` dimension (Milestone 11) is a more semantic second opinion, with all of Q17's own limitations attached. `evaluators.py`'s own docstring explains why a dedicated "fabricated destination name" check was deliberately *not* built: a legitimately helpful agent might reasonably suggest a real alternative destination when asked about one that doesn't exist, which such a check would incorrectly flag as fabrication.

### 22. How can I detect regressions?

`make eval-ci` (Milestone 17) compares the current run's `quality_pass_rate` and `trajectory_healthy_rate` against a committed baseline (`data/evaluation/baseline.json`, updated only by explicit `make eval-baseline`) and fails if either drops past a configurable threshold (`Settings.regression_max_quality_drop`/`_trajectory_drop`, both env-overridable). Two independent thresholds, not one blended score — Milestone 16 demonstrated live that a real regression can move the two metrics in *opposite* directions, which a single score would hide. See `src/travel_ai_concierge/evaluation/regression.py`.

### 23. How can evaluation become part of CI?

`make eval-ci`'s exit code (0 or 1, Q22) is the whole mechanism — any CI runner (GitHub Actions, GitLab CI, anything that gates a pipeline on a process exit code) can call it directly. No `.github/workflows/` file was built for this project specifically, deliberately — there's no existing CI configuration here to extend, and the spec asks to "demonstrate how evaluation *could become* part of CI," which the exit code already does without committing to a specific CI platform this educational project has no other reason to depend on.

### 24. How do I compare quality, latency and cost?

`make cost-latency-experiment` (Milestone 14) compares exactly two agent configurations across all three; `make final-experiment-suite` (Milestone 21) generalizes this to an N-config matrix and adds the remaining dimensions the project spec's own "Report" list names — deterministic score, judge score, human feedback, tool accuracy, groundedness — closing with an auto-generated "which configuration should we deploy, and why" recommendation. See `src/travel_ai_concierge/evaluation/cost_latency_report.py` and `final_suite.py`.

### 25. What happens if Langfuse becomes unavailable?

The application keeps serving — observability was designed from Milestone 1 as not a hard runtime dependency (ADR-004), and Milestone 15 gave that design intent a real, non-negotiable test rather than leaving it as an assertion: `tests/integration/test_langfuse_unavailable.py` points `LANGFUSE_HOST` at a real unreachable host and confirms `/chat` still returns 200 in under 2 seconds (measured live: 1.61s, the response returned before the SDK's own background retry/backoff even logged anything). This works because trace export batches asynchronously on a background thread (Q27's "asynchronous ingestion") — it was never in the request's own critical path to begin with.

### 26. What data should I avoid sending to an observability platform?

Answered honestly as a real, currently-unaddressed gap in this project, not a solved problem: every `/chat` request's raw `message` flows into the trace's `input` verbatim, unredacted, since Milestone 2 — low-stakes today because the actual traffic is synthetic travel queries, but a real deployment would carry real names, dates, and destinations completely unmodified. Langfuse's SDK has a real `mask` callback (`Langfuse(mask=...)`, verified via introspection) as the natural hook for this — not wired up anywhere in this project. See [docs/PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md#pii) (Milestone 20) for the full discussion, including data retention.

### 27. What belongs in Langfuse versus Prometheus/APM/logging?

Langfuse answers "was this generation/tool-call/conversation *good*" — LLM-semantic quality. Prometheus/an APM answers "is the *service* up, fast, and within capacity" — infra-level golden signals (request rate, error rate, latency, saturation) this project doesn't emit today (no `/metrics` endpoint exists). Logs are the connective tissue *between* the two, in principle — and a genuinely concrete, verified gap was found while writing [docs/PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md) (Milestone 20): `structlog`'s `merge_contextvars` processor is already wired into the logging pipeline, but nothing in the codebase ever calls `bind_contextvars(trace_id=...)`, so a log line and the Langfuse trace for the same request can't actually be correlated yet — the mechanism is half-built, not missing outright.

### 28. How would this architecture change at production scale?

The full answer is [docs/PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md) (Milestone 20) — all twelve topics the spec names, each grounded in a verified fact about this specific codebase rather than generic advice, closing with an explicit launch-blocking priority order. The single most concrete finding: `ConversationStore`'s in-memory `dict` (Milestone 7) is the first thing that breaks *correctness*, not just performance, the moment the API scales to more than one replica — a request landing on a different process has no knowledge of history a prior turn wrote elsewhere. Secrets and authentication (there is currently none on any route) rank above it as launch blockers; multi-region ranks as the last concern that matters, not needed until there's an actual second region to serve.
