"""The build/enhance prompt templates must include Supabase context when configured."""
import claude_executor as ce
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
    # The base prompt may mention Supabase in passing ("or Supabase if
    # attached"); what must be absent is the integration block itself.
    assert "Supabase integration available" not in text
    assert "window.SUPABASE_URL" not in text
    assert "window.SUPABASE_ANON_KEY" not in text


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

# --- which projects actually get the SQL tool + mandatory-RLS rules ---------
# Bug found 2026-07-23. _lookup_supabase_config computed the flag as
# bool(db_uri_encrypted), but routes_db.execute_sql has TWO paths and PREFERS
# OAuth:
#     if row.oauth_access_token_encrypted and row.linked_project_ref: -> Mgmt API
#     if row.db_uri_encrypted:                                        -> asyncpg
# So an OAuth-linked project CAN run SQL, but the agent was never told the tool
# existed and never saw the "RLS is MANDATORY" block. The gate was on the
# mechanism (db_uri) instead of the capability (can we execute SQL).
# Zero prod projects were linked when this was found, so no user was affected -
# it would have bitten the first person to link via OAuth, the low-friction path.

def test_sql_tool_available_with_db_uri_only():
    assert ce.sql_tool_available(
        db_uri=True, oauth_token=False, project_ref=False) is True


def test_sql_tool_available_with_oauth_only():
    """The regression: OAuth alone is enough, routes_db prefers this path."""
    assert ce.sql_tool_available(
        db_uri=False, oauth_token=True, project_ref=True) is True


def test_sql_tool_unavailable_with_neither():
    assert ce.sql_tool_available(
        db_uri=False, oauth_token=False, project_ref=False) is False


def test_oauth_token_without_project_ref_is_not_enough():
    """routes_db requires BOTH for the Management API path."""
    assert ce.sql_tool_available(
        db_uri=False, oauth_token=True, project_ref=False) is False
    assert ce.sql_tool_available(
        db_uri=False, oauth_token=False, project_ref=True) is False


def test_oauth_linked_project_gets_the_mandatory_rls_block():
    """The whole point: an OAuth-linked project must see the RLS rules."""
    text = build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-04-25",
        supabase_url="https://demo.supabase.co",
        has_db_uri=ce.sql_tool_available(
            db_uri=False, oauth_token=True, project_ref=True),
    )
    assert "/db/sql" in text
    assert "ROW LEVEL SECURITY" in text
