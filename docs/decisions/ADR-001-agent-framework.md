# ADR-001: Agent Orchestration Framework

**Date:** 2026-08-28  
**Status:** Accepted

## Context

The Travel AI Concierge must orchestrate multi-step, conditional agent workflows: understand user intent, optionally ask clarifying questions, select and call one or more tools, reason over results, and generate a final response. We need a framework that makes this flow explicit and observable.

Three options were evaluated.

## Options

### Option A — Transparent Python

Write the agent loop as plain Python: a function that calls the LLM, inspects the response, executes tools in a `while` loop, and recurses or returns.

**Pros:** Zero dependencies. Fully understood. Easy to instrument manually.  
**Cons:** Conditional routing (clarify vs. proceed) quickly becomes a hand-rolled state machine. Error handling, retries, and cycle detection require bespoke code. The routing logic is buried in control flow rather than declared in a structure that maps to observability.

### Option B — LangGraph

A graph-based orchestration library from LangChain Inc. You define a typed `StateGraph`: nodes are Python functions, edges are deterministic or conditional transitions. The state is an explicit Pydantic-compatible dict that every node reads and writes.

**Pros:**  
- Explicit graph topology — you can read the graph definition and immediately understand agent flow.
- Typed `AgentState` — every transition is visible; no hidden mutable variables.
- Each node maps naturally to a Langfuse span: enter the node → open span, exit → close span.
- Built-in tool execution, cycle detection, and `interrupt_before`/`interrupt_after` for human-in-the-loop.
- Conditional edges make clarification logic first-class.
- Does not require LangChain abstractions for tools or LLMs.

**Cons:** Adds a dependency. Requires learning the LangGraph mental model before the first agent works.

### Option C — CrewAI / AutoGen / similar

Role-based multi-agent frameworks.

**Cons:** Introduces role decomposition complexity we do not need. The "crew" mental model obscures the single-agent workflow we want to observe and evaluate. Poor fit for this project's learning objectives.

## Decision

**LangGraph (Option B)**

The key reason is observability alignment: the graph topology is the observability model. Each node is a named, observable step. Conditional edges are visible routing decisions. This maps directly onto the trace structure we want in Langfuse:

```
travel_concierge_turn (trace)
├── understand_request (span / node)
├── clarify_or_proceed (conditional edge → routing decision)
├── select_tools (span / node)
├── execute_tools (span / node)
│   ├── search_destinations (tool)
│   └── search_hotels (tool)
└── generate_response (span / node)
```

> Updated post-Milestone 4: the tools ended up using Langfuse's first-class `tool` observation type rather than a `tool.`-prefixed span name — a real distinct type, not just a naming convention (see [RATIONALE_PER_MILESTONE.md](../RATIONALE_PER_MILESTONE.md#milestone-4--synthetic-travel-tools)). The diagram above reflects that; it was written before that detail was known.

We will NOT use prebuilt LangGraph agents. Every node is a named Python function we write. The graph is declared explicitly and documented.

## Consequences

- `langgraph` is added as a dependency in Milestone 5.
- Tool functions are plain Python; LangGraph only provides the execution graph.
- Langfuse spans are opened/closed at node boundaries (not inside the LangGraph internals).
- If LangGraph introduces behaviour that makes Langfuse instrumentation difficult, we reassess.
