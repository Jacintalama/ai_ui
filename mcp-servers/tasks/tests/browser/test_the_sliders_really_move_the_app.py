"""Moving a control really changes the running app, checked in a browser.

The whole risk of an appearance panel is sliders that move nothing. It is
not a hypothetical: measured 2026-11-05, every app in the repo declared
zero CSS variables, so a panel dropped on them as they stood would have
drawn a full set of controls that changed absolutely nothing, and no
structural test could have told the difference.

So this drives the real panel in a real browser against a real iframe and
asserts the COMPUTED colour of an element inside that frame changes. The
JavaScript is the real integrations-ui.js, cut to the appearance section.
"""
import json
import pathlib

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

JS = (pathlib.Path(__file__).resolve().parents[3]
      / "gdrive" / "integrations-ui.js")


def _appearance():
    """The real appearance code, cut out of the real file.

    From AIUI_FONTS, which the controls read, down to the next function,
    so the cut cannot leave an undefined reference behind it.
    """
    src = JS.read_text(encoding="utf-8")
    start = src.index("  var AIUI_FONTS = [")
    end = src.index("  function aiuiShowAppInline(")
    return src[start:end]


#: What the service says about an app that declares its tokens. Shaped by
#: app_theme.state(), not invented here.
THEMEABLE = {
    "tokens": [
        {"name": "--site-primary", "kind": "color", "label": "Primary",
         "default": "#2563eb"},
        {"name": "--site-font-body", "kind": "font", "label": "Body font",
         "default": "Georgia, serif"},
        {"name": "--site-spacing-scale", "kind": "scale", "label": "Spacing",
         "default": "1", "low": 0.5, "high": 2.0},
    ],
    "values": {"--site-primary": "#8b5a2b"},
    "missing": [],
    "themeable": True,
}

BARE = {"tokens": THEMEABLE["tokens"], "values": {}, "themeable": False,
        "missing": ["--site-primary"]}

#: The built app, inside the frame. It declares its palette and USES it,
#: which is the only reason any of this works.
APP = (
    "<!doctype html><meta charset='utf-8'>"
    "<style>:root{--site-primary:#8b5a2b;}"
    "h1{color:var(--site-primary);}</style>"
    "<h1 id='title'>Bean There</h1>"
)

PAGE = """<!doctype html><meta charset="utf-8">
<div id="host"></div>
<script>
function aiuiAuthHeaders() { return { 'Content-Type': 'application/json' }; }
// A TRAP, not a stub. Until 2026-11-12 this harness defined `authHeaders`
// instead, which is the name of a function that lives inside
// createIntegrationsModal and is therefore NOT in scope anywhere in this
// section of the file. Supplying it here meant this panel passed a real
// browser test while every one of its three calls threw a ReferenceError
// in production, so the panel said "Reading this app..." for a week and
// the pencil's enhance sent nothing at all.
//
// A harness that defines a name the real page lacks does not test the
// page, it tests the harness. This one fails loudly instead.
function authHeaders() {
  throw new Error('authHeaders is not in scope in the real page. '
                  + 'Use aiuiAuthHeaders.');
}
function aiuiWatchChange() { window.__watched = true; }
window.__sent = [];
window.fetch = function (url, opts) {
  window.__sent.push({ url: String(url),
                       method: (opts && opts.method) || 'GET',
                       body: (opts && opts.body) || '' });
  var state = (String(url).indexOf('/upgrade') >= 0)
    ? { task_id: 'tid-1', slug: 'bean-there', status: 'running' }
    : %(state)s;
  return Promise.resolve({ ok: true, json: function () {
    return Promise.resolve(state); } });
};
%(js)s
var frame = document.createElement('iframe');
frame.id = 'app';
frame.srcdoc = %(app)s;
document.getElementById('host').appendChild(frame);
window.__look = aiuiAppearance('chat-1', 'bean-there', frame);
document.getElementById('host').appendChild(window.__look.el);
</script>
"""


def _page(browser, state):
    page = browser.new_page()
    page.set_content(PAGE % {"js": _appearance(),
                             "state": json.dumps(state),
                             "app": json.dumps(APP)})
    page.wait_for_selector("#app")
    return page


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def _title_colour(page):
    return page.frame_locator("#app").locator("#title").evaluate(
        "el => getComputedStyle(el).color")


