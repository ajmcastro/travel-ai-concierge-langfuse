"""Travel AI Concierge — Chat UI (Milestone 3).

Talks to the FastAPI backend exclusively over HTTP (`Settings.api_base_url`)
— it never imports agent/provider code directly. API and UI are separate
processes that can be started, restarted, and scaled independently; this
file only enforces that in code by refusing to reach around the HTTP
boundary, not by living in a separate package.

Run with:
    make ui                              # or:
    uv run streamlit run ui/streamlit_app.py
"""

import time
import uuid

import httpx2
import streamlit as st

from travel_ai_concierge.config import get_settings
from travel_ai_concierge.observability import get_langfuse_client

settings = get_settings()

st.set_page_config(page_title="Travel AI Concierge", page_icon="🧳")


def _new_session_id() -> str:
    return f"session-{uuid.uuid4().hex[:12]}"


def _new_user_id() -> str:
    # A stable synthetic identity for this browser session — not a fresh one
    # per message. Langfuse's user_id exists to aggregate behavior/cost for
    # the *same* identity over time; a new ID per request would defeat that
    # (see docs/RATIONALE_PER_MILESTONE.md, Milestone 2).
    return f"anon-{uuid.uuid4().hex[:8]}"


if "session_id" not in st.session_state:
    st.session_state.session_id = _new_session_id()
if "user_id" not in st.session_state:
    st.session_state.user_id = _new_user_id()
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.header("Travel AI Concierge")

    if st.button("New conversation"):
        st.session_state.session_id = _new_session_id()
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.subheader("Debug")
    st.text(f"Session ID: {st.session_state.session_id}")
    st.text(f"User ID: {st.session_state.user_id}")

    last_assistant = next(
        (m for m in reversed(st.session_state.messages) if m["role"] == "assistant"), None
    )
    if last_assistant:
        st.text(f"Model: {last_assistant.get('model', '—')}")
        st.text(f"Latency (client-measured): {last_assistant.get('latency_ms', '—')} ms")
        trace_id = last_assistant.get("trace_id")
        if trace_id:
            # get_trace_url() makes a real network call (project_id lookup,
            # cached after the first success — see docs/EXPERIMENTS.md,
            # Milestone 3) and raises if it can't resolve — unreachable host
            # (httpx2.ConnectError), wrong keys (langfuse's own
            # UnauthorizedError), a timeout, etc. The chat response itself
            # already succeeded without Langfuse (span creation is
            # local-only), so this is a non-critical debug convenience
            # failing, not the app itself — catch broadly rather than
            # enumerate every SDK exception type, and degrade to a caption
            # instead of a traceback (see ADR-004: observability must not
            # become a hard runtime dependency).
            try:
                trace_url = get_langfuse_client().get_trace_url(trace_id=trace_id)
                st.markdown(f"[View trace in Langfuse]({trace_url})")
            except Exception:
                st.caption(
                    "Trace link unavailable — is Langfuse running and configured "
                    "correctly? (`make langfuse-up`)"
                )
        else:
            st.caption("No trace ID — set DEBUG=true in .env to see one.")

    st.divider()
    st.caption(
        "Each message is sent as a single, stateless request — the LLM does not "
        "yet see earlier turns in this conversation (that starts in Milestone 7). "
        "The session_id above only groups these turns together in Langfuse."
    )

for i, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message["role"] == "assistant":
            feedback = st.feedback("thumbs", key=f"feedback-{i}")
            if feedback is not None:
                st.toast("Thanks for the feedback! (not yet sent to Langfuse — see Milestone 12)")

if prompt := st.chat_input("Plan your next trip..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"), st.spinner("Thinking..."):
        try:
            t0 = time.monotonic()
            response = httpx2.post(
                f"{settings.api_base_url}/chat",
                json={
                    "message": prompt,
                    "session_id": st.session_state.session_id,
                    "user_id": st.session_state.user_id,
                },
                timeout=30.0,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            response.raise_for_status()
        except httpx2.ConnectError:
            st.error(
                f"Could not reach the API at {settings.api_base_url}. Is `make serve` running?"
            )
        except httpx2.HTTPStatusError as exc:
            st.error(f"API returned {exc.response.status_code}: {exc.response.text}")
        else:
            body = response.json()
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": body["message"],
                    "trace_id": body.get("trace_id"),
                    "model": body.get("metadata", {}).get("model"),
                    "latency_ms": latency_ms,
                }
            )
            # The sidebar debug panel is rendered earlier in this same
            # top-to-bottom script pass, so it already drew using the
            # session_state from *before* this message was appended — without
            # a rerun it would show the previous exchange's trace, one
            # interaction behind. Streamlit reruns from the top on request;
            # it does not re-invoke st.chat_input, so this does not resend.
            st.rerun()
