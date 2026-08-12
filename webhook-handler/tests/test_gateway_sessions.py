"""Session policy: which Open WebUI chat a conversation writes to, and how a
turn is appended so the sidebar renders it.

Open WebUI's frontend keeps BOTH a flat `messages` list and a `history` map
keyed by message id with `currentId` on the newest leaf. Writing only one of
them produces a chat that exists but shows nothing.
"""
from unittest.mock import AsyncMock

import pytest

from gateway.sessions import (append_turn, get_or_create_chat, history_messages,
                              title_from)


def test_title_is_a_short_single_line():
    assert title_from("hello there") == "hello there"
    long = "word " * 40
    assert len(title_from(long)) <= 60
    assert "\n" not in title_from("first line\nsecond line")


def test_title_falls_back_when_there_is_no_text():
    assert title_from("") == "New chat"
    assert title_from("   ") == "New chat"


def test_history_messages_keeps_only_role_and_content():
    chat = {"messages": [
        {"role": "user", "content": "hi", "id": "1", "timestamp": 1},
        {"role": "assistant", "content": "hello", "id": "2", "done": True},
    ]}
    assert history_messages(chat) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_history_messages_is_capped_to_the_most_recent():
    chat = {"messages": [{"role": "user", "content": str(i)} for i in range(50)]}
    out = history_messages(chat, limit=6)
    assert len(out) == 6
    assert out[-1]["content"] == "49"


def test_history_messages_skips_empty_and_malformed_entries():
    chat = {"messages": [
        {"role": "user", "content": ""},
        {"role": "user"},
        "not a dict",
        {"role": "assistant", "content": "kept"},
    ]}
    assert history_messages(chat) == [{"role": "assistant", "content": "kept"}]


def test_append_turn_writes_both_messages_and_history():
    chat = {"title": "t", "messages": [], "history": {"messages": {}, "currentId": None}}
    out = append_turn(chat, "hi", "hello", "auto_router.auto")

    assert [m["role"] for m in out["messages"]] == ["user", "assistant"]
    assert len(out["history"]["messages"]) == 2
    newest = out["history"]["currentId"]
    assert out["history"]["messages"][newest]["role"] == "assistant"


def test_append_turn_links_the_new_turn_to_the_previous_one():
    chat = {"title": "t", "messages": [], "history": {"messages": {}, "currentId": None}}
    first = append_turn(chat, "one", "1", "m")
    second = append_turn(first, "two", "2", "m")

    prev_leaf = first["history"]["currentId"]
    new_user = second["messages"][2]
    assert new_user["parentId"] == prev_leaf
    assert new_user["id"] in second["history"]["messages"][prev_leaf]["childrenIds"]


def test_append_turn_does_not_mutate_the_input():
    chat = {"title": "t", "messages": [], "history": {"messages": {}, "currentId": None}}
    append_turn(chat, "hi", "hello", "m")
    assert chat["messages"] == []


async def test_get_or_create_reuses_an_existing_mapping():
    tasks = AsyncMock()
    tasks.gateway_get_session.return_value = {"owui_chat_id": "chat-1",
                                               "owui_user_id": "u1"}
    owui = AsyncMock()
    owui.get_chat.return_value = {"title": "old", "messages": [{"role": "user",
                                                                "content": "hi"}]}

    chat_id, chat = await get_or_create_chat(
        tasks, owui, "telegram", "42", "u1", "next message", "m")

    assert chat_id == "chat-1"
    assert chat["messages"]
    owui.create_chat.assert_not_called()
    tasks.gateway_put_session.assert_not_called()


async def test_get_or_create_makes_a_chat_and_stores_the_mapping():
    tasks = AsyncMock()
    tasks.gateway_get_session.return_value = None
    owui = AsyncMock()
    owui.create_chat.return_value = "chat-new"
    owui.get_chat.return_value = {"title": "Hello", "messages": []}

    chat_id, chat = await get_or_create_chat(
        tasks, owui, "telegram", "42", "u1", "Hello there", "m")

    assert chat_id == "chat-new"
    owui.create_chat.assert_awaited_once()
    tasks.gateway_put_session.assert_awaited_once_with(
        "telegram", "42", "chat-new", "u1")


