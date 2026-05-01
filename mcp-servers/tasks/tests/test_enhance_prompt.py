import pytest
from claude_executor import build_enhance_prompt, ENHANCE_PROMPT_TEMPLATE
from schemas import EnhanceRequest


def test_enhance_request_validates_non_empty_prompt():
    with pytest.raises(Exception):
        EnhanceRequest(source_task_id="00000000-0000-0000-0000-000000000001", prompt="")


def test_enhance_request_rejects_too_long_prompt():
    with pytest.raises(Exception):
        EnhanceRequest(
            source_task_id="00000000-0000-0000-0000-000000000001",
            prompt="x" * 2001,
        )


def test_build_enhance_prompt_includes_slug_and_user_request():
    out = build_enhance_prompt(
        slug="meeting-notes",
        user_request="add attendees field",
        attempt_count=0,
        max_attempts=3,
    )
    assert "apps/meeting-notes/" in out
    assert "add attendees field" in out


def test_build_enhance_prompt_forbids_stack_pivot():
    out = build_enhance_prompt(
        slug="todo-list",
        user_request="add dark mode",
        attempt_count=0,
        max_attempts=3,
    )
    # Must warn against replacing stack
    assert "preserve the existing tech stack" in out.lower()


def test_build_enhance_prompt_requires_tdd():
    out = build_enhance_prompt(
        slug="x",
        user_request="y",
        attempt_count=0,
        max_attempts=3,
    )
    assert "red-green-refactor" in out.lower() or "red" in out.lower()


def test_build_enhance_prompt_retry_context_appears_on_retry():
    out = build_enhance_prompt(
        slug="x",
        user_request="y",
        attempt_count=1,
        max_attempts=3,
        error_context="Previous test failed: missing import",
    )
    assert "Previous test failed: missing import" in out
    assert "1/3" in out or "attempt 1" in out.lower()


def test_build_enhance_prompt_no_attachments_omits_stanza():
    from claude_executor import build_enhance_prompt
    out = build_enhance_prompt(
        slug="meeting-notes",
        user_request="add a header",
        attempt_count=0,
        max_attempts=3,
        supabase_url=None,
        has_db_uri=False,
        user_email="r@x.com",
    )
    assert "Attached images" not in out


def test_build_enhance_prompt_with_attachments_includes_stanza():
    from claude_executor import build_enhance_prompt
    out = build_enhance_prompt(
        slug="meeting-notes",
        user_request="match this layout",
        attempt_count=0,
        max_attempts=3,
        supabase_url=None,
        has_db_uri=False,
        user_email="r@x.com",
        attachments=[
            "apps/meeting-notes/.attachments/abc-123/shot.png",
            "apps/meeting-notes/.attachments/abc-123/mockup.jpg",
        ],
    )
    assert "Attached images" in out
    assert "Read them with your Read tool" in out
    assert "apps/meeting-notes/.attachments/abc-123/shot.png" in out
    assert "apps/meeting-notes/.attachments/abc-123/mockup.jpg" in out


def test_attachments_stanza_uses_slugged_paths_not_bare_attachments():
    """Prompt's attachment paths must resolve from agent CWD (CLAUDE_WORKSPACE).

    Agent runs with CWD = CLAUDE_SANDBOX_DIR or CLAUDE_WORKSPACE. Files land
    under apps/<slug>/.attachments/<task_id>/<name>. A bare `.attachments/...`
    path would resolve to CLAUDE_WORKSPACE/.attachments/... which doesn't exist
    and would silently break vision input.
    """
    from claude_executor import build_enhance_prompt
    out = build_enhance_prompt(
        slug="meeting-notes",
        user_request="x",
        attempt_count=0,
        max_attempts=3,
        supabase_url=None,
        has_db_uri=False,
        user_email="r@x.com",
        attachments=["apps/meeting-notes/.attachments/abc/shot.png"],
    )
    assert "apps/meeting-notes/.attachments/abc/shot.png" in out
    # And the bare form must NOT appear (would resolve wrong from agent CWD)
    assert "\n- .attachments/" not in out
