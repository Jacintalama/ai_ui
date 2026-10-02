"""From the marked job to the run: the column, the spawns, the main run.

The spawns and _run_execution need the database tier to run, so their
wiring is checked here by signature and source, and end to end on the server
(CLAUDE.md: a NameError inside a function body survives an import).
"""
import inspect
import os
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import routes_aiuibuilder
import routes_execution
from models import TaskItem

HERE = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS = os.path.join(HERE, "..", "migrations")


def test_the_migration_adds_a_nullable_column_idempotently():
    sql = open(os.path.join(MIGRATIONS, "053_task_design_skill.sql"),
               encoding="utf-8").read()
    assert ("ALTER TABLE tasks.items ADD COLUMN IF NOT EXISTS "
            "design_skill TEXT;") in sql
    down = open(os.path.join(MIGRATIONS, "rollbacks",
                             "053_task_design_skill.down.sql"),
                encoding="utf-8").read()
    assert "DROP COLUMN IF EXISTS design_skill" in down


def test_the_model_has_the_column():
    column = TaskItem.__table__.columns["design_skill"]
    assert column.nullable


@pytest.mark.parametrize("fn", [
    routes_aiuibuilder._create_and_spawn_build,
    routes_aiuibuilder._create_and_spawn_enhance,
])
def test_both_spawns_take_the_mark_and_store_it(fn):
    assert inspect.signature(fn).parameters["design_skill"].default is None
    assert "design_skill=design_skill," in inspect.getsource(fn)


def _task(design="impeccable", attempt=0):
    return SimpleNamespace(design_skill=design, attempt_count=attempt,
                           built_app_slug="crumb-and-co")


def test_only_the_first_main_run_gets_the_design():
    assert routes_execution._run_design(_task(), main_run=True) == "impeccable"
    assert routes_execution._run_design(_task(), main_run=False) is None
    assert routes_execution._run_design(None, main_run=True) is None
    assert routes_execution._run_design(_task(""), main_run=True) is None


def test_a_retry_runs_without_the_design():
    # Each marked attempt may spend the whole cap, so retrying with the
    # design rules could spend three caps and still keep nothing. A retry
    # exists to get the person a working app; it runs as builds always have.
    assert routes_execution._run_design(_task(attempt=1), main_run=True) is None


def test_stream_claude_defaults_to_not_the_main_run():
    params = inspect.signature(routes_execution._stream_claude).parameters
    assert params["main_run"].default is False


class _Session:
    """Answers every query with the given task and records each statement."""

    def __init__(self, task, statements):
        self._task, self._statements = task, statements

    async def execute(self, statement, *a, **k):
        self._statements.append(statement)
        task = self._task
        return SimpleNamespace(scalar_one_or_none=lambda: task)

    async def commit(self):
        return None


class _Executor:
    def __init__(self, seen):
        self._seen = seen

    async def run(self, prompt, **kwargs):
        self._seen.append(kwargs)
        for chunk in ("a", "b"):
            yield chunk

    async def stop(self):
        return None


def _drive(monkeypatch, task):
    statements, seen = [], []

    @asynccontextmanager
    async def _session():
        yield _Session(task, statements)

    @asynccontextmanager
    async def _no_lock(_s):
        yield

    monkeypatch.setattr(routes_execution, "session", _session)
    monkeypatch.setattr(routes_execution, "heavy_lock", _no_lock)
    monkeypatch.setattr(routes_execution, "get_executor",
                        lambda: _Executor(seen))
    return statements, seen


def _logged(statements, text):
    for statement in statements:
        try:
            params = statement.compile().params
        except Exception:                                   # noqa: BLE001
            continue
        if any(text in str(v) for v in params.values()):
            return True
    return False


async def test_a_marked_run_gets_the_design_and_says_so_in_the_log(
        monkeypatch):
    statements, seen = _drive(monkeypatch, _task())
    out = await routes_execution._stream_claude(
        "p", uuid.uuid4(), uuid.uuid4(), main_run=True)
    assert seen[0]["design"] == "impeccable"
    assert _logged(statements, "[design skill: impeccable]")
    # The returned output is what the outcome parser reads. A line in front
    # of it changes parse_outcome's fallback for a run with no text.
    assert out == "ab"


@pytest.mark.parametrize("task,main_run", [
    (_task(), False), (_task(attempt=1), True), (_task(None), True),
])
async def test_an_unmarked_run_calls_the_executor_as_before(
        monkeypatch, task, main_run):
    statements, seen = _drive(monkeypatch, task)
    out = await routes_execution._stream_claude(
        "p", uuid.uuid4(), uuid.uuid4(), main_run=main_run)
    assert "design" not in seen[0]
    assert not _logged(statements, "[design skill")
    assert out == "ab"


def test_run_execution_marks_exactly_one_call_as_the_main_run():
    # AutoFix, verify, questions and plan runs are narrow jobs; only the run
    # that builds or changes the app (and its retries, which recurse into
    # _run_execution) gets the design rules.
    source = inspect.getsource(routes_execution._run_execution)
    assert source.count("main_run=True") == 1
