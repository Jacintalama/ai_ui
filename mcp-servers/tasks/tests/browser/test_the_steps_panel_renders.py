"""The step panel's own HTML, rendered, including which lane it is on.

Nothing had ever rendered this panel. Every test of it read the source
and asserted a statement was present, which cannot see a broken template
string, a variable that does not exist by that name in the browser, or
text that lands as markup.

The real aiuiStepPanel, aiuiStepStates, aiuiLaneOf and aiuiEscape are
lifted out of the shipped file. Only the three things that need a real
chat are stubbed: which chat is open, where the panel goes, and the
answer the steps were fetched in.
"""
import pathlib

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

JS = (pathlib.Path(__file__).resolve().parents[3]
      / "gdrive" / "integrations-ui.js")

AGENT_STEPS = [
    {"key": "preparing", "said": "Getting ready"},
    {"key": "writing", "said": "Writing the app"},
    {"key": "smoking", "said": "Opening it in a browser"},
]
LIGHT_STEPS = [
    {"key": "drafting", "said": "Writing the page"},
    {"key": "proofing", "said": "Making sure the page is finished"},
    {"key": "filing", "said": "Saving it to version history"},
]


def _panel_code():
    src = JS.read_text(encoding="utf-8")

    def fn(name):
        start = src.index("  function " + name + "(")
        return src[start:src.index("\n  }\n", start) + 5]

    # aiuiStepRows and aiuiMotion since 2026-11-10: the rows are shared with
    # the video's panel, and the step in progress moves.
    return "\n".join(fn(n) for n in ("aiuiLaneOf", "aiuiStepStates",
                                     "aiuiStepPanel", "aiuiStepRows",
                                     "aiuiMotion", "aiuiEscape"))


def _page(page, *, lane, step, light_name="Simple site",
          agent_name="Full builder"):
    """Draw the panel for a build on `lane` sitting at `step`."""
    page.set_content('<div id="thread"></div>')
    page.add_script_tag(content="""
      var AIUI_STEPS = %s;
      var AIUI_LANE_SAID = { light: %r, agent: %r };
      function aiuiChatIdFromUrl() { return 'chat-1'; }
      function aiuiPutUnderLastMessage(box) {
        document.getElementById('thread').appendChild(box);
      }
      function aiuiLastReplyBody() { return document.getElementById('thread'); }
      %s
      window.draw = function (lane, step) {
        return aiuiStepPanel('chat-1', { build_lane: lane, build_step: step }, 2);
      };
    """ % ({"light": LIGHT_STEPS, "agent": AGENT_STEPS},
           light_name, agent_name, _panel_code()))
    assert page.evaluate("([lane, step]) => window.draw(lane, step)",
                         [lane, step]) is True
    return page.locator("#aiui-steps")


@pytest.fixture
def page():
    with playwright_api.sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        yield pg
        browser.close()


# --- it renders at all ---------------------------------------------------

def test_the_panel_draws_a_row_for_every_step(page):
    panel = _page(page, lane="agent", step="writing")
    for said in ("Getting ready", "Writing the app", "Opening it in a browser"):
        assert said in panel.inner_text()


def test_the_step_it_is_on_is_the_one_marked_working(page):
    panel = _page(page, lane="agent", step="writing")
    text = panel.inner_text()
    assert text.count("Done") == 1          # the one before it
    assert text.count("Working on it") == 1
    assert text.count("Waiting") == 1


def test_a_build_that_has_said_nothing_yet_is_on_its_first_step(page):
    """Ralph's 2026-11-05 screenshot: a minute in, every row read
    Waiting."""
    panel = _page(page, lane="agent", step="")
    assert "Waiting" in panel.inner_text()
    assert panel.inner_text().count("Working on it") == 1


# --- which lane ----------------------------------------------------------

def test_it_says_which_lane_the_build_is_on(page):
    """Compared without case: the heading is uppercased by CSS, so the
    rendered text is SIMPLE SITE while the DOM holds "Simple site"."""
    light = _page(page, lane="light", step="drafting").inner_text().lower()
    assert "simple site" in light
    agent = _page(page, lane="agent", step="writing").inner_text().lower()
    assert "full builder" in agent
    assert "simple site" not in agent


def test_a_light_build_is_drawn_with_its_own_three_steps(page):
    """Not the agent's. A six step bar on a three step build is wrong
    about how much is left, which is the opposite of the point."""
    panel = _page(page, lane="light", step="drafting")
    text = panel.inner_text()
    assert "Writing the page" in text
    assert "Opening it in a browser" not in text


def test_no_lane_name_is_drawn_before_the_answer_arrives(page):
    """The name is fetched with the steps. A blank heading is better than
    the wrong lane's name."""
    panel = _page(page, lane="light", step="drafting", light_name="")
    assert "simple site" not in panel.inner_text().lower()
    assert "Writing the page" in panel.inner_text()


# --- it is text, not markup ----------------------------------------------

def test_a_step_sentence_is_text_even_if_it_arrives_as_markup(page):
    """Every sentence here is ours and fixed, and it still reaches
    innerHTML. "ours today" is how an escaping hole starts."""
    page.set_content('<div id="thread"></div>')
    page.add_script_tag(content="""
      var AIUI_STEPS = { agent: [{ key: 'writing',
                                   said: '<img src=x onerror=window.bad=1>' }] };
      var AIUI_LANE_SAID = { agent: 'Full builder', light: 'Simple site' };
      function aiuiChatIdFromUrl() { return 'chat-1'; }
      function aiuiPutUnderLastMessage(box) {
        document.getElementById('thread').appendChild(box);
      }
      function aiuiLastReplyBody() { return document.getElementById('thread'); }
      %s
      aiuiStepPanel('chat-1', { build_lane: 'agent', build_step: 'writing' }, 1);
    """ % _panel_code())
    assert page.evaluate("window.bad === undefined") is True
    assert page.locator("#aiui-steps img").count() == 0
