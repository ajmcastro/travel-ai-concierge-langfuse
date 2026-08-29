# Travel AI Concierge with Langfuse — Project Implementation Prompt

> **What this file is**: the original brief given to the AI pair-programmer (Claude Code) that built this repository, kept verbatim for transparency. It reads like a prompt because it is one — this project is developed milestone-by-milestone through a real human/AI collaboration, and this is the spec that collaboration follows. For a reader-friendly summary of what actually got built and why, start with the main [README](../README.md), [docs/architecture.md](architecture.md), and [docs/RATIONALE_PER_MILESTONE.md](RATIONALE_PER_MILESTONE.md) instead — come back here when you want the full, unabridged intent behind a milestone.

I want you to act as a **Senior Machine Learning Engineer, Agentic AI Architect, and LLMOps/AI Observability Engineer** and help me build an educational but production-quality open-source project called:

**Travel AI Concierge — Langfuse Observability Lab**

The purpose of this project is to learn and demonstrate how to design, instrument, monitor, evaluate, debug, and progressively improve a production-like **Agentic AI application using Langfuse**.

The application domain will be travel.

The system should behave as an AI Travel Concierge capable of interacting conversationally with users, understanding their travel needs, using tools, retrieving travel information, reasoning over alternatives, and constructing useful travel recommendations or itineraries.

However, the primary learning objective is **not travel recommendation itself**.

The Travel AI Concierge is the realistic workload through which we will learn:

- Agentic AI architecture
- production LLM observability
- tracing
- spans and generations
- session tracking
- user tracking
- prompt management
- token and cost monitoring
- latency analysis
- tool observability
- agent debugging
- evaluation datasets
- offline evaluation
- online evaluation
- LLM-as-judge
- human feedback
- experiments
- regression detection
- production failure analysis
- prompt/version comparison
- production AI quality engineering

The project will eventually be published as an open-source GitHub repository.

Therefore:

- do not use proprietary travel data
- do not use TUI branding, APIs, data, code, or intellectual property
- use synthetic or openly available data
- document the architecture carefully
- provide reproducible local development
- never commit credentials
- maintain a high-quality README
- include an MIT-compatible open-source structure unless I explicitly decide otherwise

This project is conceptually related to my existing **Travel AI Search** project.

Where useful, design the Travel AI Concierge so that it can later consume the Travel AI Search service through an API.

The Travel AI Concierge must nevertheless be capable of running independently using synthetic/local travel data.

I want to understand the implementation, not merely have you generate code.

Therefore work incrementally, explain important architectural choices, discuss meaningful alternatives, and avoid unnecessary complexity.

Do NOT generate the entire repository in one step.

---

# Main learning objectives

The project must progressively demonstrate:

1. Agentic AI application architecture
2. Tool-using LLM agents
3. Agent state and conversational context
4. FastAPI-based Agentic AI services
5. User-facing conversational interfaces
6. Langfuse architecture
7. Local self-hosted Langfuse
8. Optional Langfuse Cloud integration
9. LLM tracing
10. Agent-level tracing
11. Nested spans
12. Generation tracking
13. Tool-call observability
14. Session tracking
15. User tracking
16. metadata and tags
17. token usage monitoring
18. latency monitoring
19. LLM cost monitoring
20. model/provider tracking
21. error tracking
22. failure analysis
23. prompt management
24. prompt versioning
25. prompt deployment strategies
26. evaluation datasets
27. experiment execution
28. deterministic evaluators
29. LLM-as-judge evaluation
30. human evaluation and feedback
31. production scoring
32. trace-level scoring
33. regression testing
34. evaluation across prompt/model versions
35. tool-selection evaluation
36. agent trajectory evaluation
37. groundedness and hallucination evaluation
38. response quality evaluation
39. production-like debugging workflows
40. fallback and resilience strategies
41. observability-driven Agentic AI improvement
42. privacy and sensitive-data considerations
43. OpenTelemetry concepts where relevant
44. production AI monitoring architecture
45. CI-oriented AI evaluation
46. reproducible experimentation

The final project should answer an important engineering question:

> How do we know that an Agentic AI application is actually working correctly in production?

---

# Example user interactions

The final Travel AI Concierge should support interactions such as:

> "I'm planning a five-day trip to Portugal in October with my partner. We like food, wine and quieter places. We would prefer not to rent a car."

or:

> "Find me a family-friendly beach holiday somewhere warm in October under €2,500."

or:

> "I'm thinking about Mallorca, but perhaps somewhere quieter. What would you suggest?"

or:

> "Plan a three-day itinerary in Porto. I like architecture, local food and wine but don't want a packed schedule."

The system should be conversational.

It should be capable of asking clarification questions when important information is missing.

For example:

User:

> "Find me somewhere warm for a week."

Concierge:

> "Sure. What month are you travelling, approximately what budget do you have, and where would you be departing from?"

The final system should demonstrate multi-turn conversational state.

---

# Core architectural principle

The system should be designed around two separate concerns:

## Business capability

Travel AI Concierge

and:

## AI operations capability

Langfuse observability and evaluation

Langfuse must NOT be hidden behind a tiny generic logging abstraction that makes its concepts impossible to learn.

We want clean integration boundaries, but the implementation should expose Langfuse concepts clearly enough that a developer can understand:

