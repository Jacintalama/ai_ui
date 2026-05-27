from claude_executor import _ensure_gitignore_attachments, build_prompt, parse_outcome


def test_build_prompt_includes_task_fields():
    p = build_prompt(
        description="Fix routing",
        action_type="BUILD",
        priority="CRITICAL",
        meeting_title="Standup",
        meeting_date="Apr 8",
    )
    assert "Fix routing" in p and "BUILD" in p and "CRITICAL" in p and "Standup" in p


def test_parse_completed():
    o = parse_outcome("Did the work.\nCOMPLETED: Updated Caddyfile and reloaded.")
    assert o.kind == "completed"
    assert o.payload == "Updated Caddyfile and reloaded."


def test_parse_needs_input():
    o = parse_outcome("Looked at it.\nNEEDS_INPUT: What's the Trello API token?")
    assert o.kind == "needs_input"
    assert "Trello API token" in o.payload


def test_parse_needs_steps():
    o = parse_outcome("NEEDS_STEPS: 1. Open Caddyfile\n2. Edit\n3. Reload")
    assert o.kind == "needs_steps"
    assert o.payload.startswith("1. Open Caddyfile")


def test_parse_no_sentinel_treated_as_failed():
    o = parse_outcome("I tried but I'm confused.")
    assert o.kind == "failed"


def test_parse_completed_with_dash_separator_no_colon():
    """Claude sometimes writes `--- COMPLETED Built apps/foo/` instead of the
    strict `COMPLETED:` form. Without tolerance, the build looks `failed`,
    routes_execution flips status to `pending`, and the build overlay sticks
    on the QUEUED chip even though the agent finished successfully. Real log
    that triggered the prod incident: `--- COMPLETED Built apps/portfolio/`."""
    o = parse_outcome(
        "Wrote files.\n--- COMPLETED Built `apps/portfolio/` - portfolio site"
    )
    assert o.kind == "completed"
    assert "portfolio" in o.payload


def test_parse_completed_keyword_only_space():
    """Bare `COMPLETED <text>` (no colon, no `---`) is also tolerated —
    same forgiving behavior, prevents stuck-on-QUEUED for any sentinel
    that happens to drop punctuation."""
    o = parse_outcome("Did stuff.\nCOMPLETED Built the thing")
    assert o.kind == "completed"
    assert o.payload == "Built the thing"


def test_parse_does_not_match_keyword_inside_word():
    """Word-boundary anchor: `PRECOMPLETED` shouldn't trigger, otherwise
    real prose with these words concatenated could falsely complete a task."""
    o = parse_outcome("Status: PRECOMPLETED phase pending review.")
    assert o.kind == "failed"


def test_parse_picks_last_sentinel_when_both_forms_present():
    """If the agent uses both forms (e.g. mid-stream `--- COMPLETED` plus a
    final `COMPLETED:` block), the LAST one wins — same as before."""
    text = (
        "--- COMPLETED Built foo\n"
        "Then I noticed an issue and fixed it.\n"
        "COMPLETED: Final summary."
    )
    o = parse_outcome(text)
    assert o.kind == "completed"
    assert o.payload == "Final summary."


# ---------------------------------------------------------------------------
# _ensure_gitignore_attachments
# ---------------------------------------------------------------------------
# The agent commits app changes after each successful build/enhance. Without a
# per-app .gitignore line for `.attachments/`, image blobs uploaded via
# /api/tasks/enhance end up in the build's commit history.

def test_ensure_gitignore_attachments_creates_file_when_missing(tmp_path):
    """Fresh app with no .gitignore — helper creates one with `.attachments/`."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()

    _ensure_gitignore_attachments(app_dir)

    gitignore = app_dir / ".gitignore"
    assert gitignore.exists()
    assert ".attachments/" in gitignore.read_text(encoding="utf-8").splitlines()


def test_ensure_gitignore_attachments_appends_to_existing(tmp_path):
    """Existing .gitignore without `.attachments/` — helper appends the line
    and adds a leading newline if the existing file doesn't end with one.
    """
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    gitignore = app_dir / ".gitignore"
    # No trailing newline on purpose — helper must add one before appending.
    gitignore.write_text("node_modules/\n*.log", encoding="utf-8")

    _ensure_gitignore_attachments(app_dir)

    text = gitignore.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "node_modules/" in lines
    assert "*.log" in lines
    assert ".attachments/" in lines
    # Leading newline was injected since original didn't end with \n.
    assert "*.log\n.attachments/" in text


def test_ensure_gitignore_attachments_idempotent(tmp_path):
    """Running the helper twice does not duplicate the `.attachments/` line."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()

    _ensure_gitignore_attachments(app_dir)
    _ensure_gitignore_attachments(app_dir)

    text = (app_dir / ".gitignore").read_text(encoding="utf-8")
    assert text.count(".attachments/") == 1


def test_ensure_gitignore_attachments_already_present_is_noop(tmp_path):
    """If the line is already there (with surrounding entries), the file is
    left untouched."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    gitignore = app_dir / ".gitignore"
    original = "node_modules/\n.attachments/\n*.log\n"
    gitignore.write_text(original, encoding="utf-8")

    _ensure_gitignore_attachments(app_dir)

    assert gitignore.read_text(encoding="utf-8") == original


def test_ensure_gitignore_attachments_skips_when_app_dir_missing(tmp_path):
    """If the app dir doesn't exist (defensive), helper is a no-op — does
    NOT create either the dir or a stray .gitignore at the parent."""
    missing = tmp_path / "ghost-app"

    _ensure_gitignore_attachments(missing)

    assert not missing.exists()
    assert not (tmp_path / ".gitignore").exists()
