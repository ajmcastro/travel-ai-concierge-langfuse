# Langfuse — Self-Hosted Reference (Milestone 1)

This document explains the local Langfuse deployment: what runs, why, how to reach it, and how to find your data once the application starts sending traces.

## Why self-hosted, and why this exact stack

We mirror the official Langfuse self-hosted architecture rather than inventing a simplified one:

- https://github.com/langfuse/langfuse/blob/main/docker-compose.yml
- https://langfuse.com/self-hosting/docker-compose

As of this milestone, that's Langfuse **v4** — a jump from the v3 architecture referenced in earlier planning docs in this repo (ADR-004). The service topology (Postgres/ClickHouse/Redis/MinIO + web/worker) is unchanged; the image tags moved to `docker.langfuse.com/langfuse/*:4`. `docs/decisions/ADR-004-langfuse-deployment.md` is otherwise still accurate.

## Services

| Service | Image | Purpose | Host port(s) |
|---|---|---|---|
| `langfuse-web` | `langfuse/langfuse:4` | UI + REST/OTel ingestion API | `${LANGFUSE_WEB_PORT:-3000}` |
| `langfuse-worker` | `langfuse/langfuse-worker:4` | Drains the Redis queue into ClickHouse | `127.0.0.1:3030` |
| `postgres` | `postgres:17` | Relational metadata: projects, users, prompts, datasets | `127.0.0.1:5432` |
| `clickhouse` | `clickhouse-server:25.12` | Trace/observation event storage (columnar) | `127.0.0.1:8123`, `127.0.0.1:9000` |
| `redis` | `redis:7` | Async ingestion queue between web/worker and ClickHouse | `127.0.0.1:6379` |
| `minio` | `chainguard/minio` | S3-compatible blob storage (large payloads, media) | `9090` (S3 API), `127.0.0.1:9091` (console) |

Everything except `langfuse-web` and MinIO's S3 port is bound to `127.0.0.1` — not reachable from other machines on your network, matching the upstream file's security posture.

**Startup order**: `postgres`, `redis`, `clickhouse`, `minio` must all report healthy before `langfuse-worker` and `langfuse-web` start (enforced by `depends_on: condition: service_healthy` in `docker-compose.yml`). First boot additionally runs schema migrations inside `langfuse-web`/`langfuse-worker` — expect the first `make langfuse-up` to take noticeably longer than subsequent ones.

**Persistence**: five named volumes (`langfuse_postgres_data`, `langfuse_clickhouse_data`, `langfuse_clickhouse_logs`, `langfuse_minio_data`, `langfuse_redis_data`) survive `docker compose down` / container restarts. To fully reset the stack (e.g. after changing `LANGFUSE_INIT_*` values, which only apply on a Postgres that has never been initialized), you must additionally remove the volumes: `docker compose down -v`.

## Credentials and headless initialization

A from-scratch self-hosted Langfuse normally requires a manual signup flow in the UI (create an account, create an org, create a project, generate an API key pair) before the SDK can send anything. For a reproducible educational repo, that manual step is friction we don't want every contributor to repeat.

Instead, `docker-compose.yml` passes `LANGFUSE_INIT_*` environment variables to `langfuse-web`. **On the first boot only** (i.e., the first time against an empty Postgres), Langfuse provisions:

- an organization (`LANGFUSE_INIT_ORG_ID` / `_ORG_NAME`)
- a project inside it (`LANGFUSE_INIT_PROJECT_ID` / `_PROJECT_NAME`)
- an API key pair for that project, set to the *exact* values you choose (`LANGFUSE_INIT_PROJECT_PUBLIC_KEY` / `_SECRET_KEY`)
- a user account you can log into the UI with (`LANGFUSE_INIT_USER_EMAIL` / `_NAME` / `_PASSWORD`)

Reference: https://langfuse.com/self-hosting/administration/headless-initialization

`.env.example` sets `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` / `_SECRET_KEY` to the **same values** as `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` used by the application's `Settings`. The result: `make env && make langfuse-up` gives you a stack where the app's configured keys are already valid — no copy-pasting from the UI required. You can still do it the manual way (see below) if you want to see that flow.

**This is a local-dev convenience, not a security model.** Every value in `.env.example` is a known, published placeholder. Regenerate all of them (`openssl rand -hex 32`, or `-hex 16` for the shorter ones) before running this anywhere reachable by anyone else.

## Starting the stack

```bash
make env          # copy .env.example → .env if you haven't already
make langfuse-up  # docker compose up -d
```

Wait for `langfuse-web` to report healthy (first boot: ~30–90s for migrations):

```bash
docker compose ps
```

## Accessing the UI

Open `http://localhost:${LANGFUSE_WEB_PORT:-3000}` (check your `.env` — see the port-conflict note below). Sign in with `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` from your `.env`.

**Port conflict**: if something else on your machine already listens on 3000, override `LANGFUSE_WEB_PORT` (and `LANGFUSE_HOST` / `NEXTAUTH_URL` to match) in your own `.env` — do not edit `docker-compose.yml`. This is exactly the situation encountered while building this milestone (an unrelated `open-webui` container held port 3000), resolved by setting `LANGFUSE_WEB_PORT=3001` locally.

## Creating your first trace

```bash
make langfuse-smoke-test
```

