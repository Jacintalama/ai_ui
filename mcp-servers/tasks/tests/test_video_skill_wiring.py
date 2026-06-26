"""Animated/remotion generation is driven by the editable 'remotion-best-practices'
Open WebUI skill: the user's skill content REPLACES the built-in ANIM_BEST_PRACTICES
in the authoring prompt, with a safe fallback to the built-in when the skill is
missing/empty/inactive or the DB read fails. (2026-06-26.)
"""
import base64
import os

os.environ.setdefault("AIUI_FERNET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ.setdefault("DATABASE_URL", "postgresql://t:t@localhost/test")

from video_plan import (  # noqa: E402
    ANIM_BEST_PRACTICES,
    REMOTION_SKILL_ID,
    build_anim_system_prompt,
    fetch_skill_best_practices,
)


# --- build_anim_system_prompt: skill content replaces the built-in -------------
def test_anim_prompt_uses_skill_override_in_place_of_builtin():
    sp = build_anim_system_prompt("CUSTOM SKILL GUIDANCE: be bold and varied.")
    assert "CUSTOM SKILL GUIDANCE: be bold and varied." in sp
    assert ANIM_BEST_PRACTICES not in sp  # the user's skill REPLACES the built-in


def test_anim_prompt_falls_back_to_builtin_when_skill_absent_or_blank():
    for empty in (None, "", "   \n  "):
        sp = build_anim_system_prompt(empty)
        assert ANIM_BEST_PRACTICES in sp


def test_anim_prompt_preserves_core_contract():
    sp = build_anim_system_prompt()
    assert "JSON plan" in sp          # core instruction preserved
    assert "40" in sp                 # duration cap still stated


# --- fetch_skill_best_practices: resilient DB read -----------------------------
class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Async-context-manager session stub: execute() -> _FakeResult, or raises."""

    def __init__(self, rows=None, raise_on_execute=False):
        self._rows = rows or []
        self._raise = raise_on_execute

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, *a, **k):
        if self._raise:
            raise RuntimeError("db boom")
        return _FakeResult(self._rows)


def _factory(rows=None, raise_on_execute=False):
    return lambda: _FakeSession(rows=rows, raise_on_execute=raise_on_execute)


async def test_fetch_skill_returns_active_content():
    out = await fetch_skill_best_practices(
        session_factory=_factory(rows=[("My remotion skill body",)])
    )
    assert out == "My remotion skill body"


async def test_fetch_skill_none_when_no_row():
    out = await fetch_skill_best_practices(session_factory=_factory(rows=[]))
    assert out is None


async def test_fetch_skill_none_when_blank_content():
    out = await fetch_skill_best_practices(session_factory=_factory(rows=[("   ",)]))
    assert out is None


async def test_fetch_skill_none_on_db_error_never_raises():
    out = await fetch_skill_best_practices(session_factory=_factory(raise_on_execute=True))
    assert out is None


def test_remotion_skill_id_is_the_website_skill():
    assert REMOTION_SKILL_ID == "remotion-best-practices"
