"""The build/enhance prompt templates must include Supabase context when configured."""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

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


def test_build_prompt_omits_sql_tool_when_no_db_uri():
    text = build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-04-25",
        supabase_url="https://demo.supabase.co",
        has_db_uri=False,
    )
    # Supabase block is present, but no SQL-execute tool instructions.
    assert "Supabase integration available" in text
    assert "/db/sql" not in text


def test_build_prompt_includes_sql_tool_when_db_uri_configured():
    text = build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-04-25",
        supabase_url="https://demo.supabase.co",
        has_db_uri=True,
    )
    assert "/db/sql" in text
    # Must give Claude clear instructions:
    assert "CREATE TABLE" in text or "create tables" in text.lower()
    assert "POST" in text or "curl" in text.lower()
    # Must NOT instruct user to copy SQL — Claude does it itself.
    assert "ask the user" not in text.lower() or "do not ask the user" in text.lower()


def test_enhance_prompt_includes_sql_tool_when_db_uri_configured():
    text = build_enhance_prompt(
        slug="alpha",
        user_request="add a tasks table with RLS",
        attempt_count=0,
        max_attempts=3,
        error_context="",
        supabase_url="https://demo.supabase.co",
        has_db_uri=True,
    )
    assert "/db/sql" in text