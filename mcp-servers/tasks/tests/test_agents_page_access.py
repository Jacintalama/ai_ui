"""The Access control on the agent form.

Structural, because the page is vanilla JS with no test harness. These check
the things that would silently change somebody's permissions if they were
wrong, which is why they are worth having even in this crude form.
"""
import os
import re

PAGE = os.path.join(os.path.dirname(__file__), "..", "static", "agents.html")


def _page():
    with open(PAGE, encoding="utf-8") as fh:
        return fh.read()


def test_all_three_levels_are_offered():
    page = _page()
    for value in ('value="read"', 'value="ask"', 'value="all"'):
        assert value in page, value


def test_the_labels_are_the_owners_words():
    page = _page()
    assert "Read only" in page
    assert "With access" in page
    assert "All access" in page


def test_the_scope_is_stated_on_the_form():
    """The web chat runs Open WebUI's own tool loop and ignores this setting.
    A permission control that silently does nothing where somebody first
    tests it is worse than one that admits its edges."""
    page = _page()
    assert "Web chat" in page
    assert re.search(r"always has full access", page)


def test_a_new_agent_defaults_to_asking():
    page = _page()
    assert re.search(r'value="ask"[^>]*checked', page), (
        "the middle level is the default for a new agent")


def test_the_level_is_written_into_meta():
    page = _page()
    assert re.search(r"meta\.access\s*=", page), (
        "buildAgentBody must put the level on meta.access")


def test_an_agent_with_no_level_set_is_not_given_one_on_save():
    """Absent means "behave exactly as today". Preselecting a level and
    writing it on an unrelated edit would silently drop a schedule from full
    to read only."""
    page = _page()
    assert "chosenAccess" in page
    assert re.search(r"if\s*\(\s*f\.access\s*\)\s*meta\.access", page), (
        "the level must be omitted from the body when nothing is selected")


def test_nothing_is_preselected_for_an_agent_that_has_no_level():
    """setAccess("") must clear every radio, or an unrelated edit writes a
    level onto an agent that never had one."""
    page = _page()
    assert "function setAccess" in page
    assert re.search(r"all\[i\]\.checked\s*=\s*false", page), (
        "setAccess must clear the group before selecting")


def test_no_em_dashes_in_the_new_copy():
    page = _page()
    assert "\u2014" not in page and "\u2013" not in page
