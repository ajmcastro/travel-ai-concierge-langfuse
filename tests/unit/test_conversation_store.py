"""Tests for the Milestone 7 in-memory conversation store."""

from travel_ai_concierge.conversation import ConversationStore, Turn


async def test_unknown_session_has_empty_history():
    store = ConversationStore()
    assert await store.get_history("nobody-here") == []


async def test_append_turn_is_visible_in_history():
    store = ConversationStore()
    await store.append_turn(
        "s1", Turn(user_message="hi", assistant_message="hello", trace_id="t1"), max_turns=10
    )

    history = await store.get_history("s1")
    assert len(history) == 1
    assert history[0].user_message == "hi"
    assert history[0].assistant_message == "hello"
    assert history[0].trace_id == "t1"


async def test_sessions_are_isolated():
    store = ConversationStore()
    await store.append_turn(
        "s1", Turn(user_message="a", assistant_message="A", trace_id=None), max_turns=10
    )
    await store.append_turn(
        "s2", Turn(user_message="b", assistant_message="B", trace_id=None), max_turns=10
    )

    assert [t.user_message for t in await store.get_history("s1")] == ["a"]
    assert [t.user_message for t in await store.get_history("s2")] == ["b"]


async def test_history_trims_to_max_turns():
    store = ConversationStore()
    for i in range(5):
        await store.append_turn(
            "s1",
            Turn(user_message=f"msg-{i}", assistant_message=f"reply-{i}", trace_id=None),
            max_turns=3,
        )

    history = await store.get_history("s1")
    # Only the 3 most recent turns survive — oldest dropped first.
    assert [t.user_message for t in history] == ["msg-2", "msg-3", "msg-4"]


async def test_get_history_returns_a_copy():
    # Callers mutating the returned list must not corrupt the store's own state.
    store = ConversationStore()
    await store.append_turn(
        "s1", Turn(user_message="a", assistant_message="A", trace_id=None), max_turns=10
    )

    history = await store.get_history("s1")
    history.append(Turn(user_message="tampered", assistant_message="", trace_id=None))

    assert len(await store.get_history("s1")) == 1
