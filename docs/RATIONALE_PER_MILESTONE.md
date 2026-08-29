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
