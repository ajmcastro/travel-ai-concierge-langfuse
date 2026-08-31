# Travel AI Concierge — Langfuse Observability Lab

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-API-009688.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent%20Orchestration-1C3C3C.svg)](https://www.langchain.com/langgraph)
[![Langfuse](https://img.shields.io/badge/Langfuse-Observability-black.svg)](https://langfuse.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-Chat%20UI-FF4B4B.svg)](https://streamlit.io)

Your agent works great in the demo. Then it's in production: a user got a weird recommendation, the OpenAI bill tripled overnight, or one specific conversation is slow and you don't know if it's the LLM, a tool call, or your own code. **How do you actually find out what happened?**

This repo builds a real (if toy) agentic AI application — a travel concierge — and instruments it end-to-end with [Langfuse](https://langfuse.com) to answer exactly that question, milestone by milestone: tracing, sessions, token/cost/latency monitoring, prompt versioning, and offline/online evaluation including LLM-as-judge and regression detection. The travel domain is the vehicle; **AI observability and evaluation engineering is what you're here to learn.**

**Who this is for**: developers who can already build an LLM agent and now want to answer "is it actually working, and how would I know if it broke?" — not a Python or LangChain tutorial.

> **Current milestone:** M13 — Agent trajectory evaluation ([progress table](#milestones))  
> Built and documented one milestone at a time — see [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md) for the reasoning behind each step, not just the result.

---

## What this project teaches

Each item below is built at a specific milestone (see the [Milestones](#milestones) table) — this isn't a feature list, it's a curriculum you can follow in order.

- Agentic AI application architecture (LangGraph)
- Production LLM observability: traces, spans, generations, sessions, users
- Tool-call observability and agent trajectory analysis
- Token usage, latency, and cost monitoring
- Prompt management and versioning
- Offline and online evaluation (deterministic + LLM-as-judge + human feedback)
- Regression detection and evaluation-driven CI
- Production debugging workflows using trace data
- Privacy and security considerations for AI observability

---

## Technology

| Concern | Technology |
|---------|-----------|
| Language | Python 3.12 |
| Package management | [uv](https://docs.astral.sh/uv/) |
| API | FastAPI |
| Agent orchestration | LangGraph ✅ |
| Chat UI | Streamlit ✅ |
| Observability | [Langfuse](https://langfuse.com) |
| LLM provider | Anthropic / Mock (OpenAI planned) |
| Testing | pytest |
| Linting | Ruff |
| Type checking | mypy |
| Infrastructure | Docker Compose |

---

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Docker + Docker Compose (for Langfuse)

---

## Quick start

```bash
# 1. Install dependencies
make install

# 2. Create your local .env (ships with working local-dev Langfuse credentials — no signup needed)
make env

# 3. Start Langfuse (self-hosted, local) — do this before the API below, or every
#    /chat request pays a real ~2.5s penalty retrying against a host that isn't up yet
make langfuse-up

# 4. Start the API
make serve

# 5. Check it's running
make health

# 6. Start the chat UI (in another terminal)
make ui
```

---

## Langfuse — local self-hosted (default)

**Start this before you call `/chat`** — with the `.env.example` default (`DEBUG=true`), every request flushes to Langfuse before responding; if nothing is listening yet, that's a real ~2.5s retry/backoff penalty per request, not an instant failure. See `docs/EXPERIMENTS.md` (Milestone 2) for the measured number.

```bash
# Start the full Langfuse stack: postgres, clickhouse, redis, minio, langfuse-web/worker
make langfuse-up

# Open the UI (port from LANGFUSE_WEB_PORT in your .env, default 3000)
open http://localhost:3000

# Create a real trace and print its URL
make langfuse-smoke-test

# Stop
make langfuse-down
```

Your `.env` (from `.env.example`) provisions an org, project, user, and API key pair automatically on first boot — no manual signup required, and `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are valid immediately. Sign in to the UI with `LANGFUSE_INIT_USER_EMAIL`/`_PASSWORD` from the same file. Full reference, including the manual-signup alternative and what to do if port 3000 is already taken on your machine: [docs/langfuse.md](docs/langfuse.md).

### Optional: Langfuse Cloud

To use [Langfuse Cloud](https://cloud.langfuse.com) instead, change three values in `.env`:

```env
LANGFUSE_PUBLIC_KEY=pk-lf-<your-cloud-key>
LANGFUSE_SECRET_KEY=sk-lf-<your-cloud-key>
LANGFUSE_HOST=https://cloud.langfuse.com
```

No code changes required.

---

## Chat API

```bash
# Talk to it — defaults to the deterministic mock provider, no API key needed
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Plan me a quiet 5-day trip to Portugal"}' | python3 -m json.tool

# Or, with the server already running elsewhere (make serve):
make chat-smoke-test
```

Every request is one Langfuse trace. By default (`AGENT_ENABLED=true`) it runs the Milestone 5 agent: an `agent` step decides whether to answer directly or call a tool; if it calls one, an `execute_tools` step runs it and the agent gets another turn to incorporate the result, looping until it has a final answer (capped by `AGENT_MAX_ITERATIONS`, default 5). Try a message that triggers the mock provider's tool-calling path:

```bash
curl -s -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message": "find me a hotel"}' | python3 -m json.tool
```

Pass the same `session_id` across requests to group them into one conversation *and*, since Milestone 7, give the concierge real memory of it — see [Sessions](#sessions-and-conversation-memory) below. Pass `user_id` to attribute a trace to a real, stable identity (omitted rather than fabricated when you don't have one — see [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md#milestone-2--minimal-concierge-with-tracing)).

Since Milestone 6, every trace also carries `tags` (`agent`/`direct-llm`, `provider:<name>`), structured `metadata` (`agent_enabled`, `llm_provider`), and — on the agent path — its own `agent_version`, independent of `app_version`. If a tool call fails or the turn raises, the relevant observation is marked `level="ERROR"` with a `status_message` instead of the failure being visible only as text. Full taxonomy and a real good-vs-poor example: [docs/TRACE_DESIGN.md](docs/TRACE_DESIGN.md).

Since Milestone 8, the system prompt itself comes from [Langfuse Prompt Management](#prompt-management), not a hardcoded string — see below.

With `DEBUG=true` (the `.env.example` default), the response includes a `trace_id` you can open directly in the Langfuse UI. Switch to the real model:

```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-5
ANTHROPIC_API_KEY=sk-ant-...
```

No code changes, no different endpoint — same `/chat`, same trace shape, real tokens and cost instead of a deterministic echo.

---

## Sessions and Conversation Memory

```bash
make conversation-smoke-test   # a real 3-turn conversation, requires `make serve`
```

Since Milestone 7, the concierge actually remembers a conversation — not just in Langfuse's Sessions view (grouped by `session_id` since Milestone 2), but in what the LLM itself sees. Every `/chat` call replays up to the last `MAX_HISTORY_TURNS` (default 10) exchanges from that `session_id` ahead of the new message, and stores the new exchange afterward — in-process, in-memory, gone on restart (a deliberate choice for an educational system with no other need for a database; see the "Conversation Memory" section of [docs/architecture.md](docs/architecture.md)).

```bash
curl -s http://localhost:8000/sessions/<session_id> | python3 -m json.tool
```

Returns this app's own record of that session's turns (404 if none exist yet) — `trace_id` per turn only in `DEBUG=true`, same convention as `/chat`'s own response. This is a different thing from Langfuse's own Session view, which already aggregates cost/latency/token totals per `session_id` natively — this endpoint answers "what did this session actually say," not "how much did it cost" (see [docs/TRACE_DESIGN.md](docs/TRACE_DESIGN.md)).

---

## Prompt Management

```bash
make seed-prompts        # create/update v1 (production) + v2 (staging) in Langfuse
make prompts-smoke-test  # fetch both, compare — no server needed
```

Since Milestone 8, the system prompt is a named, versioned, labeled prompt in Langfuse Prompt Management (`travel-concierge-system`), not a hardcoded string. `/chat` fetches it by label (`PROMPT_LABEL`, default `production` → v1); flip to `PROMPT_LABEL=staging` to run v2 — a more directive version that requires tool use for destination/hotel facts instead of just encouraging it — with no code change.

**Never a hard dependency**: if Langfuse is unreachable, or you haven't run `make seed-prompts` yet, `/chat` still works — it falls back to the same text as v1, held locally in code (`Settings`-independent, always available). This is directly tested (`tests/unit/test_prompts.py`) against an intentionally-unreachable host, not just asserted.

Every trace records which prompt version answered it (`metadata.prompt_version`, `metadata.prompt_fallback`) and — for a real, non-fallback prompt — links the generation to that exact version in Langfuse's own prompt-usage view. Comparing v1 vs. v2 for actual quality (not just mechanism) needs a real provider and a real evaluation dataset, which is Milestone 9's job, not this one's — see [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md#milestone-8--prompt-management) for why this milestone deliberately stops short of declaring a winner.

---

## Evaluation

```bash
make generate-eval-dataset  # (re)write data/evaluation/cases.json
make evaluate               # run it, print a human-readable + JSON report
make eval-ci                # same, exits 1 only if a case crashed outright
```

Since Milestone 9, a local, deterministic evaluation harness runs 39 hand-authored test cases through the *real* agent graph — deliberately independent of Langfuse datasets at this layer (that's [below](#langfuse-datasets-and-experiments), Milestone 10, a separate optional publishing step). Cases cover all 20 query classes the project spec names — destination/hotel recommendation, family/couples holiday, budget/luxury, beach/city/culture/nightlife/quiet/food-wine, itinerary planning, vague requests, multi-constraint, needs-clarification, one-tool, multi-tool, impossible-constraint, contradictory-preferences — grounded in the real synthetic destinations/hotels, not invented data.

Five deterministic (Layer 1 — no LLM judge here, that's [below](#llm-as-judge), Milestone 11) evaluators check each case: expected tool called, tool arguments satisfy the stated constraints, the response is non-empty, the response actually references what a tool returned (a groundedness *proxy*, not semantic scoring), and — where expected — a clarifying question was asked. Each evaluator can also `skip` a case it doesn't apply to, so out-of-scope checks aren't counted as failures.

**Read the report's own note before judging a low pass rate**: under the default `MockProvider`, most tool-usage and clarification checks fail — not because the agent is broken, but because Mock is a fixed keyword-trigger table with no real reasoning (see [providers/llm/mock.py](src/travel_ai_concierge/providers/llm/mock.py)). The dataset describes what a *real* agent should do; run with `LLM_PROVIDER=anthropic` for a meaningful signal. `make eval-ci`'s `--ci` flag is **not** a regression/baseline gate yet — that's explicitly [Milestone 17](#milestones)'s job.

Each case runs as a real Langfuse trace, tagged `evaluation` plus its query class — inspectable exactly like production traffic, not a hidden side process.

`make evaluate` also prints an agent trajectory report alongside this one, at no extra cost — see [Agent Trajectory Evaluation](#agent-trajectory-evaluation) below.

---

## Langfuse Datasets and Experiments

```bash
make sync-eval-dataset      # publish/update the same 39 cases as a real Langfuse Dataset
make experiment-prompt-v1   # run it — PROMPT_LABEL=production, run_name="prompt-v1"
make experiment-prompt-v2   # run it — PROMPT_LABEL=staging,   run_name="prompt-v2"
```

Since Milestone 10, the exact same dataset from [Evaluation](#evaluation) above can also be published to a real Langfuse Dataset (`travel-concierge-eval-cases`, upserted by case id — safe to re-run after editing `cases.json`) and run as a named, comparable experiment, using the Langfuse SDK's own `run_experiment()` API rather than anything hand-rolled. `make experiment-prompt-v1`/`-v2` is the spec's own "Experiment A" worked example: the same 39 cases, same Layer 1 evaluators, two different `PROMPT_LABEL`s, two `run_name`s on the *same* dataset — open the printed `dataset_run_url` to compare them side by side natively in Langfuse. Since Milestone 13, every run also pushes `trajectory_*` Evaluations (see [Agent Trajectory Evaluation](#agent-trajectory-evaluation) below) unconditionally, alongside Layer 1's own scores.

Quality scores are pushed to Langfuse automatically by the SDK (pass→1.0/fail→0.0/skip→no score, so out-of-scope checks don't drag down the average). Cost and token usage are **not** recomputed here — Langfuse already captures them per generation and shows them in that same comparison view; duplicating that arithmetic locally isn't this milestone's job (see [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md#milestone-10--langfuse-datasets-and-experiments)).

`data/evaluation/cases.json` stays the source of truth throughout — Langfuse is an execution/analysis layer here, not where test cases are authored or edited.

---

## LLM-as-Judge

```bash
make evaluate-judged                        # local report + judge summary (Settings.judge_provider, default "fake")
uv run python scripts/run_experiment.py --run-name my-run --with-judge   # same, pushed to Langfuse
```

Since Milestone 11, cases can also be scored qualitatively — relevance, helpfulness, groundedness, constraint satisfaction, and (for `itinerary_planning` cases) itinerary coherence — dimensions no deterministic check can meaningfully assess. `JudgeProvider` has two implementations: `FakeJudgeProvider` (default, free, offline, deterministic — its scores are directly derived from Milestone 9's own evaluator outcomes, and every rationale says so) and `AnthropicJudgeProvider` (real, one LLM call per case, opt-in via `JUDGE_PROVIDER=anthropic`).

**Not an independent judge**, and said so plainly rather than glossed over: this project has one real LLM vendor, so the real judge is Anthropic judging Anthropic's own output family — not the "independent model family" the spec asks to prefer where possible. `JUDGE_MODEL` is a separate setting from `LLM_MODEL` as a partial mitigation (a different capability tier can judge), not a fix. Self-preference/verbosity bias and stochasticity (Anthropic calls here never set `temperature` — there's no such parameter in the installed SDK) are documented, not controlled for — see [docs/architecture.md](docs/architecture.md)'s "LLM-as-Judge" section for the full list, which the project spec explicitly requires.

A malformed or out-of-range judge response raises rather than silently falling back to a placeholder score — "do not blindly trust LLM-as-judge scores" applies to a broken parse too.

---

## Agent Trajectory Evaluation

```bash
make evaluate   # now also prints + saves a trajectory report, no extra flag needed
```

Final-answer checks alone can't tell you *how* the agent got there — an agent that calls the wrong tool, calls one twice, or skips a needed clarification can still produce text that passes every text-quality check. Since Milestone 13, every evaluation run also computes `tool_precision`/`tool_recall` (over the unique tools called — a correct-but-repeated call doesn't hurt either score, `repeated_tool_calls` catches that separately), missing/unnecessary/repeated tool calls, `agent_steps`, and clarification correctness in *both* directions (Layer 1 only ever checked "clarified when expected"; this adds "did NOT clarify unnecessarily"). Unlike the judge, this costs nothing extra (no LLM call) — it's computed unconditionally on every `make evaluate`/`eval-ci`/`evaluate-judged` run and pushed onto every Langfuse experiment run too, no new flag or Makefile target.

Each case is classified against Layer 1's own text-quality evaluators as `aligned`, **good answer, poor trajectory**, or **poor answer, good trajectory** — the project spec's own two claims, both genuinely demonstrated: re-running the evaluation and reading the failures by hand (before writing any of this) found two already-existing dataset cases (`requires-clarification-002`, `impossible-constraint-001`) where `MockProvider` calls an unnecessary tool yet still produces text that passes every text-quality check — good answer, poor trajectory, live, from the unmodified dataset. The inverse, poor answer despite a *correct* trajectory, cannot occur under Mock (confirmed empirically: its text is always derived directly from whatever it just did, so a correct trajectory and a healthy answer are the same event) — demonstrated instead with one explicitly hand-built fixture in `tests/unit/test_trajectory.py`. Full account in [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) and [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md#milestone-13--agent-trajectory-evaluation).

---

## Chat UI

```bash
make serve    # API, in one terminal
make ui       # Streamlit, in another — opens at http://localhost:8501
```

A real chat interface: multi-turn transcript, a "New conversation" button (fresh `session_id`, cleared history), thumbs up/down under each response (since Milestone 12, wired to a real Langfuse score — see [Human Feedback](#human-feedback) below), and a sidebar debug panel (session/user ID, model, client-measured latency, and a link straight to the trace in Langfuse).

Talks to the API exclusively over HTTP (`API_BASE_URL` in `.env`) — the UI process never imports agent or provider code, so it can be started, stopped, or deployed independently of the API. Since Milestone 7, each request still sends only the latest message, but the API itself now replays conversation history server-side (see [Sessions](#sessions-and-conversation-memory) above) — the transcript displaying full history is no longer just a client-side illusion.

---

## Human Feedback

```bash
make serve   # API
make ui      # thumbs up/down under each response, plus an optional comment
```

A real end user's opinion, sent to Langfuse as a genuine score — `POST /feedback` takes a `message_id` (returned by every `/chat` response, distinct from the debug-gated `trace_id`) and writes `user_thumbs` (1.0/0.0) plus an optional comment, linked to the trace it's rating (Langfuse's ingestion API accepts only one of trace/session/dataset-run per score, so the score itself carries `trace_id`, not both — the trace already carries its own `session_id` from creation, so it's still findable either way directly in Langfuse's own UI: filter traces by `user_thumbs < 1`, or roll up by session — no custom dashboard built for this).

The `message_id`/`trace_id` split exists because `trace_id` is deliberately hidden from the client outside `Settings.debug` (Milestone 2), but feedback needs to work in production too — `message_id` is always returned, and the server resolves it back to the real trace internally. A resubmitted rating for the same message reuses the same deterministic `score_id` rather than creating a duplicate. Full design reasoning in [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md#milestone-12--human-feedback).

**Finding it in Langfuse**: open a trace and click its **Scores** tab (not the default "Preview" tab) — that's where `user_thumbs`, its value, and the comment actually show up; there's also a small `user_thumbs: 1.00`-style hint under the trace name in the tree view. Its **Observation** and **Session** columns are empty by design (the score links `trace_id` only — see above), not a sign anything's missing.

---

## Travel Tools

```bash
make generate-data      # (re)writes data/synthetic/*.json from scripts/generate_data.py
make tools-smoke-test   # calls all three tools directly, prints results + real Langfuse traces
```

Three typed, synchronous functions over a small hand-authored dataset (8 destinations, 18 hotels): `search_destinations`, `search_hotels`, `get_destination_information`. Each call opens a real Langfuse **tool** observation — a distinct type from `span`/`generation`, visible as its own filter facet in the Tracing UI.

Built and tested standalone in Milestone 4 before anything called them from a request — `make tools-smoke-test` still calls them directly with no parent trace, producing their own single-node root traces. Since Milestone 5, the same unchanged code is also called from inside the agent's `execute_tools` step, where it nests under the request's trace instead — see [Agent](#agent) below.

---

## Agent

```bash
make agent-smoke-test   # compares "simple chatbot" vs "tool-using agent" traces, no server needed
```

A hand-written LangGraph graph — two nodes, `agent` and `tools`, looping until the model stops requesting tools. No `langgraph.prebuilt` agent: every node and routing decision is a named Python function you can read directly (`src/travel_ai_concierge/agent/`). `agent` opens a real Langfuse **agent** observation (a distinct type, like `tool` in Milestone 4); `tools` groups every tool call from one turn under one `execute_tools` span.

Two independent safety nets cap the loop at `AGENT_MAX_ITERATIONS` (default 5): the agent withholds tools on what would be the last allowed call (so a well-behaved model still produces a real answer, not an empty one), and routing hard-stops regardless of that, in case a provider ever ignores having no tools offered. Full story, including a real off-by-one bug this went through, in [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md#milestone-5--explicit-agentic-ai-workflow).

Set `AGENT_ENABLED=false` to bypass the graph entirely and restore the Milestone 2 direct-call shape on the same `/chat` endpoint — the exact "simple chatbot vs. tool-using agent" comparison the milestone asks for, without maintaining two endpoints.

---

## Development Commands

```bash
make test              # run all tests (excludes integration by default)
make test-unit         # unit tests only (no infrastructure required)
make test-integration  # requires `make langfuse-up` first
make lint              # ruff check
make format            # ruff format
make typecheck         # mypy
make check             # lint + format-check + typecheck
```

---

## Project structure

```
src/travel_ai_concierge/
├── config/          — Pydantic Settings
├── api/             — FastAPI app, routes (/health, /chat, /sessions/{id}, /feedback ✅ Milestone 12), request/response schemas
├── agent/           — LangGraph agent/tools loop ✅ (Milestone 5): state, nodes, graph
├── providers/llm/   — LLM provider abstraction ✅ (Milestone 2, tool-calling added M5): Mock, Anthropic
├── conversation/    — In-memory per-session conversation store ✅ (Milestone 7), turn lookup by message_id (Milestone 12)
├── prompts.py       — Langfuse Prompt Management fetch + local fallback ✅ (Milestone 8)
├── observability/   — Langfuse client factory ✅ (Milestone 1)
├── domain/          — Destination, Hotel models ✅ (Milestone 4)
├── tools/           — search_destinations, search_hotels, get_destination_information ✅ (Milestone 4, connected via the agent M5)
└── evaluation/      — Dataset loader, evaluators, runner, reporting ✅ (Milestone 9), Langfuse dataset sync + experiments ✅ (Milestone 10), LLM-as-judge ✅ (Milestone 11), trajectory metrics + final-answer comparison ✅ (Milestone 13)

ui/
└── streamlit_app.py — Chat UI ✅ (Milestone 3), talks to the API over HTTP only

data/
├── synthetic/       — 8 destinations, 18 hotels ✅ (Milestone 4), regenerate via `make generate-data`
└── evaluation/      — 39-case dataset ✅ (Milestone 9), regenerate via `make generate-eval-dataset`; results/ is gitignored run output
```

---

## Documentation

| Read this... | ...when you want to |
|---|---|
| [docs/architecture.md](docs/architecture.md) | See the current system diagram, trace structure, and component responsibilities |
| [docs/TRACE_DESIGN.md](docs/TRACE_DESIGN.md) | Understand the naming/tags/metadata/version/error-level taxonomy, and see a real good-vs-poor trace design example |
| [docs/langfuse.md](docs/langfuse.md) | Understand or troubleshoot the self-hosted Langfuse stack — services, ports, credentials |
| [docs/RATIONALE_PER_MILESTONE.md](docs/RATIONALE_PER_MILESTONE.md) | Understand *why* a milestone was built the way it was, not just what it does |
| [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) | See what was actually tried and measured, including surprises and dead ends |
| [docs/decisions/](docs/decisions/) | Read the formal ADRs behind each major technical choice (agent framework, UI, LLM provider, Langfuse deployment) |
| [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) | Read the full, original brief this project is built from — kept verbatim for transparency |

---

## Milestones

| # | Description |
|---|-------------|
| M0 | Scaffolding, config, health API ✅ |
| M1 | Local Langfuse deployment ✅ |
| M2 | Minimal concierge with tracing ✅ |
| M3 | Chat UI ✅ |
| M4 | Synthetic travel tools ✅ |
| M5 | LangGraph agent workflow ✅ |
| M6 | Production-like trace design ✅ |
| M7 | Sessions and multi-turn analysis ✅ |
| M8 | Prompt management ✅ |
| M9 | Evaluation framework ✅ |
| M10 | Langfuse datasets and experiments ✅ |
| M11 | LLM-as-judge ✅ |
| M12 | Human feedback ✅ |
| M13 | Agent trajectory evaluation ✅ |
| M14–M21 | Cost/latency experiments, failure & resilience, debugging exercise, regression detection, optional Travel AI Search integration, Langfuse Cloud, production architecture, final experiment suite… |

---

## Development

This project was designed and implemented by Antonio de Castro, with AI-assisted development using Claude Code (model Sonnet5).

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
