"""What a run cost, which model answered, and how many paid turns a person
has had today. The SQL is captured, not run: the DB tier is exercised on the
server (see the plan's live verification task)."""
import pytest

import agent_activity
import agent_escalation


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Session:
    def __init__(self, log, value=None, boom=False):
        self.log, self.value, self.boom = log, value, boom

    async def __aenter__(self):
        if self.boom:
            raise RuntimeError("db down")
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, statement, params=None):
        self.log.append((str(statement), dict(params or {})))
        return _Result(self.value)

    async def commit(self):
        self.log.append(("COMMIT", {}))


@pytest.fixture
def db(monkeypatch):
    log = []
    state = {"value": None, "boom": False}
    monkeypatch.setattr(agent_activity, "session",
                        lambda: _Session(log, state["value"], state["boom"]))
    return log, state


async def test_finishing_without_usage_writes_exactly_what_it_did_before(db):
    log, _ = db
    await agent_activity.finish_run("run-1", "completed")
    sql, params = log[0]
    assert "model" not in sql and "cost_usd" not in sql
    assert params == {"id": "run-1", "status": "completed"}


async def test_finishing_with_usage_writes_the_model_the_reason_and_the_cost(db):
    log, _ = db
    usage = agent_escalation.TurnUsage(run_id="run-1", model="gpt-5.5",
                                       escalation="build", prompt_tokens=2000,
                                       completion_tokens=200, cost_usd=0.016)
    await agent_activity.finish_run("run-1", "completed", usage=usage)
    sql, params = log[0]
    assert "COALESCE(:escalation, escalation)" in sql
    assert params == {"id": "run-1", "status": "completed", "model": "gpt-5.5",
                      "escalation": "build", "prompt_tokens": 2000,
                      "completion_tokens": 200, "cost_usd": 0.016}
    assert log[-1][0] == "COMMIT"


async def test_a_move_is_recorded_the_moment_it_happens(db):
    log, _ = db
    await agent_activity.mark_escalated("run-1", "heavy_tool")
    assert log[0][1] == {"id": "run-1", "reason": "heavy_tool"}
    await agent_activity.mark_escalated(None, "heavy_tool")
    await agent_activity.mark_escalated("run-1", None)
    assert len([e for e in log if e[0] != "COMMIT"]) == 1


async def test_todays_paid_turns_are_counted_per_person_from_utc_midnight(db):
    log, state = db
    state["value"] = 3
    assert await agent_activity.paid_turns_today("Ada@Example.com") == 3
    sql, params = log[0]
    assert "lower(user_email) = lower(:email)" in sql
    assert "escalation IS NOT NULL" in sql
    assert "date_trunc('day', now() AT TIME ZONE 'UTC')" in sql
    assert params == {"email": "Ada@Example.com"}


async def test_a_count_that_fails_is_none_not_zero(db):
    _, state = db
    state["boom"] = True
    assert await agent_activity.paid_turns_today("a@example.com") is None
    assert await agent_activity.paid_turns_today("") is None


async def test_recording_cost_never_raises_when_the_database_is_down(db):
    _, state = db
    state["boom"] = True
    await agent_activity.finish_run("run-1", "completed",
                                    usage=agent_escalation.TurnUsage())
    await agent_activity.mark_escalated("run-1", "build")
