"""Somebody who started a connect and never got back is told so.

Measured on production 2026-11-18, from the table added two days before
for exactly this:

    11:04, 11:04, 11:05, 11:06, 11:11, 11:21, 11:27, 11:28, 11:50,
    11:58, 11:59   alamajacintg04   airtable   started

Eleven attempts in an hour, every one recorded `started` and nothing
else. None of the fourteen failure stages fired, and the tasks log has
ZERO hits on /connect/airtable/callback in that window. So Airtable
never sent him back at all: the integration is limited to development
use, where only its owner can authorize it.

He was never told anything. He could not be told on return, because he
never returned. But the next time he opens Connections, the platform
knows perfectly well that he has tried eleven times and never landed,
and it should say so instead of showing him the same Connect button for
the twelfth time.

That is what the table was for, and until now nothing read it.

WHAT COUNTS AS STUCK, and why it is not just "a failure happened":

  * Only starts with NO success after them. Connecting on the fourth go
    is not stuck, it is connected, and a card that nags about earlier
    failures after a success is noise.
  * TWO or more. One abandoned connect is somebody changing their mind,
    and calling that a fault would train people to ignore the notice.
  * Only the stage that means "we sent them to the vendor". A start
    that came back as `declined` is a person pressing cancel, which is
    an answer, not a wall.
"""
import os

import pytest

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connect_attempt as CA

HIM = "alamajacintg04@gmail.com"


def row(provider, stage, at, email=HIM):
    return {"email": email, "provider": provider, "stage": stage,
            "http_status": None, "at": at}


# --- the real case --------------------------------------------------------

def test_eleven_starts_and_no_return_is_stuck():
    rows = [row("airtable", "started", i) for i in range(11)]
    stuck = CA.stuck_for(HIM, rows)
    assert "airtable" in stuck, stuck
    assert stuck["airtable"]["starts"] == 11


def test_the_notice_says_what_to_do_about_it():
    rows = [row("airtable", "started", i) for i in range(11)]
    said = CA.stuck_line("Airtable", CA.stuck_for(HIM, rows)["airtable"])
    low = said.lower()
    assert "11" in said, said
    # It must not blame the person, and must point at the one thing that
    # actually unblocks them.
    assert "set up" in low or "owner" in low or "finish" in low, said
    assert "you" in low, said


# --- what must NOT count --------------------------------------------------

def test_connecting_in_the_end_is_not_stuck():
    """Three goes then success is a person who got there."""
    rows = [row("airtable", "started", 1), row("airtable", "started", 2),
            row("airtable", "started", 3),
            row("airtable", "connected", 4)]
    assert CA.stuck_for(HIM, rows) == {}


def test_a_success_then_a_fresh_start_is_not_stuck_yet():
    """Reconnecting is ordinary. One start after a success is not a wall."""
    rows = [row("airtable", "connected", 1), row("airtable", "started", 2)]
    assert CA.stuck_for(HIM, rows) == {}


def test_two_starts_after_a_success_is_stuck_again():
    rows = [row("airtable", "connected", 1), row("airtable", "started", 2),
            row("airtable", "started", 3)]
    assert CA.stuck_for(HIM, rows).get("airtable", {}).get("starts") == 2


def test_one_abandoned_connect_is_not_a_fault():
    """Somebody changing their mind. Calling that a fault would train
    people to ignore the notice."""
    assert CA.stuck_for(HIM, [row("airtable", "started", 1)]) == {}


def test_pressing_cancel_is_an_answer_not_a_wall():
    """`declined` means the vendor DID come back and the person said no."""
    rows = [row("airtable", "started", 1), row("airtable", "declined", 2),
            row("airtable", "started", 3), row("airtable", "declined", 4)]
    assert CA.stuck_for(HIM, rows) == {}


def test_a_failure_that_came_back_is_not_this():
    """A token the vendor rejected is a different problem with a
    different fix, and it already shows as Needs reconnecting."""
    rows = [row("airtable", "started", 1),
            row("airtable", "token_rejected", 2),
            row("airtable", "started", 3),
            row("airtable", "token_rejected", 4)]
    assert CA.stuck_for(HIM, rows) == {}


def test_somebody_elses_attempts_are_not_mine():
    rows = [row("airtable", "started", i, email="someone@else.com")
            for i in range(11)]
    assert CA.stuck_for(HIM, rows) == {}


def test_each_app_is_judged_on_its_own():
    rows = ([row("airtable", "started", i) for i in range(3)]
            + [row("notion", "started", 9), row("notion", "connected", 10)])
    stuck = CA.stuck_for(HIM, rows)
    assert set(stuck) == {"airtable"}


def test_no_rows_is_not_stuck():
    assert CA.stuck_for(HIM, []) == {}
    assert CA.stuck_for("", []) == {}


def test_it_never_raises_on_a_row_it_cannot_read():
    """It reads rows written by call sites that may be newer than it is,
    and a notice is never worth taking a page down for."""
    rows = [None, {}, {"email": HIM}, "nonsense",
            {"email": HIM, "provider": "airtable", "stage": "started"},
            {"email": HIM, "provider": "airtable", "stage": "started"}]
    out = CA.stuck_for(HIM, rows)
    assert out.get("airtable", {}).get("starts") == 2
