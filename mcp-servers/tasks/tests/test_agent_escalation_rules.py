"""Which requests a free agent does badly enough to move to the paid model.
Keyword rules on what the person typed, pinned case by case."""
import pytest

import agent_escalation as esc


@pytest.fixture(autouse=True)
def _limits(monkeypatch):
    monkeypatch.setattr(esc, "MESSAGE_CHARS", 2000)
    monkeypatch.setattr(esc, "CONVERSATION_CHARS", 60000)


@pytest.mark.parametrize("text,reason", [
    ("build me a todo app with a login page", esc.REASON_BUILD),
    ("Can you create a landing page for my shoe store?", esc.REASON_BUILD),
    ("make a dashboard of my sales", esc.REASON_BUILD),
    ("refactor the checkout code", esc.REASON_CODE),
    ("please debug the signup flow", esc.REASON_CODE),
    ("write a script that renames my files", esc.REASON_CODE),
    ("fix the bug on the pricing page", esc.REASON_CODE),
    ("add a feature to export as CSV", esc.REASON_CODE),
    ("open it in App Builder", esc.REASON_CODE),
    ("change the code so the button is red", esc.REASON_CODE),
    ("please change the checkout code", esc.REASON_CODE),
    ("modify the function that sends emails", esc.REASON_CODE),
    ("rewrite this function", esc.REASON_CODE),
    ("edit the css on my site", esc.REASON_CODE),
    ("update the html of the contact form", esc.REASON_CODE),
    ("change the signup component so it asks for a phone number", esc.REASON_CODE),
    ("here:\n```js\nconst x = 1\n```", esc.REASON_CODE),
    ("I get TypeError: Cannot read properties of undefined", esc.REASON_ERROR),
    ("Traceback (most recent call last):\n  File \"a.py\"", esc.REASON_ERROR),
    ("it crashed\n    at Object.<anonymous> (/app/x.js:10:5)", esc.REASON_ERROR),
])
def test_work_the_free_model_does_badly_moves_to_paid(text, reason):
    assert esc.rule_reason(text) == reason


@pytest.mark.parametrize("text", [
    "what is my schedule meeting on calendar tomorrow?",
    "hi team",
    "make sure the site is up",
    "set up a meeting with Ralph on Friday",
    "create a schedule that emails me every morning",
    "make it blue",
    "yes, go ahead",
    "change my yoga class to Friday",
    "update me on the launch plan",
    "edit the meeting invite so it starts at 3",
    "change the meeting to 3pm and send the notes, then share the code",
    "",
    None,
])
def test_ordinary_requests_stay_free(text):
    assert esc.rule_reason(text) is None


def test_a_very_long_message_moves_to_paid():
    assert esc.rule_reason("a" * 2001) == esc.REASON_LONG_MESSAGE
    assert esc.rule_reason("a" * 2000) is None


@pytest.mark.parametrize("text,plain", [
    ("what is on my calendar tomorrow?", True),
    ("Who emailed me today", True),
    ("why did the build fail?", False),
    ("is the page live yet?", False),
    ("can you make it blue?", False),
    ("make it blue", False),
    ("yes go ahead", False),
    ("", False),
])
def test_a_plain_question_is_one_about_something_else(text, plain):
    assert esc.is_plain_question(text) is plain


@pytest.mark.parametrize("content,passed", [
    ("PASS", True), (" pass. ", True), ('"PASS"', True),
    ("PASS\n\nI checked the files", False), ("", False), (None, False),
])
def test_pass_shapes(content, passed):
    assert esc.looks_like_pass(content) is passed


def test_heavy_tools_are_the_app_change_tools_and_junk_is_not():
    call = lambda n: {"function": {"name": n}}  # noqa: E731
    assert esc.names_heavy_tool([call("read_app_file"), call("propose_app_change")])
    assert esc.names_heavy_tool([call(" apply_app_change ")])
    assert not esc.names_heavy_tool([call("list_my_apps")])
    assert not esc.names_heavy_tool([None, {"function": "x"}, {"function": {"name": 3}}])
    assert not esc.names_heavy_tool("nope")


def test_conversation_size_counts_text_parts_and_ignores_junk(monkeypatch):
    monkeypatch.setattr(esc, "CONVERSATION_CHARS", 10)
    msgs = [{"role": "user", "content": "12345"},
            {"role": "user", "content": [{"type": "text", "text": "123456"}]},
            {"role": "tool", "content": None}, "junk"]
    assert esc.conversation_chars(msgs) == 11
    assert esc.too_long(msgs)
