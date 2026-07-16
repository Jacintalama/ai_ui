"""Unit tests for the post-execution commit sweep (app_git.sweep_app_commit).

Monkeypatches app_git._run_git (the module-level seam) so no real git runs.
Every test asserts on the exact argv handed to git, because the safety of this
feature is entirely about WHICH paths get staged: the same working tree holds
IO's own platform code and the VPS's drift, so a broad `git add` would sweep
unrelated changes into a user's app commit.

Context: 43 of 47 prod apps have zero commits because claude_executor.py:174-183
merely *tells* the agent to commit and nothing verifies it. This sweep is the
verification.
"""
import app_git


def _make_git(responses):
    """Fake _run_git recording argv. `responses` maps the git subcommand
    (first non `-c` arg) to a (returncode, stdout) tuple. Unlisted commands
    return (0, "")."""
    calls = []

    async def _fake(*args, **kwargs):
        calls.append(list(args))
        sub = next((a for i, a in enumerate(args)
                    if not a.startswith("-c") and (i == 0 or args[i - 1] != "-c")), "")
        return responses.get(sub, (0, ""))

    _fake.calls = calls
    return _fake


def _argv_for(calls, sub):
    """The first recorded argv whose subcommand is `sub`."""
    for c in calls:
        if sub in c:
            return c
    return None


# --- the no-op path: the agent did its job ---------------------------------

async def test_sweep_is_noop_when_agent_already_committed(monkeypatch):
    git = _make_git({"status": (0, "")})  # clean tree == agent committed
    monkeypatch.setattr(app_git, "_run_git", git)

    sha = await app_git.sweep_app_commit(
        "my-app", message="Build a coffee shop site", actor_email="a@b.com"
    )

    assert sha is None
    assert _argv_for(git.calls, "commit") is None, "must not create a second commit"
    assert _argv_for(git.calls, "add") is None, "must not stage anything"


# --- the sweep path: the agent did NOT commit ------------------------------

async def test_sweep_commits_when_agent_left_changes_uncommitted(monkeypatch):
    git = _make_git({
        "status": (0, "?? apps/my-app/index.html\n"),
        "rev-parse": (0, "abc1234def\n"),
    })
    monkeypatch.setattr(app_git, "_run_git", git)

    sha = await app_git.sweep_app_commit(
        "my-app", message="Build a coffee shop site", actor_email="a@b.com"
    )

    assert sha == "abc1234def"
    assert _argv_for(git.calls, "add") is not None
    assert _argv_for(git.calls, "commit") is not None


async def test_sweep_never_stages_the_whole_tree(monkeypatch):
    git = _make_git({"status": (0, "?? apps/my-app/index.html\n")})
    monkeypatch.setattr(app_git, "_run_git", git)

    await app_git.sweep_app_commit("my-app", message="x", actor_email="a@b.com")

    for argv in git.calls:
        assert "-A" not in argv, f"broad add would sweep IO's platform code: {argv}"
        assert "--all" not in argv, f"broad add would sweep IO's platform code: {argv}"
        assert "." not in argv, f"broad add would sweep IO's platform code: {argv}"


async def test_sweep_stages_only_the_app_path(monkeypatch):
    git = _make_git({"status": (0, "?? apps/my-app/index.html\n")})
    monkeypatch.setattr(app_git, "_run_git", git)

    await app_git.sweep_app_commit("my-app", message="x", actor_email="a@b.com")

    add = _argv_for(git.calls, "add")
    assert add[-1] == "apps/my-app/"
    assert "--" in add, "pathspec must be separated so a slug can't be read as a flag"


async def test_sweep_commit_is_path_scoped(monkeypatch):
    """`git commit` without a pathspec would commit anything else already
    staged in the shared tree. rollback_app_core gets away with that; the
    sweep runs right after an agent that may have staged anything."""
    git = _make_git({"status": (0, "?? apps/my-app/index.html\n")})
    monkeypatch.setattr(app_git, "_run_git", git)

    await app_git.sweep_app_commit("my-app", message="x", actor_email="a@b.com")

    commit = _argv_for(git.calls, "commit")
    assert commit[-1] == "apps/my-app/"
    assert "--" in commit


async def test_sweep_commits_as_the_task_actor(monkeypatch):
    """VersionEntry.actor_email resolves off the commit author, so the
    timeline shows who caused the change."""
    git = _make_git({"status": (0, "?? apps/my-app/x\n")})
    monkeypatch.setattr(app_git, "_run_git", git)

    await app_git.sweep_app_commit("my-app", message="x", actor_email="jane@b.com")

    commit = _argv_for(git.calls, "commit")
    assert "user.email=jane@b.com" in commit
    assert "user.name=jane" in commit


# --- message safety --------------------------------------------------------

async def test_sweep_still_commits_when_actor_is_unknown(monkeypatch):
    """A task with no assignee must still get its history recorded. Falling
    back to the repo's default git identity beats losing the commit, which is
    the failure this whole feature exists to stop."""
    git = _make_git({
        "status": (0, "?? apps/my-app/x\n"),
        "rev-parse": (0, "deadbee1\n"),
    })
    monkeypatch.setattr(app_git, "_run_git", git)

    sha = await app_git.sweep_app_commit("my-app", message="x", actor_email=None)

    assert sha == "deadbee1"
    commit = _argv_for(git.calls, "commit")
    assert not any(str(a).startswith("user.email=") for a in commit)