- trace
- span
- generation
- observation
- session
- user
- metadata
- tags
- score
- dataset
- dataset item
- experiment
- prompt
- prompt version

Prefer explicit implementations over magic.

---

# Technology requirements

Use Python.

IMPORTANT:

Use `uv` for ALL Python version, virtual environment and package management.

Do NOT use:

- Poetry
- Pipenv
- Conda
- requirements.txt as the primary dependency mechanism
- direct pip-based project management

Use:

- `uv python`
- `uv init`
- `uv add`
- `uv remove`
- `uv sync`
- `uv run`

as appropriate.

Maintain dependencies in:

`pyproject.toml`

and commit:

`uv.lock`

Prefer Python 3.12 unless dependency compatibility gives a strong reason to select another supported version.

Use:

- Python
- FastAPI
- Pydantic
- Pydantic Settings
- Langfuse Python SDK
- Docker Compose
- pytest
- Ruff
- mypy where useful
- httpx
- structured logging
- an appropriate LLM provider SDK
- optionally LangGraph if justified by the agent orchestration requirements

For the UI, prefer a lightweight implementation.

Evaluate at least these alternatives:

- Streamlit
- Gradio
- lightweight React/Next.js frontend

For the initial educational implementation, prefer **Streamlit** unless there is a compelling architectural reason not to.

The frontend is not the primary learning objective.

The Agentic AI and observability architecture are.

---

# Agent orchestration framework

Do NOT automatically use a large Agentic AI framework merely because this is an agent project.

Before implementation, explicitly compare:

1. transparent Python orchestration
2. LangGraph
3. another major alternative only if relevant

For this project, **LangGraph is likely the preferred orchestration framework** because it gives us explicit:

- state
- nodes
- edges
- routing
- tool execution
- retries
- conditional transitions

and these concepts map well onto observability traces.

However, explain this decision before adopting it.

Avoid unnecessary LangChain abstractions where plain Python would be clearer.

If LangGraph is used, the developer must still understand the underlying agent execution flow.

Do not bury everything behind prebuilt agents.

---

# LLM provider architecture

The application must use a provider abstraction.

For example:

```python id="fgs30j"
class LLMProvider(Protocol):
    async def generate(...): ...
```

Possible implementations may eventually include:

- OpenAI provider
- AWS Bedrock provider
- local/mock provider

At least one provider should support a real LLM.

A deterministic fake/mock provider must exist for tests.

Do not hard-code model IDs throughout the system.

Configuration should select:

- provider
- model
- temperature
- max tokens where relevant
- timeout
- retry settings

The Langfuse instrumentation must capture provider/model metadata.

---

# Langfuse deployment modes

The project must support two Langfuse modes.

## Mode 1 — Local Langfuse

This is the default educational mode.

Langfuse must run through Docker Compose.

The developer should be able to execute approximately:

```bash id="98hkut"
make up
```

and start:

- required Langfuse infrastructure
- Langfuse server
- any required databases/services

The exact Langfuse Docker architecture must follow the officially supported self-hosting architecture for the Langfuse version we use.

Do NOT invent a simplified deployment that differs materially from current Langfuse recommendations.

Document:

- services
- ports
- volumes
- databases
- credentials
- persistence
- startup order

The Langfuse UI should be reachable locally through a documented URL.

---

# Mode 2 — Langfuse Cloud

The application should optionally support:

https://cloud.langfuse.com/

Switching between local Langfuse and Langfuse Cloud should require configuration changes only.

For example:

```env id="vw8kpx"
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=
```

Never commit real credentials.

Provide:

`.env.example`

Local Langfuse must remain the default path for learning and development.

---

# Architecture principles

Follow these principles:

- clean architecture without overengineering
- clear domain/infrastructure separation
- dependency injection where useful
- typed Python
- Pydantic at system boundaries
- async APIs where beneficial
- configuration via environment variables
- structured logging
- `.env.example`
- never commit real credentials
- unit tests
- integration tests
- reproducible Docker infrastructure
- deterministic test fixtures
- Makefile required
- clear README
- architecture documentation
- ADRs for meaningful architectural decisions
- graceful degradation where useful

Do not create abstractions merely for design-pattern purity.

---

# Target repository structure

Start approximately with:

```text id="bf730b"
travel-ai-concierge-langfuse/
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── Makefile
├── docker-compose.yml
├── .env.example
├── .gitignore
│
├── data/
│   ├── synthetic/
│   ├── knowledge/
│   └── evaluation/
│
├── docs/
│   ├── architecture.md
│   ├── observability.md
│   ├── evaluation.md
│   ├── langfuse.md
│   ├── PROJECT_SPEC.md
│   ├── experiments/
│   └── decisions/
│
├── scripts/
│   ├── generate_data.py
│   ├── seed_evaluation_dataset.py
│   ├── run_evaluation.py
│   └── ...
│
├── src/
│   └── travel_ai_concierge/
│       ├── api/
│       │   ├── app.py
│       │   ├── routes/
│       │   └── schemas/
│       │
│       ├── config/
│       │
│       ├── domain/
│       │
│       ├── agent/
│       │   ├── state.py
│       │   ├── graph.py
│       │   ├── nodes/
│       │   └── routing.py
│       │
│       ├── tools/
│       │
│       ├── providers/
│       │   ├── llm/
│       │   └── search/
│       │
│       ├── observability/
│       │   ├── langfuse.py
│       │   └── context.py
│       │
│       ├── evaluation/
│       │   ├── evaluators/
│       │   ├── datasets.py
│       │   └── runner.py
│       │
│       └── infrastructure/
│
├── ui/
│   └── ...
│
└── tests/
    ├── unit/
    ├── integration/
    └── evaluation/
```