This runs `scripts/smoke_test_langfuse.py`, which:

1. Builds a `Langfuse` client from `Settings` (`src/travel_ai_concierge/observability/langfuse_client.py`)
2. Calls `auth_check()` to confirm the configured keys are valid
3. Opens a root span named `travel_concierge_turn`
4. Wraps a nested `generation`-type span (`mock_llm_call`) inside a `propagate_attributes(...)` context, so `session_id`, `user_id`, `tags`, and `environment` land on both spans
5. Flushes (spans are batched asynchronously — a short-lived script must flush before exiting)
6. Prints the trace URL

Open the printed URL. In the UI you should see:

- The trace name (`travel_concierge_turn`) and total latency
- **Session** and **User ID** chips (top of the trace panel) — click through to `Sessions` / `Users` in the left nav to see them aggregated
- A nested `mock_llm_call` **generation** in the left-hand tree, with token counts
- The `Tags` (`milestone-1`, `smoke-test`) and `Env` (`development`)
- `Metadata` showing the SDK version and public key used

If you'd rather do the manual signup flow: leave the `LANGFUSE_INIT_*` variables blank, start the stack, and use "Sign up" on the login page instead. You'll create the org/project/keys by hand and paste the generated keys into `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` in `.env` yourself.

## Querying trace data programmatically

This deployment runs Langfuse v4 in **"events_only" mode** — confirmed live (Milestone 6) by calling the public REST API directly:

```bash
curl -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
  "http://localhost:${LANGFUSE_WEB_PORT:-3000}/api/public/traces/<trace-id>"
# {"message":"This endpoint is not available on deployments running in
#  Langfuse v4 events_only mode. Learn more about Langfuse v4 at:
#  https://langfuse.com/docs/v4"}
```

`GET /api/public/traces/{id}` and `GET /api/public/observations` both return
this same message rather than data — **ingestion works normally** (the SDK
writes traces exactly as documented, and they render correctly in the UI),
but the read-side REST API for traces/observations specifically is disabled.
If you need to verify what actually got recorded on a trace without opening
the UI (e.g. from a script or a sandboxed environment without browser access
to `localhost`), don't reach for this API — see `tests/unit/test_trace_design.py`
for the pattern that actually works offline: construct a `Langfuse` client
with `span_exporter=InMemorySpanExporter()` and read the attributes off the
finished spans directly, since that exercises the exact same SDK code without
depending on any read API at all.

Milestone 14's cost/latency comparison hits this same wall from a different
angle: there's no way to pull a *cross-run* comparison (config A vs config B)
back out of Langfuse programmatically at all, `InMemorySpanExporter` included
— that pattern verifies one span's own attributes, not an aggregate across
many. `evaluation/cost_latency.py` sidesteps the read API question entirely
instead of working around it: it captures `LLMResponse.usage` and wall-clock
latency in its own process, before anything is ever sent to Langfuse, so it
never needs to read anything back.

## Stopping / resetting

```bash
make langfuse-down          # stop containers, keep data
docker compose down -v      # stop containers AND delete all data
```

## What's deliberately not covered here

- Prompt management is covered as of Milestone 8, a local deterministic evaluation framework as of Milestone 9, Langfuse dataset publishing/experiments as of Milestone 10, LLM-as-judge as of Milestone 11, human feedback scoring as of Milestone 12, agent trajectory evaluation as of Milestone 13, cost/latency experiments as of Milestone 14, controllable fault injection as of Milestone 15, a real trace-based debugging exercise as of Milestone 16, regression detection (`make eval-ci` as a CI quality gate) as of Milestone 17, a tested (not just documented) Langfuse Cloud switch as of Milestone 19, and a final N-config experiment matrix composing every prior evaluation mechanism as of Milestone 21 — see [docs/architecture.md](architecture.md#prompt-management-m8) and its "Evaluation Framework" / "Langfuse Datasets and Experiments" / "LLM-as-Judge" / "Human Feedback" / "Agent Trajectory Evaluation" / "Cost and Latency Experiments" / "Failure and Resilience Laboratory" / "Observability-Driven Debugging" / "Regression Detection" / "Final Experiment Suite" sections, [docs/DEBUGGING_WORKFLOWS.md](DEBUGGING_WORKFLOWS.md), and [docs/EXPERIMENTS.md](EXPERIMENTS.md) (Milestones 16-17, 19, 21). Milestone 17's regression gate itself is purely local, the same reasoning as Milestone 14's cost/latency comparison — no Langfuse read API involved at all, since "events_only" mode has none to use (see above).
- Production security hardening, TLS, multi-tenant auth — out of scope for a local educational stack (see ADR-004's discussion of the local/Cloud split)
- Switching to Langfuse Cloud — see `.env.example` and [ADR-004](decisions/ADR-004-langfuse-deployment.md); no code changes are required, only the three `LANGFUSE_*` values. **As of Milestone 19**, this claim is tested, not just asserted: `tests/integration/test_langfuse_connectivity.py` runs unmodified against whichever target `.env` currently names (`make test-integration`) — the exact same command and test file verify local self-hosted today, and would verify a real Cloud project the moment `.env`'s three `LANGFUSE_*` values point at one. See [docs/EXPERIMENTS.md](EXPERIMENTS.md), Milestone 19, for what was and wasn't exercised live in this environment.
