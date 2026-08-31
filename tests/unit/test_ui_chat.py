"""Tests for ui/streamlit_app.py, using Streamlit's own AppTest harness.

AppTest runs the real script in a simulated Streamlit runtime — it's the
first-party way to test a Streamlit app; there is no meaningful way to unit
test one by importing it as a plain module. The HTTP call to the API is
monkeypatched at the `httpx2.post` level so these stay offline (no running
server, no Langfuse) — consistent with the rest of this project's tests.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).resolve().parents[2] / "ui" / "streamlit_app.py")


def _fake_chat_response(
    message: str, trace_id: str | None = "abc123", message_id: str = "turn-abc123"
) -> SimpleNamespace:
    def raise_for_status() -> None:
        return None

    return SimpleNamespace(
        status_code=200,
        raise_for_status=raise_for_status,
        json=lambda: {
            "session_id": "session-test",
            "message": message,
            "trace_id": trace_id,
            "message_id": message_id,
            "metadata": {"model": "mock-echo-v1"},
        },
    )


def _fake_feedback_response() -> SimpleNamespace:
    return SimpleNamespace(
        status_code=201, raise_for_status=lambda: None, json=lambda: {"recorded": True}
    )


def _routed_post(feedback_calls: list[dict]):
    # Milestone 12: httpx2.post is called for both /chat and /feedback —
    # route on the URL so a single monkeypatch can serve both, and record
    # every /feedback call's JSON body for assertions.
    def _post(url: str, json: dict, **kwargs: object) -> SimpleNamespace:
        if url.endswith("/feedback"):
            feedback_calls.append(json)
            return _fake_feedback_response()
        return _fake_chat_response("[mock] I heard: " + json["message"])

    return _post


def test_app_runs_without_error():
    at = AppTest.from_file(APP_PATH).run()
    assert not at.exception


def test_sidebar_shows_session_and_user_id():
    at = AppTest.from_file(APP_PATH).run()
    sidebar_text = " ".join(t.value for t in at.sidebar.text)
    assert "Session ID: session-" in sidebar_text
    assert "User ID: anon-" in sidebar_text


def test_sending_a_message_renders_response(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("httpx2.post", lambda *a, **k: _fake_chat_response("[mock] I heard: hello"))

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()

    assert not at.exception
    messages = [m.markdown[0].value for m in at.chat_message]
    assert "hello" in messages
    assert "[mock] I heard: hello" in messages


def test_new_conversation_clears_history(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("httpx2.post", lambda *a, **k: _fake_chat_response("hi there"))

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()
    assert len(at.chat_message) == 2

    first_session_id = at.session_state["session_id"]
    at.sidebar.button[0].click().run()

    assert at.session_state["messages"] == []
    assert at.session_state["session_id"] != first_session_id


def test_connect_error_shown_cleanly(monkeypatch: pytest.MonkeyPatch):
    import httpx2

    def _raise(*args: object, **kwargs: object) -> None:
        raise httpx2.ConnectError("connection refused")

    monkeypatch.setattr("httpx2.post", _raise)

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()

    assert not at.exception
    assert any("Could not reach the API" in e.value for e in at.error)


def test_debug_panel_shows_trace_link_when_present(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "httpx2.post", lambda *a, **k: _fake_chat_response("hi", trace_id="deadbeef")
    )
    monkeypatch.setattr(
        "travel_ai_concierge.observability.get_langfuse_client",
        lambda: SimpleNamespace(get_trace_url=lambda trace_id: f"http://example/{trace_id}"),
    )

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()

    sidebar_markdown = " ".join(m.value for m in at.sidebar.markdown)
    assert "http://example/deadbeef" in sidebar_markdown


def test_debug_panel_degrades_cleanly_when_langfuse_unreachable(monkeypatch: pytest.MonkeyPatch):
    # Regression test: get_trace_url() raising (unreachable host, wrong
    # credentials, timeout — see the broad `except Exception` in
    # streamlit_app.py) must not crash the sidebar with a raw traceback.
    # Caught live in a browser before this test existed — see
    # docs/EXPERIMENTS.md, Milestone 3.
    monkeypatch.setattr(
        "httpx2.post", lambda *a, **k: _fake_chat_response("hi", trace_id="deadbeef")
    )

    def _raise_unreachable(trace_id: str) -> str:
        raise ConnectionError("connection refused")

    monkeypatch.setattr(
        "travel_ai_concierge.observability.get_langfuse_client",
        lambda: SimpleNamespace(get_trace_url=_raise_unreachable),
    )

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()

    assert not at.exception
    sidebar_captions = " ".join(c.value for c in at.sidebar.caption)
    assert "Trace link unavailable" in sidebar_captions


def test_thumbs_up_posts_feedback_with_the_returned_message_id(monkeypatch: pytest.MonkeyPatch):
    feedback_calls: list[dict] = []
    monkeypatch.setattr("httpx2.post", _routed_post(feedback_calls))

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()
    at.feedback[0].set_value(1).run()

    assert not at.exception
    assert len(feedback_calls) == 1
    assert feedback_calls[0]["message_id"] == "turn-abc123"
    assert feedback_calls[0]["thumbs_up"] is True
    assert feedback_calls[0]["comment"] is None


def test_thumbs_down_sends_thumbs_up_false(monkeypatch: pytest.MonkeyPatch):
    feedback_calls: list[dict] = []
    monkeypatch.setattr("httpx2.post", _routed_post(feedback_calls))

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()
    at.feedback[0].set_value(0).run()

    assert feedback_calls[0]["thumbs_up"] is False


def test_feedback_is_not_resubmitted_on_a_later_unrelated_rerun(monkeypatch: pytest.MonkeyPatch):
    # st.feedback is stateful — it returns the same selection on every rerun
    # after the click, not just the click's own rerun. Regression test for
    # exactly that: a second, unrelated rerun (here, another chat message)
    # must not resend the same feedback.
    feedback_calls: list[dict] = []
    monkeypatch.setattr("httpx2.post", _routed_post(feedback_calls))

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()
    at.feedback[0].set_value(1).run()
    assert len(feedback_calls) == 1

    at.chat_input[0].set_value("another message").run()

    assert len(feedback_calls) == 1


def test_optional_comment_sent_after_feedback_reuses_the_recorded_rating(
    monkeypatch: pytest.MonkeyPatch,
):
    feedback_calls: list[dict] = []
    monkeypatch.setattr("httpx2.post", _routed_post(feedback_calls))

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()
    at.feedback[0].set_value(1).run()
    assert len(feedback_calls) == 1

    at.text_input[0].set_value("loved the detail").run()
    send_comment_button = next(b for b in at.button if b.label == "Send comment")
    send_comment_button.click().run()

    assert not at.exception
    assert len(feedback_calls) == 2
    assert feedback_calls[1]["comment"] == "loved the detail"
    assert feedback_calls[1]["thumbs_up"] is True
    # Regression guard: a successful "Send comment" click must trigger its
    # own st.rerun() so the form disappears on the very next render, not
    # only once some later, unrelated interaction happens to rerun the
    # script (see docs/EXPERIMENTS.md, Milestone 12 follow-up).
    assert len(at.text_input) == 0


def test_no_feedback_widget_without_a_message_id(monkeypatch: pytest.MonkeyPatch):
    # A response with no message_id (e.g. an older/mismatched API) shouldn't
    # render a feedback widget with nothing to attach it to.
    monkeypatch.setattr(
        "httpx2.post",
        lambda *a, **k: _fake_chat_response("hi", message_id=None),  # type: ignore[arg-type]
    )

    at = AppTest.from_file(APP_PATH).run()
    at.chat_input[0].set_value("hello").run()

    assert not at.exception
    assert len(at.feedback) == 0
