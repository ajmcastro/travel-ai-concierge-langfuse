# Production Debugging Workflows

> Added: Milestone 15. A practical runbook for diagnosing the project
> spec's own named failure modes using Langfuse trace data — every claim
> below was checked by actually running `make fault-injection-lab` against
> this codebase, not written from imagination. See
> [docs/RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md#milestone-15--failure-and-resilience-laboratory)
> for the design reasoning, and [docs/EXPERIMENTS.md](EXPERIMENTS.md) for
> the full lab output this doc is built from.

## How to reproduce everything in this doc

```bash
make langfuse-up            # if not already running
make fault-injection-lab    # injects each fault below, prints a real trace URL per fault
```

`fault_injection_lab.py` (`src/travel_ai_concierge/faults.py`) injects each
fault through explicit, scoped wrappers — never a global runtime setting —
the same way `evaluation/cost_latency.py`'s `UsageTrackingProvider`
(Milestone 14) swaps in a provider. Nothing here can accidentally fire in a
real deployment.

## The two failure families

The single most important thing to understand before reading the table
below: **tool-layer faults recover, LLM-layer faults don't.**

- **Tool-layer** (`tool_exception`, `tool_timeout`, `llm_malformed_output`):
  `agent/nodes.py`'s `tools_node` (Milestone 6) catches the failure, turns
  it into an error message the agent sees as a "tool" result, and the
  agent's *second* LLM call still produces a real, coherent answer.
  **HTTP 200.** The user never sees a failure; only the trace does.
- **LLM-layer** (`llm_timeout`, `llm_provider_unavailable`): the LLM *is*
  the thing making decisions — there's no second chance once the call
  itself fails. `chat.py`'s own `try/except` marks the trace and re-raises.
  **HTTP 500.** Clean failure — the process doesn't hang or crash, no other
  request is affected — but not a *recovered* answer. This project does not
  implement LLM-call retry logic (see "Deliberately not built" in
  RATIONALE_PER_MILESTONE.md's Milestone 15 entry for why).

## Fault reference table

| Fault | Spec's name | HTTP result | Where it shows in Langfuse | Self-recovers? |
|---|---|---|---|---|
| `llm_timeout` | LLM timeout | 500 | `llm_call` generation: red **Error** banner, `TimeoutError` message (Milestone 15 fix — see below) | No |
| `llm_provider_unavailable` | LLM provider unavailable | 500 | Same as above, `ConnectionError` message | No |
| `llm_malformed_output` | malformed structured response | 200 | `execute_tools`: `level=ERROR`, `status_message` names the missing argument | Yes |
| `tool_exception` | travel provider error / tool exception | 200 | `execute_tools`: `level=ERROR`, `status_message` names the failed tool | Yes |
| `tool_timeout` | tool timeout | 200 | Same shape as `tool_exception` — see below for why there's no separate timeout mechanism | Yes |
| (no fault — real tool behavior) | no results | 200 | The tool's own span: `output.result_count: 0`, no error level at all | N/A — not a failure |
| (no fault — real network condition) | Langfuse unavailable | 200 | Nothing — that's the point | N/A — the app itself never sees it |

## Walkthroughs

### LLM timeout / LLM provider unavailable

**Symptom**: `/chat` returns a 500. The root trace (`travel_concierge_turn`)
shows `level=ERROR`.

**Where to look**: open the trace, expand `agent` → `llm_call`. Before
Milestone 15, this generation span ended abruptly with no error marking at
all — only the root explained anything went wrong. Reading Langfuse's own
`start_as_current_observation` source confirmed why: it's a bare
`try/finally`, no `except` — the SDK never marks a span `ERROR` on your
behalf just because an exception propagated through it. `AnthropicProvider`
and `MockProvider` now both wrap their own completion call in an explicit
`try/except` that marks the generation before re-raising (same pattern
`tools_node` already used since Milestone 6). Now the generation span
itself shows the red **Error** banner with the real exception message.

**Root cause categories**: a real timeout means the upstream API took
longer than `Settings.llm_timeout_seconds` (default 30s, already wired into
`AsyncAnthropic(timeout=...)` since Milestone 2) — check Anthropic's own
status page, or whether `max_tokens`/prompt size grew unexpectedly (see
Milestone 7's `history_turns` metadata). A connection failure usually means
DNS/network/API-key issues, not a slow model — check `ANTHROPIC_API_KEY`
and outbound connectivity first.

**Recovery**: none automatic. The user needs to retry the request
themselves. This is a deliberate scope boundary, not an oversight — see
RATIONALE_PER_MILESTONE.md.

### Malformed model output (tool call missing arguments)

**Symptom**: `/chat` returns 200, but the answer says something like *"I
couldn't check live availability, but..."* rather than real results.

**Where to look**: `execute_tools` shows `level=ERROR`; its
`status_message` names exactly which tool call failed argument binding
(e.g. `"search_hotels() missing 1 required positional argument:
'destination_id'"`) — Milestone 6's existing missing-argument handling,
which this fault type simply exercises rather than needing anything new.
The *next* `agent`/`llm_call` pair shows the recovery: the model's second
response, now grounded in the error text instead of real data.

**Root cause categories**: usually the model hallucinated a tool call with
wrong or incomplete arguments. If this happens on real traffic (not
injected), check the tool's `input_schema` in `tools/specs.py` — an
under-specified or ambiguous description is a common cause of models
guessing at arguments instead of asking a clarifying question first.

### Travel provider error / tool exception / tool timeout

**Symptom**: same shape as above — 200, a response that acknowledges it
couldn't get live data.

**Where to look**: `execute_tools` shows `level=ERROR`, `status_message`
names the tool and the underlying exception. There is currently only one
real "travel provider" in this project (the local synthetic JSON data) —
the spec's "use local synthetic provider if configured" fallback doesn't
have anywhere to fall back *to* yet; that's Milestone 18's job if/when a
real external provider is added. What already exists is the more general
mechanism: `tools_node`'s catch-all means *any* tool exception, from
whatever source, degrades the same way.

**Why there's no dedicated "tool timeout" mechanism**: today's tools are
synchronous local JSON lookups with no real latency to time out on. Rather
than build generic execution-preemption infrastructure for code that has
nothing slow to preempt, `tool_timeout` is simulated as a tool that detects
and raises its own timeout — the realistic shape a real HTTP client with a
configured timeout would actually take. If a real network-backed tool is
added later, it should raise its own `TimeoutError` the same way; the
downstream handling already works.

### No search results

**Symptom**: nothing visible as a symptom at all — a legitimate, complete
answer that happens to say nothing matched.

**Where to look**: the tool's own span (`search_hotels`, `search_destinations`)
shows `output.result_count: 0`. No `level=ERROR` — empty is a valid answer,
not a failure. Milestone 9's evaluators already treat this correctly
(`response_references_tool_result` `skip`s rather than fails when a tool
legitimately returned nothing to reference).

**Note on reproducing this one**: `MockProvider`'s trigger table always
calls `search_hotels` with a fixed real `destination_id` ("algarve")
regardless of the actual user message — it can't be steered into a
genuinely empty result through the mocked agent loop. `fault_injection_lab.py`
demonstrates this by calling `search_hotels` directly instead (the same
"no parent trace" standalone pattern `tools-smoke-test` already uses since
Milestone 4), not through a chat request.

### Langfuse unavailable

**Symptom**: none, by design. `/chat` returns 200 at normal speed.

**Where to look**: nowhere — there's nothing to find in Langfuse for this
case, because Langfuse never received anything. Verified for real, not
just asserted: `tests/integration/test_langfuse_unavailable.py` points
`LANGFUSE_HOST` at an unreachable local port and confirms `/chat` still
returns 200 in under 2 seconds. The SDK's batch span exporter retries on a
background thread — its `Transient error ... retrying in 0.87s` messages
land in the server's own logs *after* the response was already sent, never
blocking the request.

**Root cause categories** (for when this happens for real, not injected):
`make langfuse-up` not run yet, the container crashed, `LANGFUSE_HOST`
misconfigured, or a network/firewall issue between the app and Langfuse.
Check application logs directly (structured, via `logging_config.py`) since
Langfuse itself is unavailable to check.

## The general workflow (matches the spec's own 12-step list)

For any real production issue:

1. **Start with structured application logs**, not Langfuse — if Langfuse
   itself is down, logs are the only signal (see "Langfuse unavailable"
   above).
2. **Find the trace** — by `session_id` (`GET /sessions/{id}` returns each
   turn's `trace_id`, gated by `Settings.debug`; `message_id` is always
   available and resolves via `POST /feedback`'s same mechanism if a user
   reported the issue) or by filtering Tracing on `level=ERROR`.
3. **Read top-down**: root trace tags/metadata first (M6) — agent version,
   provider, history depth — then walk into `agent` → `llm_call` →
   `execute_tools` → individual tool spans.
4. **Check the error level at each layer**, not just the root — this
   milestone's own fix means a failure is now visible at the *specific*
   layer that failed, not only inferred from the root.
5. **Cross-reference Scores** — a low `user_thumbs` (M12) or a failing
   evaluator run (M9/M13) can point you at a trace worth this whole
   workflow before a user even complains.
