"""A skill somebody wrote reaches their own agent's brief.

The last piece. #92 stored personal skills, #93 wrote them, and until now an
agent still could not hold one: `selected()` resolved names against the
files in the image and nothing else.

The design called this the most dangerous change in the work, because
`brief_for` runs inside the brief, inside every turn, on every surface: the
chat panel, Discord, Telegram, the terminal channel and every scheduled
run. It proposed making it async and giving it the database.

It is not async here, and that is deliberate. Both callers were already
async, so the lookup moved OUT to them and `brief_for` stayed the pure
function it has always been. The behaviour the design asked for is the
same; nothing in a turn had to become awaitable, and every existing test of
a brief still calls it the way it always did.

Two rules from the spec are load-bearing and are tested as such:

  an agent with NO skills of its own must not touch the database at all,
  because most agents are that and the cost is paid on every turn by
  everybody;

  a database that cannot be read returns the built-in skills alone and
  never raises, because bookkeeping must not cost somebody their turn.
"""
import pytest

import agent_brief
import agent_skills
import user_skills as US

MINE = {"name": "chase-invoices", "description": "Chase unpaid invoices.",
        "tools": [], "body": "Steps:\n1. List overdue invoices."}

SHIPPED = next(iter(sorted(agent_skills.load_all())), "daily-standup")


def _agent(*skill_ids):
    return {"id": "agent-x", "name": "Ada",
            "meta": {"skillIds": list(skill_ids), "role": "Project manager"}}


# --- does anything need looking up at all ---------------------------------

def test_an_agent_with_no_skills_needs_no_lookup():
    assert agent_skills.unknown_ids({}) == []
    assert agent_skills.unknown_ids({"skillIds": []}) == []
    assert agent_skills.unknown_ids(None) == []


def test_an_agent_holding_only_built_ins_needs_no_lookup():
    """The common case. Most agents are this, and a round trip for them is
    paid on every turn by every person on the platform."""
    assert agent_skills.unknown_ids({"skillIds": [SHIPPED]}) == []


def test_an_agent_holding_something_we_do_not_ship_needs_one():
    assert agent_skills.unknown_ids(
        {"skillIds": ["chase-invoices"]}) == ["chase-invoices"]


async def test_the_database_is_not_touched_when_nothing_is_unknown(monkeypatch):
    """The guard, driven rather than read."""
    called = []

    async def spy(email):
        called.append(email)
        return [MINE]

    monkeypatch.setattr(US, "_rows_seam", spy)
    assert await US.overlay_for("r@example.com", {"skillIds": [SHIPPED]}) == {}
    assert await US.overlay_for("r@example.com", {}) == {}
    assert called == [], "a turn queried the database for nothing"


async def test_nobody_is_never_a_lookup(monkeypatch):
    called = []

    async def spy(email):
        called.append(email)
        return []

    monkeypatch.setattr(US, "_rows_seam", spy)
    assert await US.overlay_for("", {"skillIds": ["chase-invoices"]}) == {}
    assert called == []


async def test_an_unknown_skill_fetches_this_persons_own(monkeypatch):
    async def rows(email):
        assert email == "r@example.com"
        return [MINE]

    monkeypatch.setattr(US, "_rows_seam", rows)
    overlay = await US.overlay_for("r@example.com",
                                   {"skillIds": ["chase-invoices"]})
    assert list(overlay) == ["chase-invoices"]
    assert overlay["chase-invoices"]["mine"] is True


# --- a failure costs the skills, never the turn ---------------------------

async def test_a_database_that_is_down_still_builds_a_brief(monkeypatch):
    """The rule this codebase already follows. Without their own skills
    they are where the platform was yesterday, which is working."""
    async def boom(email):
        raise RuntimeError("the database is down")

    monkeypatch.setattr(US, "_rows_seam", boom)
    overlay = await US.overlay_for("r@example.com",
                                   {"skillIds": ["chase-invoices"]})
    assert overlay == {}
    line = agent_brief.build(_agent("chase-invoices"), [], own_skills=overlay)
    assert line["role"] == "system" and line["content"]


# --- the brief itself ------------------------------------------------------

def test_my_own_skill_reaches_the_brief():
    overlay = {"chase-invoices": US.as_skill(MINE)}
    content = agent_brief.build(_agent("chase-invoices"), [],
                                own_skills=overlay)["content"]
    assert "chase-invoices" in content
    assert "List overdue invoices" in content


def test_a_brief_without_an_overlay_is_what_it_always_was():
    """Every agent that predates this, which is all of them. The ordinary
    turn has to be unchanged to the character."""
    before = agent_brief.build(_agent(), [])["content"]
    after = agent_brief.build(_agent(), [], own_skills={})["content"]
    assert before == after


def test_a_built_in_skill_still_works_with_no_overlay():
    content = agent_brief.build(_agent(SHIPPED), [])["content"]
    assert SHIPPED in content


def test_mine_and_a_built_in_can_be_held_together():
    overlay = {"chase-invoices": US.as_skill(MINE)}
    content = agent_brief.build(_agent(SHIPPED, "chase-invoices"), [],
                                own_skills=overlay)["content"]
    assert SHIPPED in content and "chase-invoices" in content


def test_my_own_skill_beats_a_built_in_of_the_same_name():
    """Migration 066 was written around this: otherwise a deploy that adds
    a built-in silently replaces one somebody wrote."""
    mine = dict(MINE, name=SHIPPED, body="MINE NOT THEIRS")
    content = agent_brief.build(_agent(SHIPPED), [],
                                own_skills={SHIPPED: US.as_skill(mine)})["content"]
    assert "MINE NOT THEIRS" in content


def test_a_skill_that_is_gone_is_left_out_rather_than_breaking_the_turn():
    """Deleting a skill leaves the agents that referenced it alone. There
    was already a test proving this for built-ins; it has to stay true now
    that a name can disappear because somebody deleted their own."""
    content = agent_brief.build(_agent("deleted-yesterday"), [],
                                own_skills={})["content"]
    assert content and "deleted-yesterday" not in content


# --- brief_for did not become async ---------------------------------------

def test_the_resolver_is_still_a_pure_function():
    """The design proposed `async def brief_for(meta, user_email)`, which
    would have made the brief, _identity_line and every surface's turn
    awaitable. Both callers were already async, so the I/O moved to them
    instead. If this ever becomes a coroutine, every existing test of a
    brief is calling it wrong."""
    import inspect
    assert not inspect.iscoroutinefunction(agent_skills.brief_for)
    assert not inspect.iscoroutinefunction(agent_skills.selected)
    assert not inspect.iscoroutinefunction(agent_brief.build)
