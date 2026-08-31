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


# --- Milestone 12: turn_id / find_turn ---


def test_turn_id_is_auto_generated_and_unique():
    a = Turn(user_message="a", assistant_message="A", trace_id=None)
    b = Turn(user_message="b", assistant_message="B", trace_id=None)
    assert a.turn_id
    assert a.turn_id != b.turn_id


async def test_find_turn_returns_the_matching_turn():
    store = ConversationStore()
    turn = Turn(user_message="hi", assistant_message="hello", trace_id="t1")
    await store.append_turn("s1", turn, max_turns=10)

    found = await store.find_turn("s1", turn.turn_id)

    assert found is not None
    assert found.trace_id == "t1"


async def test_find_turn_returns_none_for_unknown_id():
    store = ConversationStore()
    await store.append_turn(
        "s1", Turn(user_message="a", assistant_message="A", trace_id=None), max_turns=10
    )

    assert await store.find_turn("s1", "no-such-id") is None


async def test_find_turn_returns_none_for_unknown_session():
    store = ConversationStore()
    assert await store.find_turn("nobody-here", "any-id") is None


async def test_find_turn_returns_none_once_trimmed_out():
    store = ConversationStore()
    first = Turn(user_message="a", assistant_message="A", trace_id=None)
    await store.append_turn("s1", first, max_turns=1)
    await store.append_turn(
        "s1", Turn(user_message="b", assistant_message="B", trace_id=None), max_turns=1
    )

    assert await store.find_turn("s1", first.turn_id) is None
