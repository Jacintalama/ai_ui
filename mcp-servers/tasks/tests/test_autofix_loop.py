"""Unit tests for the AutoFix loop (_run_autofix) and its prompt builder.

Monkeypatches routes_execution._smoke_app and routes_execution._stream_claude
(the module-level seams) plus routes_execution.session (a fake in-memory
session, since _run_autofix only needs execute()/commit() to succeed - no
real Postgres is required to exercise the loop logic in isolation)."""
import uuid

import routes_execution
from claude_executor import build_autofix_prompt


class _FakeSession:
    """Records executed statements; commit()/execute() are no-ops so the
    loop's log-append can run without a real database."""

    def __init__(self, sink):
        self._sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        self._sink.append(stmt)
        return None

    async def commit(self):
        return None


def _fake_session_factory(sink):
    def _factory():
        return _FakeSession(sink)
    return _factory


def _make_smoke(reports):
    """Returns an async fn that yields each item of `reports` in order,
    then repeats the last item forever."""
    calls = {"n": 0}

    async def _smoke(slug):
        i = min(calls["n"], len(reports) - 1)
        calls["n"] += 1
        return reports[i]

    _smoke.calls = calls
    return _smoke


def _make_stream_claude(recorder):
    async def _stream(prompt, execution_id, task_id, user_jwt=None, schedule_id=None):
        recorder.append(prompt)
        return "TESTS_PASSED: fixed"
    return _stream


async def test_clean_app_skips_autofix_entirely(monkeypatch):
    log_sink = []
    fix_calls = []
    monkeypatch.setattr(routes_execution, "session", _fake_session_factory(log_sink))
    monkeypatch.setattr(routes_execution, "_smoke_app", _make_smoke([None]))
    monkeypatch.setattr(routes_execution, "_stream_claude", _make_stream_claude(fix_calls))

    result = await routes_execution._run_autofix(
        "my-app", uuid.uuid4(), uuid.uuid4(),
    )

    assert result is None
    assert len(fix_calls) == 0
    assert len(log_sink) == 0


async def test_one_transient_error_then_clean(monkeypatch):
    log_sink = []
    fix_calls = []
    monkeypatch.setattr(routes_execution, "session", _fake_session_factory(log_sink))
    monkeypatch.setattr(routes_execution, "_smoke_app", _make_smoke(["- console.error: boom", None]))
    monkeypatch.setattr(routes_execution, "_stream_claude", _make_stream_claude(fix_calls))

    result = await routes_execution._run_autofix(
        "my-app", uuid.uuid4(), uuid.uuid4(),
    )

    assert result is None
    assert len(fix_calls) == 1
    assert "- console.error: boom" in fix_calls[0]
    assert len(log_sink) == 1


async def test_persistent_error_stops_after_max_passes(monkeypatch):
    log_sink = []
    fix_calls = []
    persistent = "- console.error: still broken"
    monkeypatch.setattr(routes_execution, "session", _fake_session_factory(log_sink))
    monkeypatch.setattr(routes_execution, "_smoke_app", _make_smoke([persistent]))
    monkeypatch.setattr(routes_execution, "_stream_claude", _make_stream_claude(fix_calls))

    result = await routes_execution._run_autofix(
        "my-app", uuid.uuid4(), uuid.uuid4(),
    )

    assert result == persistent
    assert len(fix_calls) == routes_execution.AUTOFIX_MAX_PASSES == 2
    assert len(log_sink) == 2


async def test_autofix_prompt_includes_errors_verbatim_and_scope_phrasing():
    errors = "- console.error: TypeError: foo is not a function\n- pageerror: ReferenceError: x"
    prompt = build_autofix_prompt(slug="my-app", errors=errors)

    assert errors in prompt
    assert "my-app" in prompt
    assert "ONLY" in prompt
    assert "smallest" in prompt
    assert "redesign" in prompt.lower()