Improve this structure if there is a good architectural reason.

Do NOT create dozens of empty files just to match the target structure.

Introduce modules when they become necessary.

---

# Travel domain model

Design a small but realistic travel domain.

Possible entities include:

## Destination

- id
- name
- country
- region
- description
- climate
- typical_weather
- beach
- nightlife
- family_suitability
- couples_suitability
- activities
- food
- culture
- nature
- transport_characteristics
- tags

## Hotel

- id
- name
- destination
- description
- star_rating
- customer_rating
- amenities
- family_friendly
- adults_only
- board_types
- beach_distance
- city_centre_distance
- price_band
- tags

## Flight option

Potential fields:

- origin
- destination
- departure
- arrival
- duration
- price

These may be synthetic rather than representing live flight inventory.

## User travel preferences

Possible fields:

- origin
- destination
- dates
- duration
- travellers
- children
- budget
- interests
- constraints
- accommodation preferences
- transport preferences
- soft preferences

Do not blindly implement all these fields.

Design the minimum coherent domain needed by the agent tools.

---

# Dataset

Use deterministic synthetic travel data.

Where useful, the dataset may be compatible with or derived conceptually from the synthetic dataset used by the existing Travel AI Search project.

Do NOT require the Travel AI Search project in the first milestones.

The repository should work independently.

Later introduce an optional:

`TravelSearchProvider`

with implementations such as:

- `LocalSyntheticTravelSearchProvider`
- `TravelAISearchAPIProvider`

The second implementation may call a separately running Travel AI Search API.

This demonstrates service composition without creating a hard dependency.

Do not duplicate the entire Travel AI Search implementation inside this project.

---

# Agent capabilities

The Travel AI Concierge should eventually expose tools approximately like:

- search destinations
- search hotels
- search holiday options
- retrieve destination knowledge
- compare destinations
- build itinerary
- calculate approximate trip cost

Potential tool names:

```text id="5e0is0"
search_destinations
search_hotels
search_holidays
get_destination_information
compare_destinations
build_itinerary
estimate_trip_cost
```

Do not implement fake complexity.

Each tool should have a clear purpose.

Tool parameters and return types should be typed.

---

# Agent workflow

A possible conceptual workflow is:

```text id="mynilx"
User
  ↓
Conversation API
  ↓
Agent
  ↓
Understand request
  ↓
Need clarification?
 ├── yes → ask user
 └── no
       ↓
Select tool(s)
       ↓
Execute tools
       ↓
Interpret results
       ↓
Need another tool?
 ├── yes → continue
 └── no
       ↓
Generate final answer
       ↓
Return response
```

If using LangGraph, represent these transitions explicitly where useful.

Do not assume every user request requires every step.

---

# FastAPI

Expose the backend through FastAPI.

At minimum consider:

```text id="7lj4ly"
GET  /health

POST /chat
POST /chat/stream

GET  /sessions/{session_id}

POST /feedback
```

Potential development/debug endpoints may include:

```text id="rdu91m"
GET /debug/config
POST /debug/agent
```

Do not expose sensitive configuration.

The primary endpoint should accept approximately:

```json id="3b9aq1"
{
  "message": "Plan me a quiet 5-day trip to Portugal",
  "session_id": "...",
  "user_id": "..."
}
```

and return approximately:

```json id="9e2e74"
{
  "session_id": "...",
  "message": "...",
  "trace_id": "...",
  "metadata": {}
}
```

Returning a Langfuse trace identifier in development mode is desirable because it allows the developer to immediately inspect the execution.

Do not necessarily expose it in a real production client.

---

# Chat UI

Provide a simple user-facing UI.

The UI must support:

- multi-turn chat
- session continuity
- displaying assistant responses
- displaying errors cleanly
- resetting conversation
- optionally showing debug information

A development/debug panel may optionally display:

- session ID
- trace ID
- model
- latency
- tool calls

The main UI must remain understandable to a normal travel user.

Prefer keeping detailed observability inside Langfuse rather than building a second observability dashboard.

---

# Langfuse UI

The project must clearly document how to access Langfuse.

The developer should be able to:

1. start the system
2. interact with the Travel AI Concierge
3. open Langfuse
4. find the generated trace
5. inspect the agent trajectory
6. inspect LLM calls
7. inspect tool calls
8. inspect latency
9. inspect token usage
10. inspect cost
11. inspect errors
12. inspect scores

This is a critical end-to-end learning workflow.

---

# Langfuse observability model

Design traces deliberately.

One chat turn should typically correspond to one top-level trace.

For example:

```text id="ulxmzg"
travel_concierge_turn
│
├── understand_request
│   └── generation
│
├── agent_reasoning
│
├── tool.search_destinations
│
├── tool.search_hotels
│
├── itinerary_generation
│   └── generation
│
└── final_response
    └── generation
```

Do not create spans merely for every Python function.

