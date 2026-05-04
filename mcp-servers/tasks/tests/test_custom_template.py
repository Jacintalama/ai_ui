"""Tests for the synthetic 'custom' template key — escape hatch from
template selection that lets the agent build from the user's description
alone with the universal layout/scope baseline."""
from templates import (
    is_valid_key,
    build_rules_for,
    storage_for,
    requires_supabase,
    _has_template_app,
    get_template,
)


def test_custom_is_a_valid_key():
    assert is_valid_key("custom") is True


def test_custom_template_metadata():
    t = get_template("custom")
    assert t is not None
    assert t.key == "custom"
    assert t.label == "Custom"
    assert "description" in t.description.lower() or "prompt" in t.description.lower()


def test_custom_storage_is_none():
    assert storage_for("custom") == "none"


def test_custom_does_not_trigger_supabase_gate():
    assert requires_supabase("custom", "none") is False
    assert requires_supabase("custom", "supabase") is False


def test_custom_has_no_template_app_folder():
    assert _has_template_app("custom") is False


def test_custom_rules_block_contains_baseline_layout_and_scope():
    block = build_rules_for("custom", "none")
    assert "FILE LAYOUT" in block
    assert "apps/<slug>/" in block
    assert "RULES (strict)" in block
    # Make sure no template-specific guidance leaked in.
    assert "PURPOSE: Marketing" not in block  # would be from landing
    assert "PURPOSE: Operational analytics" not in block  # dashboard
    assert "PURPOSE: Manage one main entity" not in block  # crud


def test_custom_rules_block_is_non_empty():
    block = build_rules_for("custom", "none")
    assert len(block) > 500  # baseline alone is several hundred chars


def test_custom_appears_last_in_templates_list():
    """Custom card sits at the end of the gallery. Order is determined
    by the TEMPLATES list order in templates.py."""
    from templates import TEMPLATES
    assert TEMPLATES[-1].key == "custom"