async def test_a_mapping_pointing_at_a_deleted_chat_recovers():
    # The user deleted the chat in the browser. The next message must not 404
    # forever; it must make a new one and re-point the mapping.
    from gateway.owui import OWUIError

    tasks = AsyncMock()
    tasks.gateway_get_session.return_value = {"owui_chat_id": "chat-gone",
                                               "owui_user_id": "u1"}
    owui = AsyncMock()
    owui.get_chat.side_effect = [OWUIError(404, "not found"), {"title": "t",
                                                               "messages": []}]
    owui.create_chat.return_value = "chat-fresh"

    chat_id, _ = await get_or_create_chat(
        tasks, owui, "telegram", "42", "u1", "hi", "m")

    assert chat_id == "chat-fresh"
    tasks.gateway_put_session.assert_awaited_once_with(
        "telegram", "42", "chat-fresh", "u1")


async def test_a_mapping_that_401s_recovers_the_same_as_a_404():
    # Upstream Open WebUI's get_chat_by_id_and_user_id raises 401, not 404,
    # whenever the chat is absent OR belongs to someone else. Before this fix
    # the recovery branch only caught 404 and re-raised 401, so this exact
    # scenario (a deleted chat) wedged the conversation on MODEL_DOWN forever.
    from gateway.owui import OWUIError

    tasks = AsyncMock()
    tasks.gateway_get_session.return_value = {"owui_chat_id": "chat-gone",
                                               "owui_user_id": "u1"}
    owui = AsyncMock()
    owui.get_chat.side_effect = [OWUIError(401, "unauthorized"), {"title": "t",
                                                                  "messages": []}]
    owui.create_chat.return_value = "chat-fresh"

    chat_id, _ = await get_or_create_chat(
        tasks, owui, "telegram", "42", "u1", "hi", "m")

    assert chat_id == "chat-fresh"
    tasks.gateway_put_session.assert_awaited_once_with(
        "telegram", "42", "chat-fresh", "u1")


async def test_a_mapping_that_500s_still_raises():
    # Only 401/404 mean "gone". Anything else is a real failure and must
    # surface, not be silently swallowed into "start a new chat".
    from gateway.owui import OWUIError

    tasks = AsyncMock()
    tasks.gateway_get_session.return_value = {"owui_chat_id": "chat-1",
                                               "owui_user_id": "u1"}
    owui = AsyncMock()
    owui.get_chat.side_effect = OWUIError(500, "boom")

    with pytest.raises(OWUIError):
        await get_or_create_chat(tasks, owui, "telegram", "42", "u1", "hi", "m")


async def test_a_mismatched_owner_starts_a_fresh_chat_instead_of_reading_it():
    # A re-paired platform account: the stored session still points at user
    # A's chat, but the current caller resolves to user B. Reading B's turn
    # against A's chat would be a cross-user read, so this must not even try
    # owui.get_chat on the stored id.
    tasks = AsyncMock()
    tasks.gateway_get_session.return_value = {"owui_chat_id": "chat-of-a",
                                               "owui_user_id": "user-a"}
    owui = AsyncMock()
    owui.create_chat.return_value = "chat-for-b"
    owui.get_chat.return_value = {"title": "t", "messages": []}

    chat_id, _ = await get_or_create_chat(
        tasks, owui, "telegram", "42", "user-b", "hi", "m")

    assert chat_id == "chat-for-b"
    owui.get_chat.assert_awaited_once_with("chat-for-b")
    tasks.gateway_put_session.assert_awaited_once_with(
        "telegram", "42", "chat-for-b", "user-b")


def test_the_flat_list_and_the_history_map_agree_after_two_turns():
    # Open WebUI keeps childrenIds on both structures: real chats there carry it
    # on n-1 of n flat entries. Updating only the map left every earlier turn's
    # flat entry stale forever.
    chat = {"title": "t", "messages": [], "history": {"messages": {}, "currentId": None}}
    first = append_turn(chat, "one", "1", "m")
    second = append_turn(first, "two", "2", "m")

    for message in second["messages"]:
        in_history = second["history"]["messages"][message["id"]]
        assert message["childrenIds"] == in_history["childrenIds"], message["id"]
        assert message["parentId"] == in_history["parentId"], message["id"]


def test_append_turn_shares_no_message_object_with_its_input():
    # The caller may still need the original if the write fails, so an edit to
    # the returned object must not reach back into theirs.
    chat = {"title": "t", "messages": [], "history": {"messages": {}, "currentId": None}}
    first = append_turn(chat, "one", "1", "m")
    second = append_turn(first, "two", "2", "m")

    assert second["messages"][0] is not first["messages"][0]
    first_id = first["messages"][0]["id"]
    assert second["history"]["messages"][first_id] is not first["history"]["messages"][first_id]

    second["messages"][0]["content"] = "edited"
    assert first["messages"][0]["content"] == "one"
