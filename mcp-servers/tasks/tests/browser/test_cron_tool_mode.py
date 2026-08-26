"""The Tool access control, and what the card says about it.

Follows the existing browser tests in this directory: parse the served page
and assert on structure, rather than driving a browser.
"""
import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[2] / "static" / "cron.html"


@pytest.fixture(scope="module")
def html():
    return PAGE.read_text(encoding="utf-8")


def test_there_is_a_tool_access_select(html):
    assert 'id="tool-mode"' in html


def test_it_offers_read_only_and_full_but_not_ask(html):
    block = html.split('id="tool-mode"', 1)[1].split("</select>", 1)[0]
    assert 'value="read_only"' in block
    assert 'value="full"' in block
    assert 'value="ask"' not in block, "ask is Phase 2 and cannot be honoured yet"


def test_read_only_is_the_default_selection(html):
    block = html.split('id="tool-mode"', 1)[1].split("</select>", 1)[0]
    first = re.search(r'<option[^>]*value="([^"]*)"', block)
    assert first and first.group(1) == "read_only"


def test_the_submit_body_sends_the_tool_mode(html):
    assert "body.tool_mode" in html


def test_the_control_sits_with_the_run_as_field(html):
    """It is meaningless without an agent, so it must not drift elsewhere."""
    assert html.index('id="run-as"') < html.index('id="tool-mode"')
    between = html[html.index('id="run-as"'):html.index('id="tool-mode"')]
    assert between.count('class="field"') <= 1
