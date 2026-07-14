"""Pure / mocked-DB tests for two Task 6 whole-branch-review fixes:

1. resume_with_answer (routes_execution.py) now clears stale pre-build
   questions_json/questions_asked_at on every resume path, free-text and
   structured/skip alike, not just the structured branch. Before this fix a
   free-text resume (or an admin answering via the web /answer route) left
   questions_json set, so if that same build later hit a genuine mid-build
   awaiting_input pause (which never sets questions_json), the scheduler's
   pre-build timeout sweep still matched on the stale value and silently
   auto-skipped a real mid-build question.

2. _run_prebuild_questions_then_build (routes_aiuibuilder.py) is now wrapped
   in the same outer try/except/finally contract as
   routes_execution._run_execution: an unexpected DB failure while parking
   the task or chaining into the build resets the task to "pending" and
   always releases the _RUNNING slot, so it can't get stuck "running"
   forever and 429-block every future build.

No real database is required. Finding 2's test stands in a fake async
session in place of db.session() to force a write failure at the exact
point the review flagged.
"""
import inspect
import os
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import routes_aiuibuilder as rb
import routes_execution


# ---------------------------------------------------------------------------
# Finding 1: resume_with_answer clears pre-build questions unconditionally
# ---------------------------------------------------------------------------

def test_clear_prebuild_questions_resets_both_fields():
    item = SimpleNamespace(
        questions_json=[{"q": "Which color?", "options": ["Light", "Dark"]}],
        questions_asked_at=datetime.now(timezone.utc),
    )
    routes_execution._clear_prebuild_questions(item)
    assert item.questions_json is None
    assert item.questions_asked_at is None


def test_clear_prebuild_questions_noop_when_already_clear():
    item = SimpleNamespace(questions_json=None, questions_asked_at=None)
    routes_execution._clear_prebuild_questions(item)
    assert item.questions_json is None
    assert item.questions_asked_at is None


def test_resume_with_answer_calls_clear_prebuild_questions_first():
    # resume_with_answer commits to the DB and spawns a background agent run,
    # too heavy to drive end to end here, so instead pin down that its very
    # first statement is the unconditional clear. That single choke point is
    # what covers the aiuibuilder free-text branch, the admin web /answer
    # route, and any future caller.
    source = inspect.getsource(routes_execution.resume_with_answer)
    body = source.split('"""', 2)[-1]
    first_stmt = next(line.strip() for line in body.splitlines() if line.strip())
    assert first_stmt == "_clear_prebuild_questions(item)"


# ---------------------------------------------------------------------------
# Finding 2: _run_prebuild_questions_then_build shields its DB writes the
# same way _run_execution does: reset to "pending" on failure, always pop
# _RUNNING.
# ---------------------------------------------------------------------------

class _FakeResult:
    def scalar_one(self):
        return None

    def scalar_one_or_none(self):
        return None


class _FakeSession:
    """Minimal async-context-manager stand-in for db.session().

    `fail=True` makes __aenter__ raise, simulating a DB write blowing up
    inside one of _run_prebuild_questions_then_build's
    `async with session() as s:` blocks, the exact failure Finding 2 flags.
    """

    def __init__(self, executed, fail):
        self._executed = executed
        self._fail = fail

    async def __aenter__(self):
        if self._fail:
            raise RuntimeError("simulated DB write failure")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        self._executed.append(stmt)
        return _FakeResult()

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    def add(self, obj):
        pass


async def test_prebuild_db_write_failure_resets_pending_and_pops_running(monkeypatch):
    executed = []
    calls = {"n": 0}

    def fake_session():
        calls["n"] += 1
        # The first DB block reached after a clean (no-questions) question
        # pass is the build-chain "create new exec" write; make it fail so
        # the outer except must catch it. The except handler's own write
        # (second session() call) is allowed to succeed.
        return _FakeSession(executed, fail=(calls["n"] == 1))

    monkeypatch.setattr(rb, "session", fake_session)

    async def fake_stream_claude(prompt, exec_id, task_id, *a, **k):
        return "NO_QUESTIONS"

    monkeypatch.setattr(routes_execution, "_stream_claude", fake_stream_claude)

    task_id = uuid.uuid4()
    exec_id = uuid.uuid4()
    routes_execution._RUNNING[task_id] = {"task": None}

    # No exception should propagate out.
    await rb._run_prebuild_questions_then_build(
        task_id, exec_id, "prompt text", "build a todo app",
    )

    # The slot must always be released, success or failure.
    assert task_id not in routes_execution._RUNNING

    # The except handler's own DB write must have run and reset the task.
    assert len(executed) == 1
    params = executed[0].compile().params
    assert params["status"] == "pending"
    assert params["mode"] is None


async def test_prebuild_question_pass_failure_still_pops_running(monkeypatch):
    # Belt-and-suspenders: even the pre-existing inner degrade-to-no-questions
    # guard must leave _RUNNING clean if the build chain after it also fails.
    # Only the first session() call (the build-chain write) fails; the
    # except handler's own reset-to-pending write is allowed to succeed.
    executed = []
    calls = {"n": 0}

    def fake_session():
        calls["n"] += 1
        return _FakeSession(executed, fail=(calls["n"] == 1))

    monkeypatch.setattr(rb, "session", fake_session)

    async def raising_stream_claude(prompt, exec_id, task_id, *a, **k):
        raise RuntimeError("subprocess exploded")

    monkeypatch.setattr(routes_execution, "_stream_claude", raising_stream_claude)

    task_id = uuid.uuid4()
    exec_id = uuid.uuid4()
    routes_execution._RUNNING[task_id] = {"task": None}

    await rb._run_prebuild_questions_then_build(
        task_id, exec_id, "prompt text", "build a todo app",
    )

    assert task_id not in routes_execution._RUNNING
    assert len(executed) == 1
    assert executed[0].compile().params["status"] == "pending"
