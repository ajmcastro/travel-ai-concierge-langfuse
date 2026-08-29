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
