"""The build/enhance prompt templates must include Supabase context when configured."""
import os

os.environ.setdefault("AIUI_FERNET_KEY", "v3KGZ9ZpQAQ-HeaR_R-nXvI3T8cPOFYYJQHe3VJYJpw=")

from claude_executor import build_prompt, build_enhance_prompt


def test_build_prompt_omits_block_when_no_supabase():
    text = build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-04-25",
        supabase_url=None,
    )
    assert "Supabase" not in text


def test_build_prompt_includes_block_when_supabase_configured():
    text = build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-04-25",
        supabase_url="https://demo.supabase.co",
    )
    assert "Supabase integration available" in text
    assert "window.SUPABASE_URL" in text
    assert "window.SUPABASE_ANON_KEY" in text
    assert "https://demo.supabase.co" in text
    assert "RLS" in text or "Row Level Security" in text


def test_enhance_prompt_includes_block_when_supabase_configured():
    text = build_enhance_prompt(
        slug="alpha",
        user_request="add a login form",
        attempt_count=0,
        max_attempts=3,
        supabase_url="https://demo.supabase.co",
    )
    assert "Supabase integration available" in text
    assert "https://demo.supabase.co" in text