# --- the mechanism -------------------------------------------------------

def test_the_app_starts_in_its_own_colour(browser):
    """If this is already the colour the panel sets, the test below proves
    nothing."""
    page = _page(browser, THEMEABLE)
    assert _title_colour(page) == "rgb(139, 90, 43)"
    page.close()


def test_moving_the_colour_changes_the_app_on_screen(browser):
    """The one thing that cannot be faked: the computed colour of an
    element INSIDE the frame, after a control moved."""
    page = _page(browser, THEMEABLE)
    page.evaluate("window.__look.open()")
    page.wait_for_function("document.querySelectorAll('input[type=color]').length > 0")

    page.evaluate("""() => {
      const el = document.querySelector('input[type=color]');
      el.value = '#0f766e';
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    page.wait_for_function(
        "() => document.querySelector('#app').contentDocument"
        ".documentElement.style.getPropertyValue('--site-primary').trim()"
        " === '#0f766e'")
    assert _title_colour(page) == "rgb(15, 118, 110)"
    page.close()


def test_moving_a_control_saves_nothing(browser):
    """Live preview is the point. A panel that wrote on every nudge would
    commit once per drag."""
    page = _page(browser, THEMEABLE)
    page.evaluate("window.__look.open()")
    page.wait_for_function("document.querySelectorAll('input[type=color]').length > 0")
    page.evaluate("""() => {
      const el = document.querySelector('input[type=color]');
      el.value = '#0f766e';
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    sent = page.evaluate("window.__sent")
    assert [s["method"] for s in sent] == ["GET"], sent
    page.close()


def test_a_control_is_drawn_for_every_token_that_was_served(browser):
    page = _page(browser, THEMEABLE)
    page.evaluate("window.__look.open()")
    page.wait_for_function("document.querySelectorAll('input[type=color]').length > 0")
    assert page.locator("input[type=color]").count() == 1
    assert page.locator("select").count() == 1
    assert page.locator("input[type=range]").count() == 1
    page.close()


def test_saving_sends_only_what_was_moved(browser):
    page = _page(browser, THEMEABLE)
    page.evaluate("window.__look.open()")
    page.wait_for_function("document.querySelectorAll('input[type=color]').length > 0")
    page.evaluate("""() => {
      const el = document.querySelector('input[type=color]');
      el.value = '#0f766e';
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    page.get_by_role("button", name="Save").click()
    page.wait_for_function(
        "() => window.__sent.some(s => s.method === 'PUT')")
    put = [s for s in page.evaluate("window.__sent") if s["method"] == "PUT"][0]
    assert json.loads(put["body"]) == {"values": {"--site-primary": "#0f766e"}}
    assert put["url"].endswith("/api/aiuibuilder/bean-there/theme")
    page.close()


def test_save_is_dead_until_something_moves(browser):
    page = _page(browser, THEMEABLE)
    page.evaluate("window.__look.open()")
    page.wait_for_function("document.querySelectorAll('input[type=color]').length > 0")
    assert page.get_by_role("button", name="Save").is_disabled()
    page.close()


# --- the app that has no tokens yet --------------------------------------

def test_an_app_with_no_tokens_is_offered_the_upgrade(browser):
    """Rather than a full set of controls that move nothing, which is
    what every app in the repo would have shown."""
    page = _page(browser, BARE)
    page.evaluate("window.__look.open()")
    page.wait_for_selector("text=Make it changeable")
    assert page.locator("input[type=color]").count() == 0
    assert page.locator("input[type=range]").count() == 0
    page.close()


def test_the_upgrade_asks_for_a_build_and_hands_it_to_the_watcher(browser):
    page = _page(browser, BARE)
    page.evaluate("window.__look.open()")
    page.get_by_role("button", name="Make it changeable").click()
    page.wait_for_function("() => window.__watched === true")
    posts = [s for s in page.evaluate("window.__sent") if s["method"] == "POST"]
    assert posts and posts[0]["url"].endswith(
        "/api/aiuibuilder/bean-there/theme/upgrade")
    page.close()
