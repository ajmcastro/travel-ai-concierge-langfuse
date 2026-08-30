# Trace Design — Taxonomy and Examples

> Added: Milestone 6. This is the reference for *how* this project names and
> labels observability data — read [architecture.md](architecture.md) first
> for *what* the trace tree looks like structurally.

Every dimension below is a real Langfuse mechanism, not a naming convention
we invented — verified in this milestone by introspecting the installed SDK
(`inspect.signature` on `propagate_attributes`/`start_as_current_observation`,
and the OTel attribute keys in `langfuse._client.attributes`) before writing
any code against it.

## 1. Naming

Every observation name is a short, literal description of what happens at
that step, not of who called it or why — the same convention since M1:

| Name | Type | Set in |
|---|---|---|
| `travel_concierge_turn` | trace (root span) | `api/routes/chat.py` |
| `agent` | `agent` | `agent/nodes.py` |
| `execute_tools` | span | `agent/nodes.py` |
| `search_destinations` / `search_hotels` / `get_destination_information` | `tool` | `tools/travel_tools.py` |
| `llm_call` | `generation` | `providers/llm/*.py` |

Rule: name = the verb/noun describing the step (`execute_tools`,
`search_hotels`), never a description of the *code path* that reached it
(`agent_tool_wrapper_v2`) or a value known only at runtime (`search_hotels_for_algarve`)
— the latter belongs in `input`, not the name, or you fragment one logical
operation into many differently-named observations that Langfuse's UI can no
longer group or aggregate by name.

## 2. The four attribute axes

Set once per request in `api/routes/chat.py`, via `propagate_attributes(...)`
wrapping the whole turn — every child observation inherits them automatically
(this only works forward from where you call it; see the SDK's own
"anti-pattern" example in its docstring for what happens if you propagate
attributes *after* creating some spans).

| Axis | Langfuse mechanism | This project's value | Purpose |
|---|---|---|---|
| **Environment** | `environment=` (first-class attribute) | `Settings.environment` (`development`/`production`) | Separate dev noise from production traffic in every dashboard/filter |
| **Application version** | `release=` (set once, at client construction) | `Settings.app_version` | Which deployable build produced this trace |
| **Agent version** | `version=` (per-trace, via `propagate_attributes`) | `Settings.agent_version`, only on the agent path | Which *agent graph/reasoning logic* produced this trace — independent of the app release, because the agent's decision logic can change without a full app deploy, or vice versa |
| **Tags** | `tags=[...]` | `["agent"\|"direct-llm", f"provider:{llm_provider}"]` | Coarse, filterable segments — "show me every direct-llm trace this week" without opening any of them |
| **Feature flags / metadata** | `metadata={...}` | `{"agent_enabled": ..., "llm_provider": ..., "history_turns": ...}` | Structured, queryable facts about *how* this specific request was handled — the boolean flags and config that changed its behavior. `history_turns` (Milestone 7) is a direct, per-trace answer to "did context size grow excessively" |

Why `version` is separate from `release`: the SDK's own parameter docstring
says it plainly — *"Version identifier for parts of your application that
are independently versioned, e.g. agents."* `release` answers "which build of
the whole app is this," `version` here answers "which revision of the agent's
own reasoning is this" — two different rates of change, two different
questions a production incident might need answered separately.

Why tags *and* metadata, not just one: tags are for the handful of coarse
segments you'd actually filter the trace list by (agent vs. direct, which
provider); metadata is for the same information plus finer detail you'd want
displayed once you're already looking at one trace, without polluting the tag
list with values that don't make good filters (e.g. exact model name — a
better `metadata` value than a `tag`, since it doesn't neatly bucket traffic
the way "agent vs. direct" does).

## 3. Error metadata

Langfuse observations carry a first-class `level` (`DEBUG`/`DEFAULT`/
`WARNING`/`ERROR`) and `status_message`, set explicitly via `.update(...)` —
these are **not** inferred automatically from a Python exception; Langfuse's
own `level` field only changes if application code sets it.

Two places set it in this project:

- `api/routes/chat.py` wraps the whole turn's work in `try/except`: on any
  unhandled exception, the root `travel_concierge_turn` span gets
  `level="ERROR"` and `status_message=str(exc)` before the exception is
  re-raised (the HTTP response is still a 500 — this only makes the *trace*
  say why).
- `agent/nodes.py`'s `tools_node` tracks which tool calls failed (a
  hallucinated tool name, or a call the LLM made with missing/malformed
  arguments) and marks the `execute_tools` span `level="ERROR"` with a
  `status_message` naming which call(s) failed and why.

## 4. Good vs. poor trace design — a real before/after

This isn't a hypothetical. It's what this project's own `execute_tools` span
looked like before this milestone, and a real gap that would have gone
unnoticed without deliberately auditing for it.

**Poor** (Milestones 4–5, before this one):

```python
try:
    result_content = _serialize_tool_result(func(**call.arguments))
except Exception as exc:
    result_content = f"Error executing {call.name}: {exc}"
# ... span.update(output={"executed": len(last_message.tool_calls)})
```

The failure is real and handled gracefully from the *agent's* point of view
— the LLM sees an error string and can recover. But nothing in Langfuse says
this observation represents a failure: no `level`, no `status_message`. Worse,
if the LLM calls a real tool with a missing required argument (e.g.
`search_hotels` without `destination_id`), the exception happens during
Python's own argument binding in `func(**call.arguments)` — *before*
`search_hotels`'s own `with` block, and its `tool`-type observation, ever
opens. That specific failure mode was, until this milestone, invisible in
Langfuse at every level except as an opaque text string inside the next
`llm_call`'s input — you could build a dashboard that filtered by `level ==
ERROR` for weeks and never see it once.

**Good** (this milestone):

```python
failed: list[str] = []
for call in last_message.tool_calls:
    ...
    except Exception as exc:
        result_content = f"Error executing {call.name}: {exc}"
        failed.append(call.name)
    ...
span.update(
    output={"executed": len(last_message.tool_calls), "failed": failed},
    level="ERROR" if failed else None,
    status_message=f"{len(failed)} ... failed: {failed}" if failed else None,
)
```

Same recovery behavior for the agent — the LLM still sees the same error
text and gets a chance to react. The difference is entirely on the
observability side: a trace where any tool call failed is now filterable by
`level == ERROR`, and the `status_message` says which tool and how many,
without opening the trace.

The general lesson, not specific to this codebase: **error handling that's
correct for the *application* (the request still completes, gracefully) can
still be a *tracing* poor practice** if the observation itself doesn't say
anything went wrong. The two are different concerns, and fixing one doesn't
automatically fix the other.

## 5. Verifying this offline

Tests in `tests/unit/test_trace_design.py` assert on the actual exported
OTel span attributes, not just HTTP status codes — a Langfuse client built
with `span_exporter=InMemorySpanExporter()` (no network, no credentials)
still runs the exact same attribute-setting code as production, so the test
can read back `langfuse.trace.tags`, `langfuse.trace.metadata.*`,
`langfuse.version`, and `langfuse.observation.level` directly off the
finished span and know the real SDK call produced what we intended — not
just that our code compiled and ran without raising.