Observability should reflect meaningful AI/business operations.

---

# Trace metadata

Capture useful metadata such as:

- environment
- application version
- git commit when practical
- agent version
- prompt version
- model
- provider
- session ID
- user ID
- request type
- selected tools
- feature flags
- experiment variant
- error/fallback indicators

Use tags where appropriate.

Potential tags:

```text id="gleczu"
travel-concierge
development
production
evaluation
prompt-v2
fallback
```

Avoid excessive cardinality where inappropriate.

---

# Sessions

Use Langfuse session concepts deliberately.

Each multi-turn conversation should map to a session.

This must allow us to answer questions like:

- what happened throughout this user's conversation?
- which turns were slow?
- which turn caused the bad recommendation?
- did the agent repeatedly call the same tool?
- did context size grow excessively?
- did quality degrade across the conversation?

---

# User tracking

Support a user identifier.

For synthetic/demo scenarios, generate synthetic users.

Do NOT use personally identifiable information unnecessarily.

Document privacy implications.

Explain what information should and should not be sent to Langfuse in real production systems.

---

# LLM generation observability

Capture for each relevant LLM call:

- provider
- model
- input
- output
- token usage
- latency
- generation parameters
- prompt identifier/version where applicable
- errors
- estimated cost where available

Where supported, rely on Langfuse-native mechanisms.

Avoid manually duplicating functionality already handled correctly by the SDK.

---

# Tool observability

Tool calls are a critical part of Agentic AI observability.

Each tool invocation should make it possible to understand:

- tool selected
- input parameters
- execution time
- output summary
- whether it succeeded
- whether fallback occurred

For example:

```text id="i5qz1o"
search_hotels

input:
destination = Algarve
family_friendly = true
max_budget = 2500

result_count = 8
latency_ms = 43
```

Avoid recording unnecessarily large payloads.

---

# Cost observability

The project should demonstrate:

- token counts
- per-generation cost where supported
- cost per trace
- cost per session
- relative cost across prompt/model strategies

Eventually allow an experiment such as:

```text id="7q1td9"
Agent v1:
quality = 0.78
average cost = $0.012

Agent v2:
quality = 0.81
average cost = $0.037
```

and discuss whether the quality increase justifies approximately 3× cost.

Cost must become part of AI engineering decisions.

---

# Latency observability

Measure at least:

- API latency
- agent turn latency
- LLM latency
- tool latency
- retrieval latency
- final answer generation latency

Eventually compute:

- p50
- p95
- p99 where meaningful

Do not optimize blindly.

Use Langfuse traces to identify where latency actually occurs.

---

# Error observability

Demonstrate realistic failures.

Potential examples:

- LLM timeout
- malformed structured response
- travel search unavailable
- tool exception
- no results
- invalid tool arguments
- Langfuse unavailable
- LLM provider unavailable

Errors should be visible in observability data.

The user-facing application should degrade gracefully.

---

# Resilience

Design sensible fallbacks.

Examples:

If the LLM fails to extract structured preferences:

```text id="9brii8"
→ continue with original user message where possible
```

If the primary travel search provider fails:

```text id="rwpx6i"
→ use local synthetic provider if configured
```

If itinerary generation fails:

```text id="sglx5c"
→ return the retrieved travel options with an explanatory response
```

If Langfuse is unavailable:

```text id="3622mi"
→ the application should continue serving users
→ emit structured application logs
→ do not make observability a hard runtime dependency where avoidable
```

This last case is particularly important.

Observability must not normally cause the primary application to fail.

Add tests for relevant fallback behaviour.

---

# Prompt management

Prompt management is an important learning objective.

Initially prompts may live in source code so the architecture remains understandable.

Later introduce Langfuse Prompt Management.

Candidate prompts:

- system prompt
- travel preference extraction
- destination comparison
- itinerary generation
- final response

Demonstrate:

- prompt creation
- prompt version
- production/staging labels if supported
- retrieving prompts through the Langfuse SDK
- caching/fallback
- prompt metadata

Do not make the application unable to start if remote prompt retrieval fails.

Use an appropriate local fallback strategy.

---

# Prompt experiments

Eventually compare prompt versions.

Example:

```text id="cw5tz1"
travel-concierge-system-v1
travel-concierge-system-v2
```

Evaluate:

- correctness
- helpfulness
- tool-selection accuracy
- groundedness
- latency
- token usage
- cost

Do not declare a prompt superior based on a few manually inspected examples.

---

# Evaluation architecture

Evaluation is a critical project requirement.

We need to demonstrate multiple evaluation layers.

## Layer 1 — deterministic evaluation

Use evaluators that do not require an LLM where possible.

Potential metrics:

- expected tool called
- required tool arguments present
- destination constraint respected
- budget constraint respected
- output JSON/schema validity
- itinerary day count
- response contains required citations/evidence where relevant
- unsupported destination avoided

These evaluators are cheap and deterministic.

---

# Layer 2 — LLM-as-judge

Use an LLM judge for qualities that are difficult to capture deterministically.

Potential dimensions:

- relevance
- helpfulness
- completeness
- groundedness
- itinerary coherence
- constraint satisfaction
- conversational quality

Scores may use a scale such as:

```text id="yjh4sf"
1 = poor
2 = weak
3 = acceptable
4 = good
5 = excellent
```

