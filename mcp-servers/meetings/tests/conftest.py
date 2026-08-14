"""Shared fakes for the meetings tests.

A dev machine has no Postgres, and what these tests check is *what gets
written* rather than SQL, so the session maker is faked over a single
in-memory row. `expire_on_commit=False` in the real session maker means the
production code also works on a detached record, so this is a fair stand-in.
"""
import sys
import pathlib
import uuid
from datetime import datetime

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from models import MeetingRecord  # noqa: E402


class FakeResult:
    def __init__(self, record):
        self._record = record

    def scalar_one_or_none(self):
        return self._record


class FakeSession:
    def __init__(self, holder):
        self.holder = holder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, _stmt):
        return FakeResult(self.holder.record)

    def add(self, record):
        self.holder.record = record

    async def commit(self):
        self.holder.commits += 1

    async def refresh(self, record):
        record.id = record.id or uuid.uuid4()
        record.created_at = record.created_at or datetime.utcnow()
        record.updated_at = record.updated_at or datetime.utcnow()


class Holder:
    """Stands in for `_session_maker`: calling it opens a fake session."""

    def __init__(self, record=None):
        self.record = record
        self.commits = 0

    def __call__(self):
        return FakeSession(self)


def make_record(**kwargs) -> MeetingRecord:
    values = {
        "id": uuid.uuid4(),
        "title": "Standup",
        "date": "2026-05-05",
        "summary": "already summarised, so the AI step is skipped",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    values.update(kwargs)
    return MeetingRecord(**values)


@pytest.fixture
def quiet_decision_engine(monkeypatch):
    """The decision engine posts to Discord; it is not what is under test."""
    import main

    async def _noop(**_kwargs):
        return {"processed": 0, "results": []}

    monkeypatch.setattr(main, "process_action_items", _noop)
