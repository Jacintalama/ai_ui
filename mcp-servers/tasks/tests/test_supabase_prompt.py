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


# --- roles: the change must be ADDITIVE ------------------------------------
# Lukas, standup 2026-07-30: "they can have admins ... I bet the builder then
# knows how to create admins and regular users." It did not - the RLS block
# offered exactly two policy shapes and neither covered "admin sees all".
# These two tests pin the pre-existing shapes so adding a third cannot quietly
# drop them.

def _sql_prompt() -> str:
    """The build prompt WITH the SQL tool block (OAuth-linked project)."""
    return build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-07-30",
        supabase_url="https://demo.supabase.co",
        has_db_uri=ce.sql_tool_available(
            db_uri=False, oauth_token=True, project_ref=True),
    )


def test_no_auth_policy_shape_survives():
    assert "allow_all_anon" in _sql_prompt()


def test_single_user_policy_shape_survives():
    assert "user_owns_row" in _sql_prompt()


def test_admin_or_owner_policy_shape_is_taught():
    """The third shape: admin sees all, owner sees own."""
    text = _sql_prompt()
    assert "public.is_admin()" in text
    assert "user_id = auth.uid() OR public.is_admin()" in text


def test_is_admin_is_security_definer():
    """Load-bearing, not stylistic: without SECURITY DEFINER a policy on
    profiles that queries profiles recurses. Proven in the recipe scripts."""
    text = _sql_prompt()
    assert "SECURITY DEFINER" in text
    assert "search_path = public, pg_temp" in text


def test_first_signup_becomes_admin_trigger_is_taught():
    """At build time no user exists, so 'who is the admin' has no answer.
    First-signup-wins bootstraps it with no manual step."""
    text = _sql_prompt()
    assert "on_auth_user_created" in text
    assert "handle_new_user" in text


def test_admins_can_appoint_admins():
    """Without an UPDATE policy, RLS default-deny blocks role changes for
    EVERYONE including admins, so only the first signup could ever be admin.
    Found by running the recipe, not by reading it."""
    text = _sql_prompt()
    assert "profiles_admin_manages" in text
    assert "FOR UPDATE TO authenticated" in text


def test_roles_recipe_is_gated_behind_the_sql_tool():
    """No SQL tool means the agent cannot create tables at all, so the recipe
    must not appear and waste context."""
    text = build_prompt(
        description="x", action_type="BUILD", priority="IMPORTANT",
        meeting_title="m", meeting_date="2026-07-30",
        supabase_url="https://demo.supabase.co",
        has_db_uri=False,
    )
    assert "public.is_admin()" not in text
    assert "on_auth_user_created" not in text


def test_recipe_defines_is_admin_before_any_policy_uses_it():
    """Order matters: a policy referencing is_admin() before the function
    exists fails at execution. Guards a future edit reordering the block."""
    text = _sql_prompt()
    definition = text.index("CREATE FUNCTION public.is_admin()")
    first_use = text.index("public.is_admin())")
    assert definition < first_use


def test_every_create_table_in_the_recipe_enables_rls():
    """A future edit must not add a table to the recipe without RLS."""
    text = _sql_prompt()
    assert text.count("CREATE TABLE profiles") == 1
    assert "ALTER TABLE profiles ENABLE ROW LEVEL SECURITY" in text


def test_taught_sql_matches_the_proven_recipe():
    """The recipe was proven against a real Postgres BEFORE being taught
    (docs/superpowers/scripts/2026-07-30-prove-*.sql). If the prompt text drifts
    from what was proven, the agent emits untested SQL against a real user's
    database. This is the whole point of the exercise."""
    import pathlib
    import pytest
    # Walk UP for the scripts dir instead of hardcoding parents[3]. In the
    # container this file is /app/tests/..., which has only three parents, so
    # parents[3] raises IndexError rather than reaching the skip below. Fourth
    # time this repo has been bitten by a test assuming the local layout.
    scripts = None
    for parent in pathlib.Path(__file__).resolve().parents:
        candidate = parent / "docs" / "superpowers" / "scripts"
        if candidate.is_dir():
            scripts = candidate
            break
    if scripts is None:
        pytest.skip("proof scripts not present (expected in the container)")
    proven = " ".join(
        " ".join(p.read_text(encoding="utf-8").split())
        for p in sorted(scripts.glob("2026-07-30-prove-*.sql"))
    )
    taught = " ".join(_sql_prompt().split())

    for fragment in (
        "SECURITY DEFINER",
        "search_path = public, pg_temp",
        "role IN ('admin', 'user')",
        "id = auth.uid() OR public.is_admin()",
        "user_id = auth.uid() OR public.is_admin()",
        # Full statements, not bare identifiers: "guard_role_change" is a
        # substring of "guard_role_changeX", so an identifier alone does NOT
        # detect drift. Verified by mutation.
        "CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users",
        "CREATE OR REPLACE FUNCTION public.handle_new_user() RETURNS trigger",
        "CREATE FUNCTION public.guard_role_change() RETURNS trigger",
        "CREATE TRIGGER profiles_guard_role BEFORE UPDATE ON profiles",
        "ENABLE ROW LEVEL SECURITY;",
    ):
        norm = " ".join(fragment.split())
        assert norm in proven, f"{fragment!r} is not in any PROVEN script"
        assert norm in taught, f"{fragment!r} is not in the TAUGHT prompt"


def test_hardening_from_the_review_is_taught():
    """Each of these was a measured hole, not a hypothetical."""
    text = _sql_prompt()
    # a policy without enable-RLS is inert: staff saw 2 of 2 rows
    assert "is INERT without step 8b" in text or "ENABLE ROW LEVEL SECURITY;" in text
    # a leftover allow_all_anon ORs: an anon visitor read 2 of 2 rows
    assert "DROP POLICY IF EXISTS" in text
    # a raise inside the signup transaction blocks sign-up entirely
    assert "ON CONFLICT (id) DO NOTHING" in text
    # enhancing an app with existing users would crown the wrong admin
    assert "backfill" in text.lower()


def test_recipe_warns_that_policies_combine_with_or():
    """The single fact behind two of the three measured holes."""
    assert "OR" in _sql_prompt()
    assert "Policies OR" in _sql_prompt() or "policies OR" in _sql_prompt() \
        or "COMBINE WITH OR" in _sql_prompt()