The judge must also produce a concise rationale.

Do not blindly trust LLM-as-judge scores.

Document:

- judge model
- judge prompt
- model version
- known biases
- stochasticity
- limitations

Where practical, use an independent model family from the primary application model.

---

# Layer 3 — human feedback

Allow UI users to provide at least:

- thumbs up
- thumbs down

Optionally:

- 1–5 rating
- textual feedback

Associate feedback with:

- trace
- session
- response

Send the score to Langfuse.

This allows production-like analysis:

> What traces received negative user feedback?

---

# Evaluation dataset

Create a deterministic evaluation dataset.

Initially include approximately 30–50 cases.

Eventually expand toward 100+.

Query classes should include:

- destination recommendation
- hotel recommendation
- family holiday
- couples holiday
- budget
- luxury
- beach
- city
- culture
- nightlife
- quiet
- food/wine
- itinerary planning
- vague request
- multi-constraint query
- requests requiring clarification
- requests requiring one tool
- requests requiring multiple tools
- impossible constraint
- contradictory preferences

Example item:

```json id="utwxfy"
{
  "id": "family-beach-001",
  "input": {
    "message": "Find a family beach holiday somewhere warm in October under €2500."
  },
  "expected": {
    "should_use_tool": true,
    "expected_tools": ["search_holidays"],
    "constraints": {
      "family_friendly": true,
      "month": "October",
      "max_budget": 2500
    }
  }
}
```

Do not make the evaluation dataset depend entirely on LLM-generated labels.

---

# Langfuse datasets

Once basic evaluation exists locally, integrate the dataset with Langfuse datasets.

Demonstrate:

- dataset creation
- dataset items
- running experiments
- associating traces with dataset items
- collecting evaluation scores
- comparing experiments

The local JSON/JSONL dataset should remain version-controlled and reproducible.

Langfuse is an execution/analysis layer, not the only source of truth for test cases.

---

# Experiments

Create explicit experiments.

Examples:

## Experiment A

Prompt v1 vs Prompt v2.

## Experiment B

Model A vs Model B.

## Experiment C

single-agent vs explicit planning step.

## Experiment D

tool description v1 vs v2.

## Experiment E

temperature 0 vs higher temperature.

Measure at least:

- quality
- constraint satisfaction
- tool selection
- latency
- cost

Each experiment must have a written hypothesis.

---

# Agent trajectory evaluation

Final-answer quality alone is insufficient for Agentic AI.

Evaluate the path taken by the agent.

Potential questions:

- did it call unnecessary tools?
- did it call the correct tools?
- did it repeat the same tool?
- did it ask an unnecessary clarification?
- did it fail to ask a necessary clarification?
- did it use tool results?
- did it ignore retrieved evidence?
- was the trajectory excessively long?

Create trajectory-related metrics such as:

```text id="d2ig71"
tool_precision
tool_recall
unnecessary_tool_calls
repeated_tool_calls
total_tool_calls
agent_steps
```

Where meaningful.

---

# Groundedness

The Travel AI Concierge should distinguish:

- statements supported by tool/data results
- generic conversational guidance
- unsupported factual claims

Eventually add a groundedness evaluator.

For example, if a tool says:

```text id="okuxz8"
Hotel price: €1,850
```

the assistant must not claim:

```text id="kaypk9"
The holiday costs €1,500.
```

Use synthetic ground truth to make these cases testable.

---

# Hallucination tests

Create adversarial evaluation cases.

For example:

> "Does the Ocean Palace Hotel in Porto have a private beach?"

if no such hotel exists.

The agent should not invent information.

Other cases:

- nonexistent airport
- nonexistent hotel
- unavailable destination
- impossible dates
- budget below every available product

Measure refusal/uncertainty quality.

---

# Online / production evaluation

Eventually simulate a production stream.

For example:

1. issue synthetic conversations
2. generate traces
3. apply evaluators
4. analyse distributions
5. intentionally deploy a worse prompt
6. observe regression
7. detect the regression through Langfuse

This is an important milestone.

The project should demonstrate not just:

> "Here is an evaluation score."

but:

> "Here is how an engineer discovers that yesterday's deployment reduced agent quality."

---

# Regression testing

Create an evaluation quality gate.

For example:

```text id="zqlas4"
overall_quality >= baseline - tolerance
constraint_satisfaction >= 0.90
tool_accuracy >= 0.90
hallucination_rate <= 0.05
```

Do NOT choose arbitrary final thresholds without experimentation.

Start with illustrative thresholds and document them.

Eventually allow something like:

```bash id="zxb70a"
make eval-ci
```

to return a non-zero exit code if the evaluated agent regresses beyond the configured tolerance.

---

# Observability versus application monitoring

Explain an important distinction.

Langfuse focuses primarily on:

- LLM/agent observability
- traces
- generations
- prompts
- evaluations
- experiments
- AI quality

It should not necessarily replace infrastructure/application monitoring tools such as:

- Prometheus
- Grafana
- OpenTelemetry collectors
- cloud infrastructure monitoring
- API metrics/APM

Initially, avoid adding a giant infrastructure observability stack.

However, design the FastAPI service so conventional metrics could later be added.

Document how Langfuse and infrastructure observability complement each other.

---

# Structured logging

Use structured application logs.

