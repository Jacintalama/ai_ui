"""Unit tests for the enhance regression guard (app_regression).

An enhance that trades a working app for a broken one currently ships. AutoFix
asks "does it load now?", never "does it still do what it did before?". This
guard adds the comparison: smoke BEFORE the agent runs, compare AFTER, and put
the app back when a working app came out broken.

Monkeypatches the module-level seams (_smoke_app, _run_git, _rollback) so no
browser, no git and no LLM are involved. See
docs/superpowers/specs/2026-07-17-enhance-regression-guard-design.md
"""
import pathlib

import app_regression


# --- the wiring actually resolves ------------------------------------------
# Caught by the live e2e on 2026-07-17, not by a unit test: routes_execution
# called effective_slug() without importing it. `python -c "import
# routes_execution"` passed, because a NameError inside a function body only
# fires when that line RUNS - and the enhance path has no unit test that runs
# it. The real enhance died with "name 'effective_slug' is not defined".

def _unresolved_called_names(module_path: str, module_obj) -> list[str]:
    """Bare function names CALLED in a module that resolve to nothing.

    Deliberately narrow: only `foo(...)` call sites, not every name load, so it
    stays simple and produces no false positives from locals. That is exactly
    the shape of the bug it exists to catch.
    """
    import ast
    import builtins

    tree = ast.parse(pathlib.Path(module_path).read_text(encoding="utf-8"))
    local_names = {
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    # Any name bound anywhere in the module, at any scope (params, assignments,
    # comprehensions, with/except aliases). A call to one of those is fine.
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            local_names.add(n.id)
        elif isinstance(n, ast.arg):
            local_names.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            # Includes imports made INSIDE function bodies (routes_execution
            # does `from routes_projects import _require_role` in three
            # handlers). Those never appear in dir(module), so relying on the
            # module namespace alone reports them as missing.
            for alias in n.names:
                local_names.add((alias.asname or alias.name).split(".")[0])

    known = set(dir(module_obj)) | set(dir(builtins)) | local_names
    return sorted({
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id not in known
    })


def test_every_function_routes_execution_calls_actually_exists():
    """routes_execution called effective_slug() without importing it. Importing
    the module did not catch it, because a NameError inside a function body only
    fires when that line RUNS, and no unit test exercises the enhance path."""
    import routes_execution

    missing = _unresolved_called_names(routes_execution.__file__, routes_execution)

    assert missing == [], f"called but never defined or imported: {missing}"


# --- helpers ---------------------------------------------------------------

def _smoke_returning(*reports):
    """Async _smoke_app yielding each report in turn, repeating the last."""
    calls = {"n": 0}

    async def _smoke(slug):
        i = min(calls["n"], len(reports) - 1)
        calls["n"] += 1
        return reports[i]

    _smoke.calls = calls
    return _smoke


def _git_with_history(sha="abc1234", has_commits=True):
    async def _fake(*args, **kwargs):
        if "rev-parse" in args:
            return 0, f"{sha}\n"
        if "log" in args:
            return 0, (f"{sha} some earlier commit\n" if has_commits else "")
        return 0, ""
    return _fake


def _recording_rollback(result=None):
    calls = []

    async def _rollback(slug, sha, actor_email):
        calls.append({"slug": slug, "sha": sha, "actor_email": actor_email})
        return result or {"ok": True, "noop": False}

    _rollback.calls = calls
    return _rollback


# --- capturing the baseline ------------------------------------------------

async def test_baseline_records_clean_app_and_its_sha(monkeypatch):
    monkeypatch.setattr(app_regression, "_smoke_app", _smoke_returning(None))
    monkeypatch.setattr(app_regression, "_run_git", _git_with_history("deadbee"))

    base = await app_regression.capture_baseline("my-app")

    assert base is not None
    assert base.was_clean is True
    assert base.sha == "deadbee"


async def test_baseline_records_an_already_broken_app(monkeypatch):
    monkeypatch.setattr(app_regression, "_smoke_app",
                        _smoke_returning("- console.error: already broken"))
    monkeypatch.setattr(app_regression, "_run_git", _git_with_history())

    base = await app_regression.capture_baseline("my-app")

    assert base is not None
    assert base.was_clean is False


async def test_baseline_is_skipped_when_the_app_has_no_history(monkeypatch):
    """Nothing to restore, so the guard must not arm itself."""
    monkeypatch.setattr(app_regression, "_smoke_app", _smoke_returning(None))
    monkeypatch.setattr(app_regression, "_run_git",
                        _git_with_history(has_commits=False))

    assert await app_regression.capture_baseline("my-app") is None


async def test_baseline_fails_open_when_the_smoke_check_raises(monkeypatch):
    async def _boom(slug):
        raise RuntimeError("playwright exploded")
    monkeypatch.setattr(app_regression, "_smoke_app", _boom)
    monkeypatch.setattr(app_regression, "_run_git", _git_with_history())

    assert await app_regression.capture_baseline("my-app") is None


async def test_baseline_fails_open_when_git_raises(monkeypatch):
    async def _boom(*args, **kwargs):
        raise OSError("git vanished")
    monkeypatch.setattr(app_regression, "_smoke_app", _smoke_returning(None))
    monkeypatch.setattr(app_regression, "_run_git", _boom)

    assert await app_regression.capture_baseline("my-app") is None


# --- the decision ----------------------------------------------------------

def test_clean_then_broken_is_a_regression():
    base = app_regression.Baseline(was_clean=True, sha="abc1234")
    assert app_regression.is_regression(base, "- pageerror: boom") is True


def test_broken_then_broken_is_not_a_regression():
    """The app was already failing. The enhance may well be the fix, so
    reverting it would undo an attempted repair."""
    base = app_regression.Baseline(was_clean=False, sha="abc1234")
    assert app_regression.is_regression(base, "- pageerror: boom") is False


def test_clean_then_clean_is_not_a_regression():
    base = app_regression.Baseline(was_clean=True, sha="abc1234")
    assert app_regression.is_regression(base, None) is False


def test_broken_then_clean_is_not_a_regression():
    """The enhance fixed it. Obviously keep it."""
    base = app_regression.Baseline(was_clean=False, sha="abc1234")
    assert app_regression.is_regression(base, None) is False


def test_no_baseline_is_never_a_regression():
    """A fresh build, or an app with no history, has nothing to compare."""
    assert app_regression.is_regression(None, "- pageerror: boom") is False


# --- reverting -------------------------------------------------------------

async def test_revert_rolls_back_to_the_captured_sha(monkeypatch):
    rollback = _recording_rollback()
    monkeypatch.setattr(app_regression, "_rollback", rollback)
    base = app_regression.Baseline(was_clean=True, sha="abc1234")

    await app_regression.revert_regression(
        "my-app", base, "- pageerror: boom", actor_email="jane@b.com",
    )

    assert len(rollback.calls) == 1
    assert rollback.calls[0]["slug"] == "my-app"
    assert rollback.calls[0]["sha"] == "abc1234"
    assert rollback.calls[0]["actor_email"] == "jane@b.com"


async def test_revert_returns_a_message_naming_what_broke(monkeypatch):
    monkeypatch.setattr(app_regression, "_rollback", _recording_rollback())
    base = app_regression.Baseline(was_clean=True, sha="abc1234")

    msg = await app_regression.revert_regression(
        "my-app", base, "- console.error: cart is not defined",
        actor_email="a@b.com",
    )

    assert msg is not None
    assert "cart is not defined" in msg, "the user must see WHAT broke"
    assert "version history" in msg.lower(), "and that the attempt is recoverable"


async def test_revert_message_does_not_start_with_the_reserved_rollback_prefix(monkeypatch):
    """list_app_versions_core marks a version as a rollback purely by a
    'Rollback' message prefix. This string is the task RESULT shown to the
    user, not a commit subject, but keeping it distinct avoids confusion with
    the commit rollback_app_core itself writes."""
    monkeypatch.setattr(app_regression, "_rollback", _recording_rollback())
    base = app_regression.Baseline(was_clean=True, sha="abc1234")

    msg = await app_regression.revert_regression(
        "my-app", base, "- pageerror: boom", actor_email="a@b.com",
    )

    assert not msg.startswith("Rollback")


async def test_revert_fails_open_when_rollback_raises(monkeypatch):
    """A failed revert must not fail the build. The app stays as the enhance
    left it, which is exactly where it would have been without this guard."""
    async def _boom(slug, sha, actor_email):
        raise RuntimeError("git checkout failed")
    monkeypatch.setattr(app_regression, "_rollback", _boom)
    base = app_regression.Baseline(was_clean=True, sha="abc1234")

    msg = await app_regression.revert_regression(
        "my-app", base, "- pageerror: boom", actor_email="a@b.com",
    )

    assert msg is None


# --- which app the post-build steps act on ---------------------------------
# Found by the live e2e on 2026-07-17. routes_execution derived the slug ONLY
# from the agent's completion text (`extract_app_slug(full_output)`), and
# routes_execution.py:431-435 already documents that "Claude's completion
# message for a tweak rarely repeats the `apps/<slug>/` path". So on a real
# enhance the slug came back None, which silently skipped AutoFix, the docs
# sweep, the commit sweep AND this regression guard. Measured on prod: the
# enhance changed index.html, autofix ran 0 times, and nothing was committed.
# The task already knows its own slug; use it as the fallback.

def test_effective_slug_prefers_what_the_agent_actually_wrote():
    assert app_regression.effective_slug("agent-said", "task-knows") == "agent-said"


def test_effective_slug_falls_back_to_the_task_when_the_agent_stays_quiet():
    """The enhance case: the agent tweaks a file and never names the path."""
    assert app_regression.effective_slug(None, "task-knows") == "task-knows"


def test_effective_slug_treats_empty_string_as_quiet():
    assert app_regression.effective_slug("", "task-knows") == "task-knows"


def test_effective_slug_is_none_when_neither_knows():
    assert app_regression.effective_slug(None, "") is None
    assert app_regression.effective_slug(None, None) is None


# --- what the user actually ends up reading ---------------------------------

def test_result_is_the_agent_summary_when_all_is_well():
    assert app_regression.compose_result(
        "Added a dark mode toggle", smoke_report=None, revert_message=None,
    ) == "Added a dark mode toggle"


def test_result_appends_unresolved_errors_when_autofix_gave_up():
    """Existing behaviour, preserved: a build that still has errors says so."""
    out = app_regression.compose_result(
        "Added a toggle", smoke_report="- console.error: boom", revert_message=None,
    )
    assert "Added a toggle" in out
    assert "AutoFix could not resolve" in out
    assert "boom" in out


def test_revert_message_replaces_the_summary_entirely():
    """A reverted enhance did NOT do what the summary claims, so leading with
    'Added a toggle' would be a lie about the app's current state."""
    out = app_regression.compose_result(
        "Added a toggle",
        smoke_report="- console.error: boom",
        revert_message="Reverted: this change broke the app...",
    )
    assert out.startswith("Reverted:")
    assert "Added a toggle" not in out
    assert "AutoFix could not resolve" not in out


async def test_revert_reports_nothing_when_rollback_was_a_noop(monkeypatch):
    """rollback_app_core returns noop=True when the target SHA already matches
    the files. Nothing changed, so claiming a revert would be a lie."""
    monkeypatch.setattr(app_regression, "_rollback",
                        _recording_rollback({"ok": True, "noop": True}))
    base = app_regression.Baseline(was_clean=True, sha="abc1234")

    msg = await app_regression.revert_regression(
        "my-app", base, "- pageerror: boom", actor_email="a@b.com",
    )

    assert msg is None
