"""A schedule is named for what it does, not for its time and prompt again.

Asked for 2026-11-24 from the Cron Jobs page, where Discord and Slack had
named schedules "every day at 7:00 PM: give me the best quote for this day
and send give me news up". The card already shows the time; the name now
says what it is, in a few words. A name somebody typed is kept.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routes_schedules as R  # noqa: E402
import schedule_names as N  # noqa: E402


@pytest.mark.parametrize("prompt, name", [
    ("give me the best quote for this day and send give me news up",
     "Best quote for this day"),
    ("give me the best qoute for today", "Best qoute for today"),
    ("Send the user one short daily quote for the day, with a one-line note",
     "One short daily quote"),
    ("Check my Gmail inbox for emails that arrived in the last 24 hours.",
     "Check my Gmail inbox for emails"),
    ("Write my morning board brief. Read these with your tools",
     "Write my morning board brief"),
    ("please can you summarize my unread email and post the highlights",
     "Summarize my unread email"),
    ("every day at 8am read my email and send me a summary",
     "Read my email"),
    ("Every weekday at 9:00 am, tell me what is due today",
     "What is due today"),
    ("give me a motivational quote", "Motivational quote"),
    ("", "Scheduled task"),
    ("   ", "Scheduled task"),
    ("the", "Scheduled task"),
])
def test_a_prompt_becomes_a_few_words_for_what_it_does(prompt, name):
    assert N.short_name(prompt) == name


# Live, 2026-11-26, right after #293 shipped: "please can you give me the
# best quote for this day every morning" was named "Best quote for this day
# every". The time came at the END, and only a time at the start was
# removed, so the six-word cap cut it in half.
@pytest.mark.parametrize("prompt, name", [
    ("please can you give me the best quote for this day every morning",
     "Best quote for this day"),
    ("read my email every weekday at 9am", "Read my email"),
    ("summarize my unread mail each friday", "Summarize my unread mail"),
    ("post the sales numbers daily", "Post the sales numbers"),
    ("check the server at 8:30 pm", "Check the server"),
    ("send me the board brief on mondays", "Board brief"),
    ("remind me to drink water every 2 hours", "Remind me to drink water"),
    ("check my inbox in the morning", "Check my inbox"),
    # "every" that is not a time stays: it is part of what is asked.
    ("summarize every unread email", "Summarize every unread email"),
    ("list each open pull request", "List each open pull request"),
])
def test_a_time_at_the_end_is_dropped_too(prompt, name):
    assert N.short_name(prompt) == name


def test_a_role_sentence_in_front_is_not_the_name():
    # A live prompt: "You are Ada, ... project manager. Write this week's
    # review ..." was named "You are Ada".
    assert N.short_name("You are Ada, the project manager. Write this "
                        "week's review for the team") == "Write this week's review"
    assert N.short_name("You are a helpful assistant. give me a motivational "
                        "quote") == "Motivational quote"


def test_a_name_never_ends_on_every_or_each():
    for prompt in ("give me one quote from a famous person every",
                   "tell me something new about my business each"):
        last = N.short_name(prompt).split()[-1].lower()
        assert last not in ("every", "each"), prompt


def test_a_name_is_short():
    long = "summarise every single message in every channel of the workspace"
    out = N.short_name(long)
    assert len(out) <= N.MAX_CHARS and len(out.split()) <= N.MAX_WORDS


@pytest.mark.parametrize("name, prompt", [
    # Discord: "<when>: <task[:60]>"
    ("every day at 7:00 PM: give me the best quote for this day and send give me news up",
     "give me the best quote for this day and send give me news up"),
    ("Every day at 7:00 PM: give me the best quote for this day and send giv",
     "give me the best quote for this day and send give me news up today"),
    # Slack: the prompt's first 40 characters
    ("give me the best quote for this day and",
     "give me the best quote for this day and send give me news up"),
    ("", "check my inbox"),
])
def test_a_name_that_is_only_the_prompt_is_replaced(name, prompt):
    assert N.is_made_from_prompt(name, prompt)
    assert N.name_for(name, prompt) == N.short_name(prompt)


@pytest.mark.parametrize("name, prompt", [
    ("Weekly review", "You are Ada. Write this week's review."),
    ("Inbox check (Gmail)", "Check my Gmail inbox for emails"),
    ("Daily Quote", "Send the user one short daily quote"),
    # A name that happens to start like the prompt but is short is a
    # name somebody chose, not a paste.
    ("Check", "Check my Gmail inbox for emails"),
])
def test_a_name_somebody_chose_is_kept(name, prompt):
    assert not N.is_made_from_prompt(name, prompt)
    assert N.name_for(name, prompt) == name


# --- the create route ----------------------------------------------------

class _Session:
    def __init__(self, rows):
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def add(self, row):
        self.rows.append(row)

    async def commit(self):
        return None


@pytest.fixture
def made(monkeypatch):
    rows = []
    monkeypatch.setattr(R, "session", lambda: _Session(rows))

    async def _cap(owner):
        return None
    monkeypatch.setattr(R, "_enforce_count_cap", _cap)
    return rows


async def _create(**fields):
    body = {"cron_expr": "0 19 * * *", "prompt": "give me the best quote "
            "for this day and send give me news up",
            "agent_id": "agent-a-1", **fields}
    return await R.create_schedule(R.CreateScheduleIn(**body),
                                   x_cron_secret="",
                                   x_user_email="me@example.com",
                                   x_user_admin="")


async def test_a_schedule_made_with_no_name_is_named_from_its_prompt(made):
    await _create()
    assert made[0].name == "Best quote for this day"


async def test_a_bots_pasted_name_is_replaced(made):
    await _create(name="every day at 7:00 PM: give me the best quote for "
                       "this day and send give me news up")
    assert made[0].name == "Best quote for this day"


async def test_a_typed_name_is_kept(made):
    await _create(name="Daily Quote")
    assert made[0].name == "Daily Quote"


def test_the_bots_still_send_a_name_and_that_still_works():
    """Discord and Slack send `name`; it stays accepted."""
    assert "name" in R.CreateScheduleIn.model_fields


# --- the edit route --------------------------------------------------------

class _PatchSession:
    def __init__(self, seen):
        self.seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        self.seen.append(stmt)

    async def commit(self):
        return None


@pytest.fixture
def patched(monkeypatch):
    seen = []

    class S:
        id = "11111111-2222-3333-4444-555555555555"
        user_email = "me@example.com"
        prompt = "give me the best quote for this day and send give me news up"

    async def _scoped(schedule_id, email):
        return S()
    monkeypatch.setattr(R, "_scoped_schedule", _scoped)
    monkeypatch.setattr(R, "session", lambda: _PatchSession(seen))

    def names():
        return [st.compile().params.get("name") for st in seen
                if getattr(st, "is_update", False)]
    return names


async def _patch(**fields):
    return await R.update_schedule("11111111-2222-3333-4444-555555555555",
                                   R.UpdateScheduleIn(**fields),
                                   x_cron_secret="",
                                   x_user_email="me@example.com",
                                   x_user_admin="")


async def test_the_discord_modals_pasted_name_is_tidied_on_edit(patched):
    await _patch(name="every day at 7:00 PM: give me the best quote for this",
                 prompt="give me the best quote for this day",
                 cron_expr="0 19 * * *")
    assert patched() == ["Best quote for this day"]


async def test_a_renamed_schedule_keeps_the_name_typed(patched):
    await _patch(name="Evening quote")
    assert patched() == ["Evening quote"]