Include useful fields such as:

- request_id
- trace_id
- session_id
- user_id
- tool
- latency
- error type

Be careful not to duplicate huge LLM inputs and outputs in both application logs and Langfuse.

Explain the difference between operational logs and AI traces.

---

# Privacy and security

Include a dedicated discussion of observability privacy.

Explain risks such as:

- prompts containing PII
- tool parameters containing personal information
- travel dates
- locations
- user profile data
- sensitive user messages

Demonstrate strategies such as:

- data minimisation
- masking/redaction
- synthetic IDs
- environment-specific sampling
- configurable capture
- retention policies

Do not implement elaborate enterprise compliance infrastructure.

The learning objective is to understand the architectural concerns.

---

# Sampling

Discuss trace sampling.

During development:

```text id="cx49ai"
100% tracing
```

may be appropriate.

At production scale, tracing everything may have:

- cost
- storage
- privacy
- operational implications

Eventually make sampling configurable.

Do not prematurely optimize it.

---

# Environment separation

Support meaningful environment metadata.

At minimum:

```text id="41daid"
development
test
evaluation
production
```

Evaluation traces should be distinguishable from real interactive traces.

Do not pollute production-like dashboards with automated evaluation traces without tagging them.

---

# Open-source requirements

The repository is intended for GitHub.

Provide:

- `README.md`
- `LICENSE`
- `.gitignore`
- `.env.example`
- `CONTRIBUTING.md` eventually
- architecture diagrams
- reproducible commands
- documented prerequisites
- no credentials
- no proprietary data

README badges may eventually include:

- Python version
- Ruff
- tests
- license

Do not add decorative badges before the corresponding functionality exists.

---

# README

The README should eventually contain:

1. Project motivation
2. What Langfuse is
3. What this project teaches
4. Architecture
5. Agent workflow
6. Observability architecture
7. Technologies
8. Installation using uv
9. Running Langfuse locally
10. Optional Langfuse Cloud setup
11. Starting the Travel AI Concierge API
12. Starting the chat UI
13. Example conversations
14. Inspecting traces
15. Understanding spans/generations
16. Prompt management
17. Evaluation
18. Datasets
19. Experiments
20. Human feedback
21. Cost analysis
22. Latency analysis
23. Regression testing
24. Travel AI Search integration
25. Architecture decisions
26. Limitations
27. Future work

Use Mermaid diagrams where useful.

---

# Architecture documentation

Create:

```text id="387jgc"
docs/architecture.md
```

Eventually include diagrams approximately like:

```text id="0i92g5"
                        ┌─────────────────┐
                        │   Chat UI       │
                        └────────┬────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │    FastAPI      │
                        └────────┬────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Travel AI Concierge     │
                    │ Agent / LangGraph       │
                    └──────┬─────────┬────────┘
                           │         │
                           ▼         ▼
                       Tools      LLM Provider
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
        Synthetic Travel      Travel AI Search
             Provider          optional API

                                 │
                                 │ instrumentation
                                 ▼
                         ┌───────────────┐
                         │   Langfuse    │
                         │               │
                         │ traces        │
                         │ generations   │
                         │ sessions      │
                         │ prompts       │
                         │ datasets      │
                         │ evaluation    │
                         └───────────────┘
```

Improve the diagram as the architecture evolves.

---

# Development workflow

Use `uv` exclusively for Python project management.

A `Makefile` is mandatory.

Developers should not need to remember long raw commands.

The Makefile is the canonical interface.

Initial workflow should eventually resemble:

```bash id="2skjp6"
make install
make env
make up
make health
make test
make serve
make ui
```

Potential core targets:

```bash id="ymocqa"
make install
make env

make up
make down
make restart
make logs

make langfuse-up
make langfuse-down
make langfuse-logs

make serve
make ui

make test
make test-unit
make test-integration

make lint
make format
make format-check
make typecheck
make check

make generate-data

make evaluate
make eval-ci

make clean
```

Every milestone must update the Makefile with its relevant targets.

Milestone instructions should reference:

```text id="dt73qy"
make <target>
```

rather than forcing developers to remember raw Docker or `uv run` commands.

---

# Testing strategy

Add tests progressively.

## Unit tests

Potential subjects:

- domain models
- configuration
- agent routing
- tool argument validation
- tool execution
- fallback logic
- evaluators
- scoring
- prompt rendering
- trace metadata construction

## Integration tests

Potential subjects:

- Langfuse connectivity
- FastAPI + agent
- tool execution
- local Langfuse ingestion
- evaluation dataset execution
- Travel AI Search provider

Most unit tests must NOT require:

- internet
- live Langfuse Cloud
- paid LLM API
- external infrastructure

Use fake/mock providers.

---

# Langfuse integration testing

Do not make every test depend on Langfuse.

Observability must be tested at appropriate boundaries.

For example:

- unit-test our metadata/context construction
- integration-test a small number of traces against local Langfuse
- mock Langfuse where the behavior under test is unrelated to Langfuse

Avoid fragile tests that assert internal implementation details of the Langfuse SDK.

---

# Important learning behaviour

This project is primarily educational.

Whenever implementing a major capability:

