"""Edit a schedule from the Cron Jobs page.

Asked for 2026-11-24: a card could be run, disabled, muted or deleted, and
changing anything about it meant deleting it and making it again, which
also threw away its run history and its outputs. The page's Edit button
PATCHes the same row. The PATCH used to take only the name, the time and
the prompt (all the Discord edit modal sends), so it now takes the agent
and the tool access too, with the same rules create has.
"""
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import routes_schedules as R  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"


class _Session:
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
def written(monkeypatch):
    """What the PATCH wrote, as {column: value} per UPDATE it ran."""
    seen = []

    class S:
        id = SID
        user_email = "me@example.com"
        kind = "agent"

    async def _scoped(schedule_id, email):
        return S()

    monkeypatch.setattr(R, "_scoped_schedule", _scoped)
    monkeypatch.setattr(R, "session", lambda: _Session(seen))

    def values():
        out = []
        for stmt in seen:
            if getattr(stmt, "is_update", False):
                params = stmt.compile().params
                out.append({k: v for k, v in params.items()
                            if not k.startswith("id_")})
        return out
    return values


async def _patch(**fields):
    return await R.update_schedule(SID, R.UpdateScheduleIn(**fields),
                                   x_cron_secret="",
                                   x_user_email="me@example.com",
                                   x_user_admin="")


async def test_the_agent_and_the_tool_access_can_be_changed(written):
    out = await _patch(agent_id="agent-research-assistant-0001",
                       tool_mode="full")
    assert out == {"status": "updated"}
    assert written() == [{"agent_id": "agent-research-assistant-0001",
                          "tool_mode": "full"}]


async def test_everything_the_form_shows_is_written_in_one_update(written):
    await _patch(name="Morning brief", cron_expr="30 7 * * 1-5",
                 prompt="Read my board and say what is due.",
                 agent_id="agent-inbox-triage-0002", tool_mode="read_only")
    assert written() == [{"name": "Morning brief",
                          "cron_expr": "30 7 * * 1-5",
                          "prompt": "Read my board and say what is due.",
                          "agent_id": "agent-inbox-triage-0002",
                          "tool_mode": "read_only"}]


async def test_the_agent_id_is_trimmed(written):
    await _patch(agent_id="  agent-a-1  ")
    assert written() == [{"agent_id": "agent-a-1"}]


async def test_what_the_discord_modal_sends_leaves_agent_and_access_alone(written):
    await _patch(name="Inbox check", cron_expr="0 9 * * *", prompt="check")
    (row,) = written()
    assert "agent_id" not in row and "tool_mode" not in row


@pytest.mark.parametrize("mode", ["ask", "FULL", "", "admin"])
async def test_an_unknown_tool_access_is_refused(written, mode):
    with pytest.raises(HTTPException) as e:
        await _patch(tool_mode=mode)
    assert e.value.status_code == 400
    assert written() == [], "nothing may be written on a refusal"


@pytest.mark.parametrize("agent", ["", "   "])
async def test_a_blank_agent_is_refused(written, agent):
    """A schedule with no agent fails every time it fires, at 7am, unseen."""
    with pytest.raises(HTTPException) as e:
        await _patch(agent_id=agent)
    assert e.value.status_code == 400
    assert written() == []


@pytest.mark.parametrize("field", ["name", "prompt"])
@pytest.mark.parametrize("blank", ["", "  \n "])
async def test_a_blank_name_or_prompt_is_refused(written, field, blank):
    with pytest.raises(HTTPException) as e:
        await _patch(**{field: blank})
    assert e.value.status_code == 400
    assert written() == []


async def test_a_refused_field_stops_the_whole_edit(written):
    """A bad tool access must not let the good name through on its own."""
    with pytest.raises(HTTPException):
        await _patch(name="New name", tool_mode="ask")
    assert written() == []


async def test_the_fifteen_minute_floor_still_applies(written):
    with pytest.raises(HTTPException) as e:
        await _patch(cron_expr="*/5 * * * *", agent_id="agent-a-1")
    assert e.value.status_code == 400
    assert written() == []


async def test_nothing_sent_writes_nothing(written):
    assert await _patch() == {"status": "updated"}
    assert written() == []


async def test_a_listed_schedule_carries_what_the_form_needs():
    """The Edit button fills the form from the listing, so it must carry
    every field the form shows."""
    import uuid

    class Row:
        id = uuid.UUID(SID)
        user_email = "me@example.com"
        name = "Daily Quote"
        cron_expr = "0 0 * * *"
        tz = "UTC"
        persona = ""
        prompt = "Send one quote."
        enabled = True
        last_run_at = None
        last_run_status = None
        last_result = None
        last_result_at = None
        delivery_channel_id = None
        delivery_platform = "discord"
        kind = "agent"
        agent_id = "agent-inbox-triage-0002"
        tool_mode = "full"
        notify = True

    out = R._serialize(Row())
    for key in ("name", "cron_expr", "tz", "prompt", "agent_id", "tool_mode"):
        assert out[key] == getattr(Row, key), key
