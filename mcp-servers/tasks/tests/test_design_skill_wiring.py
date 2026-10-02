"""From the marked job to the run: the column, the spawns, the main run.

The spawns and _run_execution need the database tier to run, so their
wiring is checked here by signature and source, and end to end on the server
(CLAUDE.md: a NameError inside a function body survives an import).
"""
import inspect
import os
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


def test_only_the_main_run_gets_the_design():
    task = SimpleNamespace(design_skill="impeccable")
    assert routes_execution._run_design(task, main_run=True) == "impeccable"
    assert routes_execution._run_design(task, main_run=False) is None
    assert routes_execution._run_design(None, main_run=True) is None
    blank = SimpleNamespace(design_skill="")
    assert routes_execution._run_design(blank, main_run=True) is None


def test_stream_claude_defaults_to_not_the_main_run():
    params = inspect.signature(routes_execution._stream_claude).parameters
    assert params["main_run"].default is False
    assert "design=" in inspect.getsource(routes_execution._stream_claude)


def test_run_execution_marks_exactly_one_call_as_the_main_run():
    # AutoFix, verify, questions and plan runs are narrow jobs; only the run
    # that builds or changes the app (and its retries, which recurse into
    # _run_execution) gets the design rules.
    source = inspect.getsource(routes_execution._run_execution)
    assert source.count("main_run=True") == 1
