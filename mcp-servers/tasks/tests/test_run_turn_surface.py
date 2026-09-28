"""A turn knows which surface it is running on.

A handoff is a turn like any other, except that its permissions are
narrower, its run points at the run that asked for it, and the office can
tell it apart from a run the person started.
"""
import agent_access
import agent_activity
import agent_handoff
import routes_agent_turn as rt


def _stub(monkeypatch, seen):
    async def resolve(user_email, agent_id):
        return ("tok", [], agent_access.LEVEL_ALL,
                {"id": agent_id, "name": "Iris"}, [])

    async def chat(**kw):
        seen["mode"] = kw.get("tool_mode")
        return ("answered", [])

    async def start_run(agent_id, user_email, source, parent_run_id=None):
        seen["source"] = source
        seen["parent"] = parent_run_id
        return "run-1"

    async def finish_run(run_id, status, usage=None):
        return None

    async def brief_for(user_email, agent, roster, messages):
        return {"role": "system", "content": "brief"}

    monkeypatch.setattr(rt, "_resolve_agent_row", resolve)
    monkeypatch.setattr(rt, "_chat", chat)
    monkeypatch.setattr(rt, "_brief_for", brief_for)
    monkeypatch.setattr(rt.agent_activity, "start_run", start_run)
    monkeypatch.setattr(rt.agent_activity, "finish_run", finish_run)
    monkeypatch.setattr(rt.agent_memory, "schedule_reflection",
                        lambda *a, **k: None)


async def test_a_channel_turn_is_unchanged(monkeypatch):
    seen = {}
    _stub(monkeypatch, seen)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}])
    assert seen["source"] == agent_activity.SOURCE_CHANNEL
    assert seen["parent"] is None


async def test_a_colleague_turn_says_so(monkeypatch):
    seen = {}
    _stub(monkeypatch, seen)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}],
                       surface=agent_access.SURFACE_COLLEAGUE,
                       parent_run_id="run-0")
    assert seen["source"] == agent_activity.SOURCE_COLLEAGUE
    assert seen["parent"] == "run-0"


async def test_a_colleague_turn_uses_the_colleague_permissions(monkeypatch):
    """LEVEL_ALL is what the stub returns, so a colleague turn may act. The
    point of this test is that the SURFACE reaches effective_mode at all."""
    seen = {}
    _stub(monkeypatch, seen)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}],
                       surface=agent_access.SURFACE_COLLEAGUE)
    assert seen["mode"] == agent_access.MODE_FULL


async def test_a_colleague_turn_does_not_wait_as_long(monkeypatch):
    """Somebody is waiting mid-sentence for it, and agents run one at a
    time on a 3.8GB box."""
    seen = {}

    async def chat(**kw):
        seen["timeout"] = kw.get("timeout")
        seen["iterations"] = kw.get("max_iterations")
        return ("answered", [])

    _stub(monkeypatch, seen)
    monkeypatch.setattr(rt, "_chat", chat)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}],
                       surface=agent_access.SURFACE_COLLEAGUE)
    assert seen["timeout"] < rt.CHANNEL_HTTP_TIMEOUT_SECONDS
    assert seen["iterations"] < rt.CHANNEL_MAX_TOOL_ITERATIONS


async def test_the_outermost_turn_opens_the_handoff_budget(monkeypatch):
    seen = {}
    opened = []

    async def chat(**kw):
        opened.append(agent_handoff.parent_run())
        return ("answered", [])

    _stub(monkeypatch, seen)
    monkeypatch.setattr(rt, "_chat", chat)
    await rt._run_turn("me@example.com", "agent-iris",
                       [{"role": "user", "content": "hi"}])
    assert opened == ["run-1"]