async def test_sweep_message_is_the_task_summary(monkeypatch):
    git = _make_git({"status": (0, "?? apps/my-app/x\n")})
    monkeypatch.setattr(app_git, "_run_git", git)

    await app_git.sweep_app_commit(
        "my-app", message="Add a dark mode toggle", actor_email="a@b.com"
    )

    commit = _argv_for(git.calls, "commit")
    assert "Add a dark mode toggle" in commit


async def test_sweep_message_never_starts_with_rollback(monkeypatch):
    """list_app_versions_core marks an entry as a rollback purely by the
    message prefix, so a build summary starting with 'Rollback' would
    mislabel a real build in the timeline."""
    git = _make_git({"status": (0, "?? apps/my-app/x\n")})
    monkeypatch.setattr(app_git, "_run_git", git)

    await app_git.sweep_app_commit(
        "my-app", message="Rollback the header colour", actor_email="a@b.com"
    )

    commit = _argv_for(git.calls, "commit")
    msg = commit[commit.index("-m") + 1]
    assert not msg.startswith("Rollback")
    assert "Rollback the header colour" in msg, "the real summary must survive"


async def test_sweep_truncates_a_long_summary_to_a_git_subject(monkeypatch):
    """Found by the live e2e on 2026-07-16: the agent's completion payload is a
    whole paragraph on one line, so the version timeline rendered a wall of
    text. Git caps a subject at ~72 chars by convention and the timeline shows
    this string directly."""
    long_msg = "Created a single page that says History Works " + "and more " * 40
    git = _make_git({"status": (0, "?? apps/my-app/x\n")})
    monkeypatch.setattr(app_git, "_run_git", git)

    await app_git.sweep_app_commit("my-app", message=long_msg, actor_email="a@b.com")

    commit = _argv_for(git.calls, "commit")
    msg = commit[commit.index("-m") + 1]
    assert len(msg) <= 72, f"timeline subject is {len(msg)} chars: {msg!r}"
    assert msg.startswith("Created a single page that says History Works")
    assert msg.endswith("...")


async def test_sweep_does_not_truncate_a_short_summary(monkeypatch):
    git = _make_git({"status": (0, "?? apps/my-app/x\n")})
    monkeypatch.setattr(app_git, "_run_git", git)

    await app_git.sweep_app_commit(
        "my-app", message="Add a dark mode toggle", actor_email="a@b.com"
    )

    commit = _argv_for(git.calls, "commit")
    msg = commit[commit.index("-m") + 1]
    assert msg == "Add a dark mode toggle"


async def test_sweep_falls_back_to_a_default_message_when_summary_is_empty(monkeypatch):
    git = _make_git({"status": (0, "?? apps/my-app/x\n")})
    monkeypatch.setattr(app_git, "_run_git", git)

    await app_git.sweep_app_commit("my-app", message="", actor_email="a@b.com")

    commit = _argv_for(git.calls, "commit")
    msg = commit[commit.index("-m") + 1]
    assert msg.strip(), "git rejects an empty commit message"


# --- fail open: a build must never fail because the sweep failed -----------

async def test_sweep_fails_open_when_add_fails(monkeypatch):
    git = _make_git({
        "status": (0, "?? apps/my-app/x\n"),
        "add": (1, "fatal: unable to index file"),
    })
    monkeypatch.setattr(app_git, "_run_git", git)

    sha = await app_git.sweep_app_commit("my-app", message="x", actor_email="a@b.com")

    assert sha is None
    assert _argv_for(git.calls, "commit") is None, "must not commit after a failed add"


async def test_sweep_fails_open_when_commit_fails(monkeypatch):
    git = _make_git({
        "status": (0, "?? apps/my-app/x\n"),
        "commit": (1, "fatal: could not commit"),
    })
    monkeypatch.setattr(app_git, "_run_git", git)

    sha = await app_git.sweep_app_commit("my-app", message="x", actor_email="a@b.com")

    assert sha is None


async def test_sweep_fails_open_when_git_raises(monkeypatch):
    async def _boom(*args, **kwargs):
        raise OSError("git binary vanished")
    monkeypatch.setattr(app_git, "_run_git", _boom)

    sha = await app_git.sweep_app_commit("my-app", message="x", actor_email="a@b.com")

    assert sha is None


async def test_sweep_fails_open_when_status_fails(monkeypatch):
    git = _make_git({"status": (128, "fatal: not a git repository")})
    monkeypatch.setattr(app_git, "_run_git", git)

    sha = await app_git.sweep_app_commit("my-app", message="x", actor_email="a@b.com")

    assert sha is None
    assert _argv_for(git.calls, "add") is None


# --- injection guard -------------------------------------------------------

async def test_sweep_rejects_invalid_slug_before_any_git_call(monkeypatch):
    git = _make_git({})
    monkeypatch.setattr(app_git, "_run_git", git)

    sha = await app_git.sweep_app_commit(
        "../../etc/passwd", message="x", actor_email="a@b.com"
    )

    assert sha is None
    assert git.calls == [], "a bad slug must never reach a git path argument"
