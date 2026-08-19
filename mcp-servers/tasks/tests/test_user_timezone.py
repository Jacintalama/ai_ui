"""What time it is where the user is.

Every model on the platform was answering date and time questions with nothing
to go on. Nothing in the repo read or stored a timezone: grep for
timezone|ZoneInfo|pytz outside apps/ returned nothing at all.

The browser knows the answer exactly, as an IANA zone name, so the platform can
learn it without asking anyone. What these tests pin down is the part that is
easy to get wrong once it is stored: an offset is not a timezone (it is wrong
twice a year), a detected value must not overwrite one the user set by hand,
and an unknown zone must be visible as a fallback rather than quietly reported
as fact.
"""
from datetime import datetime, timezone

import pytest

from user_timezone import (
    DEFAULT_TZ,
    context_line,
    local_now,
    normalise_timezone,
    should_store,
)


# --- only a real zone reaches the database --------------------------------

@pytest.mark.parametrize("name", ["Asia/Manila", "UTC", "America/New_York",
                                  "Europe/Berlin"])
def test_a_real_zone_is_accepted(name):
    assert normalise_timezone(name) == name


@pytest.mark.parametrize("bad", ["Not/AZone", "", "   ", None, "PST",
                                 "+08:00", "Asia/Manila; DROP TABLE x", 8])
def test_anything_that_is_not_a_real_zone_is_refused(bad):
    assert normalise_timezone(bad) is None


def test_whitespace_around_a_real_zone_is_tolerated():
    assert normalise_timezone("  Asia/Manila  ") == "Asia/Manila"


# --- a detected value never overwrites a chosen one -----------------------

def test_autodetect_fills_an_empty_row():
    assert should_store(stored_source=None, incoming_manual=False) is True


def test_autodetect_updates_a_previously_autodetected_row():
    """Someone who moves, or who fixed their laptop clock, should be followed."""
    assert should_store(stored_source="auto", incoming_manual=False) is True


def test_autodetect_leaves_a_hand_set_zone_alone():
    """Otherwise opening the app from a laptop in another zone silently undoes
    the setting the user chose."""
    assert should_store(stored_source="manual", incoming_manual=False) is False


def test_a_deliberate_change_always_wins():
    for stored in (None, "auto", "manual"):
        assert should_store(stored_source=stored, incoming_manual=True) is True


# --- the timestamp itself --------------------------------------------------

INSTANT = datetime(2026, 8, 19, 9, 1, 0, tzinfo=timezone.utc)


def test_the_time_is_rendered_in_the_users_zone_not_the_servers():
    assert local_now("Asia/Manila", now=INSTANT).hour == 17    # UTC+8
    assert local_now("America/New_York", now=INSTANT).hour == 5  # UTC-4 in Aug


def test_the_zone_name_survives_a_daylight_saving_boundary():
    """The reason an IANA name is stored and not an offset."""
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    assert local_now("Europe/Berlin", now=winter).hour == 13   # CET
    assert local_now("Europe/Berlin", now=summer).hour == 14   # CEST


# --- the line the model actually reads ------------------------------------

def test_the_line_states_the_date_the_time_and_the_zone():
    line = context_line("Asia/Manila", now=INSTANT)
    assert "Wednesday" in line
    assert "19 August 2026" in line
    assert "5:01" in line and "PM" in line
    assert "Asia/Manila" in line


def test_an_unknown_zone_falls_back_and_still_names_the_zone():
    """A fallback the model can see is recoverable. A silent wrong answer is
    not: it would confidently schedule things in the wrong hemisphere."""
    line = context_line(None, now=INSTANT)
    assert DEFAULT_TZ in line
    assert "unconfirmed" in line.lower()


def test_a_zone_that_stopped_being_valid_does_not_raise():
    """A row written before a tzdata update, or by hand. Falling back beats
    taking the chat down."""
    line = context_line("Some/Removed_Zone", now=INSTANT)
    assert DEFAULT_TZ in line


def test_a_confirmed_zone_is_not_labelled_unconfirmed():
    assert "unconfirmed" not in context_line("Asia/Manila", now=INSTANT).lower()


# --- the default argument path, which every real call takes ---------------

def test_it_works_with_no_instant_supplied():
    """Every test above passes an explicit `now`, so all of them passed while
    `datetime.now(timezone)` was being called with the timezone CLASS instead
    of timezone.utc. That raises, and it raises only on the path production
    uses. Covered here because a test suite that only exercises the injectable
    argument is testing the seam and not the function."""
    line = context_line("Asia/Manila")
    assert "Asia/Manila" in line
    assert local_now("Asia/Manila").tzinfo is not None


def test_a_naive_instant_is_read_as_utc_not_as_server_local():
    naive = datetime(2026, 8, 19, 9, 1, 0)
    assert local_now("Asia/Manila", now=naive).hour == 17
