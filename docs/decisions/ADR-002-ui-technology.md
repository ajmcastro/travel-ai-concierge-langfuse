# ADR-002: Chat UI Technology

**Date:** 2026-08-28  
**Status:** Accepted

## Context

The project needs a user-facing chat interface to demonstrate multi-turn conversations, show agent responses, and optionally display observability metadata (session ID, trace ID, latency, tool calls). The UI is **not** the primary learning objective — the agent and Langfuse integration are.

## Options

### Option A — Streamlit

Pure-Python UI framework. Chat components available via `st.chat_message`/`st.chat_input`. Session state via `st.session_state`.

**Pros:** No Node.js. No build step. Fast to write. Easy sidebar debug panel. Used widely in the ML/AI community.  
**Cons:** Limited real-time streaming support. Not a production-grade web framework.

### Option B — Gradio

Similar to Streamlit. Good defaults for chatbot UIs.

**Pros:** Less boilerplate for a simple chat interface.  
**Cons:** Less flexibility for a debug panel showing trace IDs. Similar limitations to Streamlit.

### Option C — React / Next.js

Full frontend framework.

**Pros:** Production-quality. Real streaming support. Fully customisable.  
**Cons:** Requires Node.js, a build step, and frontend development skills. Adds project complexity that distracts from the Langfuse learning objectives.

## Decision

**Streamlit (Option A)**

The UI is a learning vehicle, not the deliverable. Streamlit lets us build a functional multi-turn chat with a debug sidebar in under 200 lines of Python. When the primary learning objective becomes the UI (it never does in this project), we can replace it.

## Consequences

- `streamlit` is added as a dependency in Milestone 3.
- The sidebar will show: session ID, trace ID, model, latency, and a link to the Langfuse trace in development mode.
- Streaming LLM responses require workarounds in Streamlit; we will implement basic streaming when needed but it is not a Milestone 3 blocker.
