"""The clock filter, and the copy of the formatter it is forced to carry.

The filter runs inside the open-webui container, which does not have the tasks
service on its path, so it cannot import user_timezone. It carries a copy of
context_line instead. A copy nobody checks is a copy that drifts, and the drift
here would be invisible: both sides keep producing a plausible sentence, they
just stop agreeing about what time it is.

So the copy is loaded from disk and compared against the original, for zones on
both sides of UTC and on both sides of a daylight saving boundary.

Also covered: the two early returns the memory filter has and this one must
not. A user with an empty knowledge graph typing "hi" is exactly the person who
gets no answer if the clock is folded into that filter.
"""
import importlib.util
import pathlib
from datetime import datetime, timezone

import pytest

import user_timezone

FILTER_PATH = (pathlib.Path(__file__).resolve().parents[3]
               / "open-webui-functions" / "user_local_time_filter.py")


@pytest.fixture(scope="module")
def owui():
    assert FILTER_PATH.exists(), FILTER_PATH
    spec = importlib.util.spec_from_file_location("user_local_time_filter",
                                                  FILTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ZONES = ["Asia/Manila", "UTC", "America/New_York", "Europe/Berlin",
         "Pacific/Auckland", None, "Some/Removed_Zone"]
INSTANTS = [datetime(2026, 8, 19, 9, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 15, 23, 40, tzinfo=timezone.utc)]


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("instant", INSTANTS)
def test_the_filters_copy_says_the_same_thing_as_the_service(owui, zone, instant):
    assert owui.context_line(zone, now=instant) == \
        user_timezone.context_line(zone, now=instant)


def test_both_agree_on_the_fallback_zone(owui):
    assert owui.DEFAULT_TZ == user_timezone.DEFAULT_TZ


# --- the early returns this filter must not have --------------------------

class _Filter:
    """The real Filter with the network call stubbed out."""

    def __init__(self, owui, zone="Asia/Manila"):
        self.f = owui.Filter()

        async def _fetch(email):
            return zone

        self.f._fetch_zone = _fetch


def _system_texts(body):
    return [m["content"] for m in body["messages"] if m["role"] == "system"]


async def test_a_two_character_message_still_gets_the_time(owui):
    """The memory filter skips anything under 3 characters. For memory that is
    right. "hi" is still a turn a model may be asked the time on."""
    f = _Filter(owui).f
    body = {"messages": [{"role": "user", "content": "hi"}]}
    out = await f.inlet(body, {"email": "ralph@example.com"})
    assert any("current local date and time" in t for t in _system_texts(out))


async def test_a_user_with_no_stored_zone_still_gets_a_line(owui):
    """The memory filter returns early when there is nothing to inject. A clock
    always has something to say, even if it has to say the zone is a guess."""
    f = _Filter(owui, zone=None).f
    body = {"messages": [{"role": "user", "content": "what time is it"}]}
    out = await f.inlet(body, {"email": "new@example.com"})
    texts = _system_texts(out)
    assert texts and "unconfirmed" in texts[0]


async def test_the_line_lands_after_the_system_prompt_not_before(owui):
    f = _Filter(owui).f
    body = {"messages": [{"role": "system", "content": "You are helpful."},
                         {"role": "user", "content": "hello"}]}
    out = await f.inlet(body, {"email": "ralph@example.com"})
    assert out["messages"][0]["content"] == "You are helpful."
    assert "current local date and time" in out["messages"][1]["content"]


async def test_it_is_not_stamped_twice(owui):
    f = _Filter(owui).f
    body = {"messages": [{"role": "user", "content": "hello"}]}
    body = await f.inlet(body, {"email": "ralph@example.com"})
    body = await f.inlet(body, {"email": "ralph@example.com"})
    assert sum("current local date and time" in t
               for t in _system_texts(body)) == 1


async def test_an_unidentified_caller_is_left_alone(owui):
    f = _Filter(owui).f
    body = {"messages": [{"role": "user", "content": "hello"}]}
    out = await f.inlet(body, {})
    assert _system_texts(out) == []


async def test_a_failing_lookup_does_not_break_the_chat(owui):
    """Fails open. A clock is never worth taking a conversation down for."""
    f = owui.Filter()

    async def boom(email):
        raise RuntimeError("tasks unreachable")

    f._fetch_zone = boom
    body = {"messages": [{"role": "user", "content": "hello"}]}
    out = await f.inlet(body, {"email": "ralph@example.com"})
    assert out["messages"][-1]["content"] == "hello"


async def test_the_zone_is_looked_up_once_not_once_per_turn(owui):
    calls = []
    f = owui.Filter()

    async def counted(email):
        calls.append(email)
        return "Asia/Manila"

    f._fetch_zone = counted
    for _ in range(5):
        await f.inlet({"messages": [{"role": "user", "content": "hi"}]},
                      {"email": "ralph@example.com"})
    assert len(calls) == 1
