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
    # Kept or gained while the rules were tightened, 2026-09-18.
    ("build a website for my bakery", esc.REASON_BUILD),
    ("create a web app that tracks my workouts", esc.REASON_BUILD),
    ("set up a backend with an API for my orders", esc.REASON_BUILD),
    ("create a chrome extension that blocks ads", esc.REASON_BUILD),
    ("build an online store for my candles", esc.REASON_BUILD),
    ("make a simple snake game", esc.REASON_BUILD),
    ("create a discord bot that posts the weather", esc.REASON_BUILD),
    ("fix the login issue in the app", esc.REASON_CODE),
    ("fix the issue where the page crashes on submit", esc.REASON_CODE),
    ("implement dark mode on the settings page", esc.REASON_CODE),
    ("generate a python script to parse this csv", esc.REASON_CODE),
    ("write a program that sorts my contacts", esc.REASON_CODE),
    # Not a bar code, and an analytics snippet is code.
    ("change the navbar code so the menu collapses", esc.REASON_CODE),
    ("update the tracking code on my site", esc.REASON_CODE),
    ("the deploy fails with ModuleNotFoundError: No module named 'httpx'",
     esc.REASON_ERROR),
    ("typeerror: x is not a function", esc.REASON_ERROR),
    ("Error: ENOENT: no such file or directory, open '/app/data.json'",
     esc.REASON_ERROR),
    ("main.c:3:5: error: expected ';' before 'return'", esc.REASON_ERROR),
    ("java.lang.NullPointerException\n\tat com.foo.Bar.run(Bar.java:12)",
     esc.REASON_ERROR),
    ("GET /api/orders returns 500 Internal Server Error", esc.REASON_ERROR),
    ("the checkout page shows 502 on /api/pay", esc.REASON_ERROR),
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
    # Each of these went to the paid model before review, 2026-09-18: a
    # store, a game, an API key or an event is not software being built, a
    # zip code is not code, an issue with an invite is not a bug, and the
    # word error in a sentence is not a stack trace.
    "set up a meeting with the store manager tomorrow",
    "make dinner plans after the game on Friday",
    "create an API key for stripe",
    "create a calendar event for the site visit",
    "update the zip code on my shipping address",
    "fix the issue with my calendar invite",
    "Reply to Tom: there was an error: the invoice is wrong",
    # Found by running the rules over everyday messages the same day.
    "update my discount code on the order to WINTER10",
    "update the door code for the office",
    "fix the error in my expense report",
    "fix the typo on page 3 of the contract",
    "Error: payment declined on my card, remind me to call the bank",
    "One exception: the store is closed on Monday",
    "make the game on Friday a priority on my calendar",
    "set up my account on the benefits portal",
    "create a job application for the receptionist role",
    "implement the new expense policy starting Monday",
    "write a program for the charity gala",
    "edit the script for my youtube video",
    "add a feature story to the newsletter",
    "create a new event: team lunch at noon",
    "set up a weekly standup every Monday at 10",
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


SMART_FOOTER = "\n\n*Auto (Smart): routed to the paid general model `gpt-5.5`.*"


@pytest.mark.parametrize("content,passed", [
    ("PASS", True), (" pass. ", True), ('"PASS"', True),
    # A model that echoes its own name first. The room strips that line
    # before it checks, so the loop has to as well, or it pays to re-ask an
    # agent the room was about to drop (review, 2026-09-18).
    ("Ada:\n\nPASS", True), ("**Ada**\n\nPASS", True), ("**Ada:**\nPASS.", True),
    ("Ada\r\n\r\nPASS", True), ("Ada:\n\nPASS" + SMART_FOOTER, True),
    ("PASS" + SMART_FOOTER, True),
    ("PASS\n\nI checked the files", False), ("", False), (None, False),
    ("Ada:\n\nPASS\n\nI read the files and the build is broken.", False),
    ("Ada:", False), ("Ada: PASS on the blue one", False),
    ("Here is the plan.\n\nPASS", False), (SMART_FOOTER, False),
])
def test_the_loop_and_the_room_read_a_pass_the_same_way(content, passed):
    import agent_runner  # noqa: F401  (the loop's module must import cleanly)
    import agent_routing
    import routes_agent_chat
    assert agent_routing.is_pass(content) is passed
    assert routes_agent_chat._is_pass(content) is passed


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


def test_conversation_size_counts_the_arguments_of_tool_calls():
    # A file body the model hands apply_app_change is carried in every later
    # round like any other text.
    msgs = [{"role": "assistant", "content": None, "tool_calls": [
        {"function": {"name": "apply_app_change", "arguments": "x" * 70000}},
        {"function": {"name": "read_app_file", "arguments": "{}"}},
        {"function": {"name": "junk", "arguments": None}},
        {"function": "junk"}, None]},
        {"role": "assistant", "content": "ok", "tool_calls": "junk"}]
    assert esc.conversation_chars(msgs) == 70000 + 2 + 2
    assert esc.too_long(msgs)