1. Briefly explain what problem it solves.
2. Explain the main design choice.
3. Explain important alternatives.
4. Explain what Langfuse concept we are learning, where relevant.
5. Implement the smallest clean version.
6. Add tests.
7. Show me how to run it using the Makefile.
8. Show me where to inspect the relevant data in Langfuse.
9. Give me 2–3 experiments I should manually perform.
10. Update the relevant documentation.
11. Record meaningful experiments.

Keep:

```text id="fcgi25"
docs/EXPERIMENTS.md
```

or an equivalent well-organized experiments section.

For each experiment record:

- hypothesis
- configuration
- dataset
- prompt version
- model
- evaluator
- quality metrics
- latency
- token usage
- cost
- result
- interpretation
- surprises
- limitations

Do NOT generate every feature in this prompt immediately.

---

# Implementation sequence

Work incrementally using the following milestones.

---

## Milestone 0 — Architecture and project scaffolding

Establish:

- architectural decisions
- repository structure
- `uv`
- `pyproject.toml`
- testing
- Ruff
- mypy where useful
- configuration
- structured logging
- Makefile
- basic FastAPI `/health`
- initial documentation
- Docker Compose skeleton

Do NOT implement the full agent.

Do NOT integrate every Langfuse feature.

Before writing code, explain:

- proposed architecture
- agent framework decision
- UI decision
- LLM provider abstraction
- Langfuse deployment architecture
- local vs cloud configuration

Create ADRs for major choices if useful.

---

## Milestone 1 — Local Langfuse

Deploy the officially supported self-hosted Langfuse architecture locally with Docker Compose.

Demonstrate:

```bash id="y8ryc5"
make langfuse-up
```

Then:

- access Langfuse UI
- create/configure local project credentials
- connect from a minimal Python example
- create first test trace

Document each Langfuse infrastructure component.

This milestone is about understanding Langfuse itself.

---

## Milestone 2 — Minimal Travel AI Concierge

Implement:

- FastAPI `/chat`
- LLM provider abstraction
- mock provider
- one real configurable LLM provider
- simple conversation request/response
- session ID
- user ID

No sophisticated tools yet.

Instrument each request with Langfuse.

Learn:

- trace
- generation
- session
- user
- model
- tokens
- latency

---

## Milestone 3 — Chat UI

Create the basic conversational UI.

Support:

- user chat
- multi-turn session
- reset
- feedback placeholders
- optional development trace link/identifier

Ensure API and UI remain separate.

---

## Milestone 4 — Synthetic travel tools

Create deterministic synthetic travel data.

Implement a few meaningful tools:

- `search_destinations`
- `search_hotels`
- `get_destination_information`

Connect them to the agent.

Learn:

- tool spans
- nested observations
- agent trajectory
- tool latency
- tool inputs/outputs

---

## Milestone 5 — Explicit Agentic AI workflow

Introduce the proper orchestration architecture.

If LangGraph was selected, implement explicit state and routing.

Support:

- user intent
- clarification
- tool selection
- tool execution
- final response

Instrument the graph meaningfully.

Compare traces from:

- simple chatbot
- tool-using agent

---

## Milestone 6 — Production-like trace design

Improve observability semantics.

Add:

- consistent names
- metadata
- tags
- environment
- application version
- feature flags
- agent version
- error metadata

Document the trace taxonomy.

Create examples of good versus poor trace design.

---

## Milestone 7 — Sessions and multi-turn analysis

Implement durable or semi-durable conversational state appropriate for the educational system.

Use Langfuse sessions.

Create multi-turn evaluation examples.

Analyse:

- cost per conversation
- token growth
- repeated tools
- total latency
- context accumulation

---

## Milestone 8 — Prompt management

Move selected prompts into Langfuse Prompt Management.

Support:

- named prompts
- versions
- labels/environment strategy where available
- local fallback
- prompt metadata

Compare prompt v1 vs v2.

---

## Milestone 9 — Evaluation framework

Implement the first local evaluation framework.

Create 30–50 deterministic test cases.

Implement deterministic evaluators.

Run:

```bash id="yfmznn"
make evaluate
```

Output machine-readable and human-readable results.

Do not require Langfuse datasets yet for the core evaluation engine.

---

## Milestone 10 — Langfuse datasets and experiments

Publish or synchronize evaluation cases with Langfuse datasets.

Run structured experiments.

Compare:

- prompt versions
- models
- agent configurations

Record:

- quality
- latency
- cost
- token usage

---

## Milestone 11 — LLM-as-judge

Implement:

```text id="kcohlp"
JudgeProvider
```

with:

- deterministic fake judge
- real configurable judge

Evaluate:

- relevance
- helpfulness
- groundedness
- constraint satisfaction
- itinerary coherence

Document methodological limitations.

Prefer an independent judge model family when possible.

---

## Milestone 12 — Human feedback

Add UI feedback.

Support:

- thumbs up
- thumbs down
- optional comment

Send feedback as Langfuse scores associated with the relevant trace.

Analyse low-rated traces.

---

## Milestone 13 — Agent trajectory evaluation

Evaluate:

- correct tool selection
- missing tools
- unnecessary tools
- repeated tools
- excessive agent steps
- clarification correctness

Compare final-answer evaluation with trajectory evaluation.

Demonstrate cases where:

> good answer ≠ good trajectory

and:

> poor answer despite reasonable trajectory

---

## Milestone 14 — Cost and latency experiments

