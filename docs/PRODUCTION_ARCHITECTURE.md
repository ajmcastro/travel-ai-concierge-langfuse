# Production Observability Architecture

> Added: Milestone 20. The project spec is explicit about this milestone's
> shape: *"Document how the educational system would evolve in production...
> Do not necessarily implement all of this infrastructure. The goal is
> architectural understanding."* This is that document — no new production
> code ships with it. Every claim about the *current* system below was
> checked against the real code (grep, direct reads), not written from
> memory or assumption, the same discipline every other milestone in this
> project has held itself to.

## Why this matters, stated plainly

This project is a genuinely useful reference for the *shape* of LLM
observability — traces, generations, sessions, evaluation, cost/latency,
regression detection — but it is not a production system, and pretending
otherwise would undersell what "production" actually requires. This
document draws the line explicitly: what's already built here transfers
directly, what's a deliberate educational shortcut, and what a real
production deployment would need to add — for each of the twelve areas the
spec names.

## What's already production-shaped, and what isn't

A scan before writing anything else, so the rest of this document argues
from an accurate baseline rather than a guess:

| Already production-shaped | Deliberate educational shortcut |
|---|---|
| Structured JSON logging (`structlog`, M0) — real, just underused (see [Logs](#logs)) | Only 2 log lines exist in the whole app (`api/app.py`: startup, shutdown) — no request-level logging at all |
| Async, non-blocking trace export (Langfuse's own batching, M1) | Traces are never sampled — every request, 100% |
| Health check endpoint (`GET /health`, M0) | It's a liveness check only — no dependency checks (Langfuse reachability, disk, memory) |
| Provider abstractions swappable via env vars only, zero code changes (LLM, travel search, Langfuse host — ADR-003/004/006) | Conversation memory is a single in-process `dict` (M7) — lost on restart, invisible to any other replica |
| Explicit error-level tracing at every layer (M6, M15) | No authentication or authorization on any route; CORS wide open (`allow_origins=["*"]`) |
| A real regression gate (`make eval-ci`, M17) | The gate runs on-demand against a static 39-case dataset — nothing runs it continuously against live traffic |
| Self-hosted *or* Cloud Langfuse via three env vars, tested (M19) | `.env.example` ships real (if placeholder) secrets for local-dev convenience (ADR-005) — explicitly documented as unsafe beyond localhost |

None of the right-hand column is a bug — every one of those choices is
documented elsewhere in this repo (`docs/RATIONALE_PER_MILESTONE.md`,
ADR-005, `conversation/__init__.py`'s own docstring) as a deliberate,
reasoned trade-off for a single-developer educational project. The point of
this document is to name what changes about that trade-off once "single
developer, localhost" becomes "real users, real infrastructure."

---

## Langfuse

**Today**: the observability backbone since Milestone 1 — self-hosted via
Docker Compose (Postgres + ClickHouse + Redis + MinIO + web/worker,
"events_only" mode) or Cloud, switched by three env vars with zero code
changes, verified end-to-end in Milestone 19.

**In production**:
- **Self-hosted vs. Cloud stops being a coin flip.** For a real deployment,
  Cloud removes the entire HA/backup/upgrade burden for five stateful
  services (see [High availability](#high-availability)) — a genuine
  argument *for* Cloud in production that ADR-004 never needed to make for
  a local dev context, where "no signup required" was the deciding factor
  instead.
- **If self-hosting**: each backing service (Postgres, ClickHouse, Redis,
  MinIO) needs its own production posture — managed/replicated instances,
  automated backups, and the same TLS/network-isolation hardening `docker-compose.yml`
  currently only prepares placeholder secrets for (ADR-005: *"NOT safe to
  reuse for anything reachable from outside your machine"*).
- **Access to trace data needs real IAM.** Traces routinely contain raw
  user input (see [PII](#pii)) — "who can view traces in the Langfuse UI"
  is itself an access-control decision, not just an infra one.
- **Org/project structure** matters at team scale in a way it doesn't for
  one developer — separate Langfuse projects per environment
  (dev/staging/prod), and per-team if the org is large enough that "see
  every trace" isn't an appropriate default.

## API metrics

**Today**: none, distinct from Langfuse. There is no `/metrics` endpoint,
no request-count/latency/status-code histogram, nothing answering "is the
*service* healthy" as opposed to "was this *generation* good." `GET
/health` (M0) is a liveness check — constant-time, no dependency probes —
useful as a load-balancer health-check target, not a readiness or
capacity signal.

**In production**: instrument FastAPI with a Prometheus client
(`prometheus-fastapi-instrumentator` or equivalent) exposing RED metrics
(rate, errors, duration) per route, scraped by Prometheus and visualized in
Grafana. This is a genuinely different question from what Langfuse answers:
Langfuse's `llm_call` latency tells you the model was slow; an API-layer
histogram tells you the *whole request*, including FastAPI/network/queueing
overhead, was slow — the gap between the two is itself diagnostic
information this project currently has no way to see.

## Logs

**Today**: real infrastructure (`structlog`, JSON in production / colored
key=value in a TTY, M0), almost entirely unused — the entire application
emits exactly two log lines, `"starting"` and `"shutdown"`
(`api/app.py`). There is no request-level logging, no error logging beyond
what an unhandled exception's own traceback produces, and — the concrete
gap worth naming specifically — `configure_logging()` already wires
`structlog.contextvars.merge_contextvars` into the processor chain, but
nothing in the codebase ever calls `structlog.contextvars.bind_contextvars(...)`.
The mechanism for correlating a log line with the Langfuse trace it
belongs to (bind `trace_id`/`session_id` once per request, have every
subsequent log line in that request automatically carry it) is already
half-built and simply never finished.

**In production**:
- **Finish the correlation, don't rebuild it.** Bind `trace_id`/`session_id`
  into `structlog`'s contextvars at the top of `chat.py`'s request handler
  (right where the root span already opens) — every log line for that
  request then carries both automatically, and "find every log line for
  this trace" becomes a literal query instead of a manual reconstruction.
- **Add the request-level logging that's currently missing**: one line per
  request (method, path, status, latency), one line per unhandled
  exception with full context — today, an error's only visible trace is
  whatever `level="ERROR"` on the Langfuse span shows; a log aggregator
  with alerting (see [Alerting](#alerting)) needs its own copy.
- **Ship logs somewhere durable** — CloudWatch Logs, Datadog, an ELK/Loki
  stack — `structlog`'s JSON output in non-TTY mode is already shaped for
  this; nothing about the log *format* needs to change, only the
  destination.

## Distributed tracing

**Today**: a single FastAPI process. One request stays inside one process
for its entire lifetime — the "distributed" half of distributed tracing
has never actually been exercised, because there's never been more than
one service. Milestone 18's `TravelAISearchAPIProvider` is the one place
this project talks to a genuinely separate service over the network — and
that call currently carries no trace-context propagation across the wire;
the receiving service (a real Travel AI Search deployment) has no way to
know it's part of the same logical request.

**In production**: once there is more than one real service in the call
path — a real Travel AI Search backend, a separate auth service, anything
— trace context needs to propagate across the network boundary (W3C
`traceparent` header is the standard shape; OpenTelemetry's context
propagators implement it directly). Langfuse's own OTel foundation (see
next section) means this isn't a new mechanism to build so much as a
question of whether `TravelAISearchAPIProvider`'s `httpx2.get(...)` calls
carry the active trace context forward — today they don't, because there's
never been a second Langfuse-instrumented service on the other end to
propagate it to.

## OpenTelemetry

**Today**: Langfuse's SDK v4 *is* OTel underneath — every span this project
creates (`start_as_current_observation`) is a real OTel span, verified
directly (not assumed) as far back as Milestone 6's trace-design tests,
which read attributes straight off `InMemorySpanExporter`'s exported spans
using Langfuse's own OTel attribute keys. This project talks to Langfuse's
own OTel endpoint specifically, not a general OTel Collector.

**In production**: run an OTel Collector as a gateway, and dual-export the
*same* spans to Langfuse (the LLM-semantic view — prompts, completions,
tool calls, evaluation scores) and a general APM (Grafana Tempo, Honeycomb,
Datadog — the infra-correlation view: this span next to the database query
span next to the load balancer's own span). This is the concrete answer to
"do not duplicate instrumentation code," the same principle Milestone 19
already exercised for switching Langfuse targets: one set of
`start_as_current_observation(...)` calls, two destinations, decided by
Collector configuration, not by application code.

## Prometheus/Grafana or cloud APM

**Today**: none. See [API metrics](#api-metrics) above — this is the same
gap from the deployment/dashboard side rather than the instrumentation
side.

**In production**: Prometheus (or a cloud APM — CloudWatch, Datadog,
New Relic) for infra-level golden signals; Grafana (or the APM's own UI)
for dashboards; both genuinely complementary to Langfuse, not competing
with it — Langfuse answers "is the AI good," this layer answers "is the
service up, fast, and within capacity." A production on-call engineer
needs both dashboards open at once for a real incident, not one or the
other.

## Alerting

**Today**: none, in the live-production sense. The closest thing that
exists is Milestone 17's `make eval-ci` — a real regression gate, but a
*pull*, on-demand mechanism (run it, get an exit code) against a static
39-case dataset, not a *push* alert wired to live traffic.

**In production**, at minimum:
- **Infra alerts**: 5xx rate, p95/p99 latency, saturation — driven by the
  [API metrics](#api-metrics) this project doesn't emit yet.
- **Quality-drift alerts**: the genuinely LLM-specific case. `make eval-ci`'s
  two-metric design (`quality_pass_rate`, `trajectory_healthy_rate`,
  Milestone 17) is the right *shape* of check — the production gap is
  running it (or something like it) on a *schedule against sampled live
  traffic*, not just once per CI run against a fixed dataset, and routing a
  threshold breach to Slack/PagerDuty instead of only an exit code.
- **Cost alerts**: a token-spend anomaly (a prompt regression that triples
  average completion length wouldn't show up as an error at all — only as
  a cost graph bending the wrong way). `evaluation/cost_latency.py`'s
  `estimate_cost_usd()` (M14) is local-measurement infrastructure that
  could feed this; nothing today watches it continuously.

## Trace sampling

**Today**: none — every request is traced, unconditionally, with no
sampling configuration anywhere in `Settings`. Reasonable at the request
volume this project actually sees (a single developer, locally); not
reasonable at real production QPS, where 100% trace ingestion becomes a
real cost and storage line item.

**In production**: sampling, but with an asymmetric policy an LLM
application needs and a generic APM sampler doesn't provide by default —
you want *close to 100%* of error/regression traces (the ones actually
useful for debugging, per [Milestone 15](DEBUGGING_WORKFLOWS.md)'s whole
runbook) and a much lower rate of "boring, successful" traces. This is
tail-based sampling (decide whether to keep a trace *after* seeing how it
ended), not head-based (decide before the request even starts) — an OTel
Collector's tail-sampling processor is the standard mechanism, sitting in
front of whichever export destinations [OpenTelemetry](#opentelemetry)
above sends spans to.

## Data retention

**Today**: unbounded, by omission rather than decision — no
`Settings`-level retention policy, no scheduled deletion job; local Docker
volumes and Langfuse Cloud's own default retention are whatever they are.

**In production**: an explicit, decided retention window (e.g. 90 days for
raw traces, longer for aggregated evaluation results), driven by two
separate forces that happen to point the same direction: storage cost, and
the [PII](#pii) question below — you cannot justify indefinite retention of
raw user messages without a specific reason to, and "we never decided
otherwise" is not that reason. Langfuse Cloud plans expose retention
settings directly; a self-hosted deployment would need a scheduled job
against ClickHouse/Postgres directly.

## PII

**Today**: unaddressed, and worth stating exactly how. Every `/chat`
request's raw `message` field flows into the trace's `input` verbatim
(`chat.py`, unchanged since Milestone 2) — no redaction, masking, or
scoping of what gets sent to Langfuse. Low-stakes today because the actual
traffic is synthetic ("find me a hotel in the Algarve"), but the mechanism
would carry a real name, a real travel date, a real destination someone
doesn't want logged forever, completely unmodified, in a real deployment.

**In production**:
- **A masking function before spans are created.** Langfuse's SDK supports
  a `mask` callback applied to every observation's input/output before
  export — the natural hook for this, requiring no change to how
  `chat.py`/the tools/the providers already build their span inputs, only
  a function inserted between "what the app captured" and "what Langfuse
  receives."
- **Decide what's actually needed.** Not every field needs full-fidelity
  capture — a destination name is useful for debugging a bad
  recommendation; a user's exact free-text message may not need to survive
  past a much shorter window than the aggregate metrics do (see
  [Data retention](#data-retention)).
- **This needs legal/compliance sign-off**, not just an engineering
  decision — what counts as PII, and what retention period is defensible,
  varies by jurisdiction (GDPR, CCPA) and by what the product actually
  promises users about their data.

## Secrets

**Today**: `.env.example` ships real, working (if throwaway) secrets for
zero-friction local dev — explicitly documented since Milestone 1/ADR-005
as *"NOT safe to reuse for anything reachable from outside your
machine."* No secrets manager, no rotation, no least-privilege scoping
beyond "public key can only write, secret key can also score" (Langfuse's
own key-pair model).

**In production**: a real secrets manager (AWS Secrets Manager, HashiCorp
Vault, GCP Secret Manager) — no secret, including a placeholder, in any
file that could be committed; automated rotation; per-environment key
pairs (dev/staging/prod Langfuse projects already give this axis for free,
per the [Langfuse](#langfuse) section above); and the CORS
policy tightened from `allow_origins=["*"]` (`api/app.py`, appropriate for
local dev only) to an explicit allow-list. Authentication is worth naming
here too even though the spec's own list doesn't include it by name: there
is currently no auth on any route at all — a real production API needs
this decided before anything else on this list matters.

## Scaling

**Today**: a single Uvicorn process (`make serve`), and — the single most
concrete, load-bearing finding in this entire document — a single
in-process `dict` holding all conversation history
(`ConversationStore`, M7). Its own docstring calls this "semi-durable":
*"durable enough to give the agent real multi-turn memory across requests
within one running process, but gone on restart... deliberately not built
[with Redis/Postgres] here, since nothing else in this project needs a
database."* That choice is correct for one developer running one process.
It is the first thing that breaks the moment the API scales horizontally: a
request landing on replica B has no knowledge of history a previous turn
wrote to replica A's memory, and a user's multi-turn conversation silently
loses context depending on which replica the load balancer happens to
route to.

**In production**: move `ConversationStore`'s state out of the process —
Redis (the same technology Langfuse's own stack already runs for its async
ingestion queue, see [Asynchronous ingestion](#asynchronous-ingestion)
below) is the natural fit: `session_id`-keyed, TTL'd, shared across every
replica. `ConversationStore`'s own interface (`get_history()`/`append_turn()`)
was already designed as a narrow enough boundary that swapping its backing
store wouldn't need to touch `chat.py`'s calling code — the same
"provider abstraction, callers don't change" pattern this project has
already used repeatedly (LLM, travel search, Langfuse host) would apply
here too, just not built, since a single-process educational deployment
never needed it.

## High availability

**Today**: every component is a single point of failure — one API
process, one Postgres, one ClickHouse, one Redis, one MinIO, each
unreplicated in `docker-compose.yml`. `GET /health` (M0) is the right hook
for a load balancer's health check, but there's currently only one process
for it to check.

**In production**: multiple API replicas behind a load balancer using that
same `/health` endpoint (once [Scaling](#scaling)'s conversation-store fix
makes replicas actually interchangeable); managed or explicitly-replicated
versions of Postgres/ClickHouse/Redis, or — the simpler path — Langfuse
Cloud, which removes the HA burden for all four backing services in one
decision rather than four separate ones. This is the strongest concrete
argument for Cloud over self-hosting in a production context specifically,
distinct from the "no signup friction" reason self-hosted was chosen as
this project's own *local dev* default.

## Asynchronous ingestion

**Today**: already real, already production-shaped — the one topic on this
list where the current architecture needs no change, not a caveat. Every
span this project creates batches and exports asynchronously on a
background thread; this has been load-bearing since Milestone 1 (the
"$LANGFUSE call never blocks the request" design) and was proven directly
in Milestone 15: pointing `LANGFUSE_HOST` at an unreachable host still
returns a real `/chat` response in under 2 seconds, because ingestion never
sits in the request's own critical path
(`tests/integration/test_langfuse_unavailable.py`). Langfuse's own
self-hosted stack additionally runs a Redis-backed queue between
ingestion and ClickHouse storage (`docs/langfuse.md`) — the same pattern
[Scaling](#scaling)'s conversation-store fix above would extend to this
project's own state, not a new idea being introduced for the first time.

## Multi-region

**Today**: not applicable — one Docker Compose stack, one region,
implicitly wherever the developer's machine (or a single cloud region)
happens to be. No CDN, no edge routing, no region-aware anything.

**In production**, and genuinely only once the scale justifies it (this is
the one item on this list that's purely scale-later, never a launch
blocker): region-local API deployments behind a global load balancer;
either a single global Langfuse project or region-pinned ones, decided by
whichever is more binding — data-residency compliance or query latency for
whoever's *reading* traces; and, once conversation state has already moved
to Redis per [Scaling](#scaling), a decision between cross-region
replication (higher latency, works if a user's session can land in any
region) or region-sharded sessions (lower latency, requires routing a
session consistently back to its own region — the load balancer needs to
know that a given `session_id` belongs to a given region, which a naive
health-check-based LB does not do by default).

---

## Priority: what would actually block a launch

Not every item above carries the same urgency. Roughly, in the order a
real production rollout of this system would need to close them:

1. **Secrets and authentication** — nothing else on this list matters if
   the API is reachable, unauthenticated, with dev credentials, from the
   public internet.
2. **PII and data retention** — a real legal/compliance blocker the moment
   real user data flows through the system, not a nice-to-have.
3. **Scaling (the conversation store) and high availability** — the first
   thing that silently breaks correctness (not just performance) the
   moment there's more than one replica.
4. **API metrics, logs, and alerting** — without these, every problem
   above is invisible until a user reports it, not caught by the team
   first.
5. **Trace sampling and cost alerting** — real money and storage costs at
   real traffic volume, but a scaling concern, not a correctness one.
6. **Distributed tracing, a general OTel Collector, and multi-region** —
   genuinely not needed until there's a second real service, a second APM
   consumer, or a second region respectively; building any of these before
   they're needed would be exactly the premature complexity this project
   has avoided throughout every prior milestone.

The throughline across all twelve topics is the same one this project's
own `RATIONALE_PER_MILESTONE.md` entries repeat constantly: a shortcut
that's correct for a single-developer educational deployment (in-memory
state, no sampling, no auth, unbounded retention) becomes actively
incorrect at production scale, not just less polished — and knowing
exactly *which* shortcut breaks *first*, and *why*, is the actual
architectural understanding this milestone asks for.
