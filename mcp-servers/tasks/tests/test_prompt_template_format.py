"""Regression: every prompt template in claude_executor must format() cleanly
with the kwargs its builder function passes — nothing more.

A literal `{` in template content (e.g. JS code samples like `import { Foo }`)
must be escaped as `{{`, otherwise Python's str.format() either raises
ValueError immediately or silently registers a phantom placeholder
(`{ Foo }` → field name ` Foo `) that KeyErrors at call time.

The April 28 commit `31a9fb9ca` introduced unescaped JS examples and
broke fresh-build tasks for nearly a week before the next attempt
exposed the regression. These tests prevent that recurrence.
"""
from claude_executor import (
    build_prompt,
    build_enhance_prompt,
    build_clarify_prompt,
    build_plan_prompt,
    build_tdd_execute_prompt,
    build_verify_prompt,
)


def test_build_prompt_formats_without_error():
    out = build_prompt(
        description="Make me a portfolio Jacint A. Alama minimalist website",
        action_type="BUILD",
        priority="HIGH",
        meeting_title="meeting-id",
        meeting_date="2026-05-04",
    )
    assert "TASK: Make me a portfolio Jacint A. Alama minimalist website" in out
    assert "TYPE: BUILD" in out


def test_build_tdd_execute_prompt_formats_without_error():
    out = build_tdd_execute_prompt(
        description="add login form",
        action_type="BUILD",
        priority="HIGH",
        meeting_title="m",
        meeting_date="2026-05-04",
        plan="step 1: write the form\nstep 2: wire submit",
        conversation_history=[],
    )
    assert "step 1: write the form" in out
    assert "TASK: add login form" in out


def test_build_clarify_prompt_formats_without_error():
    out = build_clarify_prompt(
        description="todo app",
        action_type="BUILD",
        priority="NICE_TO_HAVE",
        conversation_history=[],
    )
    assert "todo app" in out


def test_build_plan_prompt_formats_without_error():
    out = build_plan_prompt(
        description="todo app",
        action_type="BUILD",
        priority="HIGH",
        requirements="simple list",
    )
    assert "simple list" in out


def test_build_enhance_prompt_formats_without_error():
    out = build_enhance_prompt(
        slug="testapp",
        user_request="rename header",
        attachments=None,
    )
    assert "testapp" in out
    assert "rename header" in out


def test_build_verify_prompt_formats_without_error():
    out = build_verify_prompt(slug="testapp", description="todo app")
    assert "testapp" in out
    assert "todo app" in out