Compare at least two configurations.

For example:

```text id="picwvj"
small model vs larger model
```

or:

```text id="co99mb"
one LLM planning step vs two
```

Measure:

- quality
- p50 latency
- p95 latency
- input tokens
- output tokens
- cost

Discuss the Pareto frontier:

```text id="6noxrw"
quality × latency × cost
```

---

## Milestone 15 — Failure and resilience laboratory

Create controllable fault injection.

Examples:

- LLM timeout
- travel provider error
- malformed model output
- tool timeout
- Langfuse unavailable
- no search results

Observe traces.

Verify graceful degradation.

Document production debugging workflows.

---

## Milestone 16 — Observability-driven debugging exercise

Intentionally introduce an agent problem.

For example:

- poor tool description causing wrong tool selection
- prompt causing excessive tool calls
- context causing hallucination

Generate traces.

Use Langfuse to diagnose the problem.

Fix it.

Run the same evaluation dataset.

Demonstrate measurable improvement.

This is one of the most important milestones.

---

## Milestone 17 — Regression detection

Establish a baseline.

Introduce a known weaker version.

Run evaluation.

Implement:

```bash id="3sishn"
make eval-ci
```

with configurable regression thresholds.

Demonstrate how AI evaluation could become a CI quality gate.

---

## Milestone 18 — Optional Travel AI Search integration

Introduce:

```text id="xtcrz0"
TravelAISearchAPIProvider
```

Call the separate Travel AI Search backend.

The Concierge may use Travel AI Search as one of its tools.

Trace:

```text id="nlgh61"
Concierge agent
→ search tool
→ Travel AI Search API
→ results
→ agent
```

Measure service latency independently from LLM latency.

The Travel AI Concierge must still support the synthetic local provider.

---

## Milestone 19 — Langfuse Cloud

Document and test optional Langfuse Cloud configuration.

Switch through environment variables only.

Verify that the same application can send traces either to:

- local self-hosted Langfuse
- Langfuse Cloud

Do not duplicate instrumentation code.

---

## Milestone 20 — Production observability architecture

Document how the educational system would evolve in production.

Discuss:

- Langfuse
- API metrics
- logs
- distributed tracing
- OpenTelemetry
- Prometheus/Grafana or cloud APM
- alerting
- trace sampling
- data retention
- PII
- secrets
- scaling
- high availability
- asynchronous ingestion
- multi-region considerations

Do not necessarily implement all of this infrastructure.

The goal is architectural understanding.

---

## Milestone 21 — Final experiment suite

Create a representative experiment matrix.

Compare combinations such as:

```text id="601aa7"
Prompt v1 + Model A
Prompt v2 + Model A
Prompt v2 + Model B
Prompt v2 + Model B + improved tool descriptions
```

Report:

- deterministic score
- LLM judge score
- human feedback where available
- tool accuracy
- groundedness
- latency
- cost

Produce a final engineering analysis:

> Which configuration should we deploy, and why?

---

# Final project questions

By completing this project I should be able to answer:

1. What exactly is an LLM trace?
2. What is the difference between a trace, span and generation?
3. How should an Agentic AI trajectory be instrumented?
4. How are sessions represented?
5. How can user interactions be correlated?
6. How are tool calls monitored?
7. How do I inspect token usage?
8. How do I inspect LLM cost?
9. How do I locate latency bottlenecks?
10. How do I identify failed agent trajectories?
11. How can prompts be versioned?
12. How do I compare two prompts empirically?
13. What is a Langfuse dataset?
14. What is a Langfuse experiment?
15. How do I perform offline evaluation?
16. How do I use LLM-as-judge?
17. What are its methodological weaknesses?
18. How can user feedback become evaluation data?
19. How do I evaluate tool selection?
20. How do I evaluate agent trajectories?
21. How can I detect hallucination?
22. How can I detect regressions?
23. How can evaluation become part of CI?
24. How do I compare quality, latency and cost?
25. What happens if Langfuse becomes unavailable?
26. What data should I avoid sending to an observability platform?
27. What belongs in Langfuse versus Prometheus/APM/logging?
28. How would this architecture change at production scale?
29. How do I use observability to actually improve an Agentic AI system?
30. How do I know whether a new agent version is truly better?

---

# Your first task

DO NOT implement all milestones now.

Start with **Milestone 0 only**.

Before writing code:

1. Inspect the current repository if one already exists.
2. Summarize what is present.
3. Propose the architecture.
4. Explain whether you recommend LangGraph or transparent Python orchestration and why.
5. Explain the recommended UI technology and why.
6. Explain the LLM provider architecture.
7. Explain the Langfuse local deployment architecture.
8. Explain how local Langfuse and Langfuse Cloud will coexist through configuration.
9. Propose the repository structure.
10. Propose the initial Makefile targets.
11. Identify the first ADRs worth creating.
12. Identify assumptions you are making.

Then implement **Milestone 0 only**.

After implementation:

1. Summarize every file created or modified.
2. Explain the architecture again using the actual implementation.
3. Show the commands I should run using `make`.
4. Run or explain the relevant tests.
5. Identify anything that remains deliberately unimplemented.
6. Explain what we will learn in Milestone 1.
7. STOP.

Do not automatically continue to Milestone 1.

Wait for me to review the implementation and ask questions before proceeding.