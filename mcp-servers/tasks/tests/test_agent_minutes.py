"""The minutes of a meeting: what is read, what is kept, and that nothing
about them can break the meeting they belong to."""
from datetime import datetime, timezone
from unittest.mock import patch

import agent_minutes as mins

NAMES = ["Ada", "Mia"]
ANSWERS = [("Ada", "Two invoices are due Friday. I will chase Northwind."),
           ("Mia", "Acme is paid. Who owns the renewal?")]


# --- the prompt ------------------------------------------------------------

def test_the_minute_taker_reads_the_question_and_every_answer():
    msgs = mins.prompt("what is due this week", ANSWERS, NAMES)
    assert msgs[0]["role"] == "system" and "JSON only" in msgs[0]["content"]
    body = msgs[1]["content"]
    assert "what is due this week" in body
    assert "Ada: Two invoices" in body and "Mia: Acme is paid" in body
    assert "Agents in the meeting: Ada, Mia" in body


def test_a_very_long_answer_is_cut_not_dropped():
    body = mins.prompt("q", [("Ada", "x" * 10_000)], ["Ada"])[1]["content"]
    assert "Ada: " + "x" * mins.MAX_ANSWER_CHARS in body
    assert "x" * (mins.MAX_ANSWER_CHARS + 1) not in body


# --- the reply -------------------------------------------------------------

def test_json_in_a_fence_or_around_prose_still_counts():
    fenced = '```json\n{"decided": ["Chase Northwind"], "todo": [], "open": []}\n```'
    prose = 'Here are the minutes: {"decided": ["Chase Northwind"], "todo": [], "open": []} done.'
    assert mins.parse(fenced, NAMES)["decided"] == ["Chase Northwind"]
    assert mins.parse(prose, NAMES)["decided"] == ["Chase Northwind"]


def test_a_to_do_names_an_agent_as_given_or_you():
    out = mins.parse('{"decided": [], "todo": [{"what": "chase Northwind", "who": "ada"},'
                     ' {"what": "own the renewal", "who": "the person"},'
                     ' {"what": "call Bob", "who": "Zed"}, "plain line"], "open": []}', NAMES)
    assert out["todo"] == [{"what": "chase Northwind", "who": "Ada"},
                           {"what": "own the renewal", "who": "You"},
                           {"what": "call Bob", "who": "You"},
                           {"what": "plain line", "who": "You"}]


def test_nothing_in_the_reply_is_no_minutes():
    assert mins.parse("Sorry, I cannot.", NAMES) is None
    assert mins.parse('{"decided": [], "todo": [], "open": []}', NAMES) is None
    assert mins.parse('{"decided": "not a list"}', NAMES) is None
    assert mins.parse("[1, 2]", NAMES) is None


def test_lines_are_capped_in_number_and_length():
    out = mins.parse('{"decided": %s, "todo": [], "open": []}'
                     % str(["line %d" % i for i in range(20)]).replace("'", '"'), NAMES)
    assert len(out["decided"]) == mins.MAX_LINES
    out = mins.parse('{"decided": ["%s"], "todo": [], "open": []}' % ("y" * 500), NAMES)
    assert len(out["decided"][0]) == mins.MAX_LINE_CHARS


# --- the bubble ------------------------------------------------------------

def test_the_markdown_has_a_dated_heading_and_only_the_sections_with_lines():
    when = datetime(2026, 10, 26, tzinfo=timezone.utc)
    text = mins.markdown({"decided": ["Chase Northwind"],
                          "todo": [{"what": "chase Northwind", "who": "Ada"}],
                          "open": []}, when)
    assert text.startswith("**Minutes, 26 Oct**")
    assert "**Decided**\n- Chase Northwind" in text
    assert "**To do**\n- Ada: chase Northwind" in text
    assert "Open questions" not in text


# --- taking them -----------------------------------------------------------

async def test_one_answer_is_not_a_meeting_and_the_model_is_not_asked():
    async def never(email, messages):
        raise AssertionError("not asked")
    with patch.object(mins, "_ask", never):
        assert await mins.take("o@x", "q", [("Ada", "only me")], ["Ada"]) is None


async def test_the_minutes_are_taken_and_the_to_dos_written():
    seen = {}

    async def ask(email, messages):
        seen["email"] = email
        return '{"decided": ["Chase Northwind"], "todo": [{"what": "chase Northwind", "who": "Ada"}], "open": ["renewal owner"]}'

    async def write(email, todo):
        seen["todo"] = (email, todo)
        return len(todo)

    with patch.object(mins, "_ask", ask), patch.object(mins, "_write_todos", write):
        got = await mins.take("o@x", "what is due", ANSWERS, NAMES,
                              when=datetime(2026, 10, 26, tzinfo=timezone.utc))
    assert seen["email"] == "o@x"
    assert seen["todo"] == ("o@x", [{"what": "chase Northwind", "who": "Ada"}])
    assert got["written"] == 1
    assert "**Minutes, 26 Oct**" in got["text"] and "- Ada: chase Northwind" in got["text"]
    assert "- renewal owner" in got["text"]


async def test_a_model_that_fails_or_rambles_leaves_no_minutes():
    async def boom(email, messages):
        raise RuntimeError("router down")

    async def rambles(email, messages):
        return "I think the meeting went well."

    with patch.object(mins, "_ask", boom):
        assert await mins.take("o@x", "q", ANSWERS, NAMES) is None
    with patch.object(mins, "_ask", rambles):
        assert await mins.take("o@x", "q", ANSWERS, NAMES) is None


async def test_to_do_rows_that_cannot_be_written_still_leave_the_minutes():
    async def ask(email, messages):
        return '{"decided": [], "todo": [{"what": "chase Northwind", "who": "Ada"}], "open": []}'

    async def broken(email, todo):
        raise RuntimeError("no database")

    with patch.object(mins, "_ask", ask), patch.object(mins, "_write_todos", broken):
        got = await mins.take("o@x", "q", ANSWERS, NAMES)
    assert got and got["written"] == 0 and "- Ada: chase Northwind" in got["text"]
