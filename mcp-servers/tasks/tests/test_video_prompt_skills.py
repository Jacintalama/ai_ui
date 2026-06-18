"""The video plan + refine prompts carry slideshow best-practices guidance.

The video generator is an ffmpeg narrated-slideshow (NOT Remotion, by design),
so these baked-in "skills" are engine-appropriate best practices that every
generated/refined video follows. (2026-06-18.)
"""
import base64
import os

os.environ.setdefault("AIUI_FERNET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ.setdefault("DATABASE_URL", "postgresql://t:t@localhost/test")

import video_refine  # noqa: E402
from video_plan import VIDEO_BEST_PRACTICES, build_plan_system_prompt  # noqa: E402


def test_best_practices_cover_the_key_dimensions():
    bp = VIDEO_BEST_PRACTICES.lower()
    for term in ("narration", "caption", "pacing", "transition", "hook"):
        assert term in bp, f"best-practices missing guidance on {term}"


def test_generate_plan_prompt_includes_best_practices():
    sp = build_plan_system_prompt()
    assert VIDEO_BEST_PRACTICES in sp     # the skill is injected
    assert "JSON plan" in sp              # core instruction preserved
    assert "60" in sp                     # duration cap still stated


def test_refine_prompt_includes_best_practices_and_context():
    sp = video_refine.build_system_prompt({"scenes": [], "title": "x"}, ["shot1.png"])
    assert VIDEO_BEST_PRACTICES in sp     # the skill is injected on refine too
    assert "shot1.png" in sp              # still lists available screenshots
    assert "propose" in sp                # refine contract preserved
