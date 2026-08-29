# ADR-005: Headless Initialization for Local Langfuse

**Date:** 2026-08-29
**Status:** Accepted

## Context

A from-scratch self-hosted Langfuse instance normally requires a manual signup flow before any SDK call can succeed: create an account in the UI, create an organization, create a project, generate an API key pair, then copy those keys into the application's configuration. For a single developer that's a few minutes; for an open-source educational repo where reproducibility is a stated goal (`.env.example`, `make env`, "reproducible local development" in the project spec), it's friction that has to be repeated by every contributor and every fresh clone.

Langfuse supports an alternative: `LANGFUSE_INIT_*` environment variables passed to `langfuse-web`, which provision an org/project/user/API-key-pair automatically the first time it boots against an empty database.

## Options

### Option A — Manual signup only

Document the UI signup flow; developers paste generated keys into `.env` themselves.

**Pros:** No pre-known secrets baked into `.env.example`. Matches what a first-time Langfuse user would naturally do.
**Cons:** Breaks the "clone, `make env`, `make langfuse-up`, it works" flow. Every contributor's local keys differ, so example commands/docs can't reference a stable key.

### Option B — Headless initialization only

Set `LANGFUSE_INIT_*` in `.env.example` so `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` are valid immediately after first boot.

**Pros:** True one-command reproducibility. Matches the project's existing bias toward `make`-driven, zero-manual-step workflows.
**Cons:** Contributors who only read the docker-compose file might not immediately understand where the "already working" keys came from. Slightly more upfront explanation needed.

### Option C — Both, but the UI is the default

Requires deciding a default, defeating the point.

## Decision

**Option B, with the manual flow documented as an explicit alternative** (`docs/langfuse.md`).

The headless-init values in `.env.example` are placeholder secrets, generated once and committed as an example — not meaningfully different from `POSTGRES_PASSWORD=postgres` being an obviously-not-for-production default. `docs/langfuse.md` says this explicitly: regenerate everything before running this anywhere reachable by anyone else.

## Consequences

- `.env.example` includes `LANGFUSE_INIT_ORG_ID`, `_PROJECT_ID`, `_PROJECT_PUBLIC_KEY`, `_PROJECT_SECRET_KEY`, `_USER_EMAIL`, `_USER_PASSWORD`, etc., with the public/secret key values matching `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` used by the application.
- These only take effect against a Postgres that has never been initialized. Changing them after the first boot requires `docker compose down -v` (destroys all local trace history) to take effect — documented in `docs/langfuse.md`.
- The manual signup path remains fully functional (leave `LANGFUSE_INIT_*` blank) for anyone who wants to see that flow or run multiple independent projects against one Langfuse instance.
