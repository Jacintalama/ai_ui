"""The app preview in a chat: a skeleton before it, and a size you choose.

Ralph, 2026-11-11, with a screenshot of a finished cup landing page sitting
in a chat: "it popup showed soo long like user didnt notice it so we want a
loading like skeleton before it shows.. in also the loading on it.... and
optimized the part of this that can be adjust the sized in the chat of the
preview".

Three things, and they are three different problems.

1. A BUILD TAKES A MINUTE AND THEN THE PANEL APPEARS FROM NOWHERE. There is
   a step list while it runs, which says what is happening, but nothing holds
   the SPACE the panel will occupy. So the finished preview arrives with no
   warning in a part of the page that was not there a moment ago, and a
   person who has looked away misses it entirely. A skeleton in the panel's
   own shape fixes that by being there first: the eye already has somewhere
   to look and the real thing fills it in.

2. THE PANEL'S OWN LOADING WAS A FLAT DARK BOX. It had a sliding bar, which
   is motion, but it looked nothing like what was about to replace it, so it
   read as a broken panel rather than a loading one. A skeleton shaped like a
   page, header and hero and lines, says "a page is coming".

3. THE SIZE WAS NOT THE PERSON'S TO CHOOSE. One fixed 22rem, with a
   bigger/smaller toggle that only acts when the split pane cannot open.
   A landing page at 22rem is a letterbox, and the thing people want is to
   drag it to the height that suits the page they are looking at and have it
   stay that way.

WHAT THESE TESTS HOLD ONTO, beyond "it works":

  - The skeleton must GO when the real panel arrives. A placeholder that
    outlives the thing it stands for is worse than no placeholder.
  - Every animation here is off under prefers-reduced-motion. A shimmer is
    the exact kind of decorative loop that triggers people, and this file
    already had that discipline for its pulse and slide.
  - The resize handle is reachable from a keyboard and says what it is.
    A drag-only control is a control some people do not have.
  - The chosen height is remembered, or choosing it is a chore repeated
    every single time an app is built.
"""
import pathlib

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

JS = (pathlib.Path(__file__).resolve().parents[3]
      / "gdrive" / "integrations-ui.js")


def _fn(src, name):
    """One function out of the file, by matching its braces.

    Same helper as test_the_panel_stays_in_its_own_reply.py: by name rather
    than by line range, because a range silently captures the wrong thing
    the moment anything above it moves.
    """
    start = src.index("  function " + name + "(")
    depth, i, seen = 0, src.index("{", start), False
    while i < len(src):
        if src[i] == "{":
            depth += 1
            seen = True
        elif src[i] == "}":
            depth -= 1
            if seen and depth == 0:
                return src[start:i + 1]
        i += 1
    raise AssertionError("no end found for " + name)


def _consts(src):
    """The size constants, read from the file rather than restated here."""
    out = []
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("var AIUI_APP_H") or s.startswith("var AIUI_APP_MIN") \
                or s.startswith("var AIUI_APP_MAX") \
                or s.startswith("var AIUI_APP_H_KEY") \
                or s.startswith("var AIUI_COVER_SLOW_MS") \
                or s.startswith("var AIUI_APP_STEP"):
            out.append(s)
    return "\n".join(out)


def _js(*names):
    src = JS.read_text(encoding="utf-8")
    parts = [_consts(src)]
    for name in names:
        parts.append(_fn(src, name))
    return "\n".join(parts)


PAGE = """<!doctype html><meta charset="utf-8">
<body style="margin:0"><div id="root"></div><script>
%(js)s
%(driver)s
</script></body>"""


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


#: Served from a real http origin rather than set as content on
#: about:blank. localStorage THROWS on an opaque origin, so a size test on
#: about:blank would prove only that the try/catch works, while the thing
#: it is meant to check, that a chosen height survives to the next app,
#: could never pass. Routed, so nothing leaves the machine.
ORIGIN = "http://aiui.test/preview"


def _page(browser, js, driver, reduced=False):
    ctx = browser.new_context(
        reduced_motion="reduce" if reduced else "no-preference")
    body = PAGE % {"js": js, "driver": driver}
    ctx.route("**/preview", lambda route: route.fulfill(
        status=200, content_type="text/html", body=body))
    page = ctx.new_page()
    page.goto(ORIGIN)
    return page


# --- 1. the skeleton that holds the space -------------------------------

SKELETON_JS = lambda: _js("aiuiMotion", "aiuiClampAppHeight",
                          "aiuiSavedAppHeight", "aiuiSkeletonBody",
                          "aiuiSkeletonPanel")

SKELETON_DRIVER = """
window.__draw = function () {
  var el = aiuiSkeletonPanel();
  document.getElementById('root').appendChild(el);
  return el.id;
};
"""


def test_a_skeleton_stands_where_the_panel_will_be(browser):
    """The whole point of it. Something panel shaped is on the page before
    the panel is, so the finished preview fills a space the eye already
    knows about rather than appearing out of nothing."""
    page = _page(browser, SKELETON_JS(), SKELETON_DRIVER)
    page.evaluate("__draw()")
    box = page.query_selector("#root > div")
    assert box is not None
    size = box.bounding_box()
    assert size["height"] > 100, "a skeleton shorter than this holds no space"


def test_the_skeleton_has_the_panels_chrome_not_just_a_grey_box(browser):
    """A bar across the top, because that is what the real panel has. A
    plain rectangle reads as a broken image, not as something arriving."""
    page = _page(browser, SKELETON_JS(), SKELETON_DRIVER)
    page.evaluate("__draw()")
    assert page.query_selector("#root [data-aiui-skeleton-bar]") is not None
    blocks = page.query_selector_all("#root .aiui-shimmer")
    assert len(blocks) >= 3, (
        "a page-shaped skeleton needs a few blocks, not one")


def test_the_skeleton_can_be_found_again_to_remove_it(browser):
    """It is drawn by one code path and removed by another, so it has to be
    findable by something other than being the last child."""
    page = _page(browser, SKELETON_JS(), SKELETON_DRIVER)
    sid = page.evaluate("__draw()")
    assert sid
    assert page.query_selector("#" + sid) is not None


def test_drawing_it_twice_leaves_one(browser):
    """The watcher runs every few seconds. A skeleton per scan would stack
    up a column of them under the reply."""
    page = _page(browser, SKELETON_JS(), SKELETON_DRIVER)
    page.evaluate("__draw(); __draw(); __draw()")
    assert len(page.query_selector_all("#root > div")) == 1


def test_the_shimmer_stops_for_anybody_who_asked_for_less_motion(browser):
    """A looping shimmer is exactly the decorative animation that setting
    exists for. The file already does this for its pulse and its slide."""
    page = _page(browser, SKELETON_JS(), SKELETON_DRIVER, reduced=True)
    page.evaluate("__draw()")
    name = page.evaluate(
        "getComputedStyle(document.querySelector('.aiui-shimmer'))"
        ".animationName")
    assert name in ("none", ""), name


def test_the_shimmer_runs_for_everybody_else(browser):
    page = _page(browser, SKELETON_JS(), SKELETON_DRIVER)
    page.evaluate("__draw()")
    name = page.evaluate(
        "getComputedStyle(document.querySelector('.aiui-shimmer'))"
        ".animationName")
    assert name and name != "none"


# --- 2. the panel's own loading ------------------------------------------

COVER_JS = lambda: _js("aiuiMotion", "aiuiSkeletonBody",
                       "aiuiCoverWhileLoading")

COVER_DRIVER = """
window.__cover = function () {
  var holder = document.getElementById('root');
  holder.style.position = 'relative';
  holder.style.height = '300px';
  var frame = document.createElement('iframe');
  holder.appendChild(frame);
  window.__frame = frame;
  return aiuiCoverWhileLoading(holder, frame);
};
window.__loaded = function () {
  window.__frame.dispatchEvent(new Event('load'));
};
"""


def test_the_loading_state_looks_like_a_page_arriving(browser):
    """Not a flat dark rectangle. Shimmer blocks in the shape of a page say
    what is coming; a blank box says something is wrong."""
    page = _page(browser, COVER_JS(), COVER_DRIVER)
    page.evaluate("__cover()")
    blocks = page.query_selector_all("#root .aiui-shimmer")
    assert len(blocks) >= 3


def test_the_loading_state_goes_when_the_app_has_loaded(browser):
    """Unchanged behaviour, restated because it is the thing a redesign of
    this would most easily break."""
    page = _page(browser, COVER_JS(), COVER_DRIVER)
    page.evaluate("__cover()")
    assert page.query_selector("#root .aiui-shimmer") is not None
    page.evaluate("__loaded()")
    assert page.query_selector("#root .aiui-shimmer") is None


def test_the_loading_state_covers_the_frame_completely(browser):
    """A half covered frame shows a white strip, which is the blank box this
    replaced."""
    page = _page(browser, COVER_JS(), COVER_DRIVER)
    page.evaluate("__cover()")
    inset = page.evaluate(
        "(function(){var c=document.querySelector('#root>div');"
        "var s=getComputedStyle(c);"
        "return [s.position, s.top, s.left, s.right, s.bottom];})()")
    assert inset[0] == "absolute", inset


# --- 3. the size is the person's to choose -------------------------------

SIZE_JS = lambda: _js("aiuiMotion", "aiuiSavedAppHeight", "aiuiSaveAppHeight",
                      "aiuiClampAppHeight", "aiuiSizeHandle")

SIZE_DRIVER = """
window.__make = function () {
  var root = document.getElementById('root');
  root.innerHTML = '';
  var frame = document.createElement('iframe');
  frame.style.cssText = 'display:block;width:100%;height:' +
    aiuiSavedAppHeight() + ';border:0;';
  root.appendChild(frame);
  root.appendChild(aiuiSizeHandle(frame));
  window.__frame = frame;
  return frame.getBoundingClientRect().height;
};
window.__h = function () {
  return window.__frame.getBoundingClientRect().height;
};
window.__handle = function () {
  return document.querySelector('[data-aiui-size-handle]');
};
"""


def test_the_handle_says_what_it_is_to_a_screen_reader(browser):
    """A bare div you can drag is invisible to anybody not using a mouse."""
    page = _page(browser, SIZE_JS(), SIZE_DRIVER)
    page.evaluate("__make()")
    h = page.query_selector("[data-aiui-size-handle]")
    assert h.get_attribute("role") == "separator"
    assert h.get_attribute("aria-orientation") == "horizontal"
    assert h.get_attribute("tabindex") == "0"
    assert (h.get_attribute("aria-label") or "").strip()


def test_the_keyboard_can_make_it_taller(browser):
    """The same control, without a mouse."""
    page = _page(browser, SIZE_JS(), SIZE_DRIVER)
    before = page.evaluate("__make()")
    page.focus("[data-aiui-size-handle]")
    page.keyboard.press("ArrowDown")
    assert page.evaluate("__h()") > before


def test_the_keyboard_can_make_it_shorter(browser):
    page = _page(browser, SIZE_JS(), SIZE_DRIVER)
    page.evaluate("__make()")
    page.focus("[data-aiui-size-handle]")
    page.keyboard.press("ArrowDown")
    taller = page.evaluate("__h()")
    page.keyboard.press("ArrowUp")
    assert page.evaluate("__h()") < taller


def test_dragging_the_handle_resizes_the_preview(browser):
    page = _page(browser, SIZE_JS(), SIZE_DRIVER)
    before = page.evaluate("__make()")
    h = page.query_selector("[data-aiui-size-handle]")
    box = h.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2 + 120, steps=6)
    page.mouse.up()
    assert page.evaluate("__h()") > before + 50


def test_it_cannot_be_dragged_into_nothing(browser):
    """A preview squeezed to 10 pixels is a control that destroys the thing
    it controls, and there is no obvious way back from it."""
    page = _page(browser, SIZE_JS(), SIZE_DRIVER)
    page.evaluate("__make()")
    h = page.query_selector("[data-aiui-size-handle]")
    box = h.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2 - 4000, steps=8)
    page.mouse.up()
    assert page.evaluate("__h()") >= 100


def test_the_size_is_remembered_for_the_next_app(browser):
    """Otherwise it is a chore repeated after every single build, which is
    the opposite of what was asked for."""
    page = _page(browser, SIZE_JS(), SIZE_DRIVER)
    page.evaluate("__make()")
    page.focus("[data-aiui-size-handle]")
    for _ in range(3):
        page.keyboard.press("ArrowDown")
    chosen = page.evaluate("__h()")
    again = page.evaluate("__make()")
    assert abs(again - chosen) < 2, (chosen, again)


def test_a_saved_size_that_is_nonsense_is_ignored(browser):
    """localStorage is editable, shared with anything else on this origin,
    and survives a release that changes what the value means."""
    page = _page(browser, SIZE_JS(), SIZE_DRIVER)
    page.evaluate(
        "localStorage.setItem(AIUI_APP_H_KEY, 'drop table'); __make()")
    assert page.evaluate("__h()") >= 100


TOGGLE_JS = lambda: _js("aiuiMotion", "aiuiClampAppHeight",
                        "aiuiSavedAppHeight", "aiuiSaveAppHeight",
                        "aiuiSizeHandle", "aiuiShowSizeHandle")

TOGGLE_DRIVER = """
window.__box = function (withHandle) {
  var root = document.getElementById('root');
  root.innerHTML = '';
  var box = document.createElement('div');
  var bar = document.createElement('div');
  bar.id = 'bar';
  box.appendChild(bar);
  var frame = document.createElement('iframe');
  box.appendChild(frame);
  if (withHandle) box.appendChild(aiuiSizeHandle(frame));
  root.appendChild(box);
  window.__bar = bar;
};
window.__shown = function () {
  var h = document.querySelector('[data-aiui-size-handle]');
  return h ? getComputedStyle(h).display !== 'none' : null;
};
"""


def test_the_grab_bar_goes_when_the_app_moves_beside_the_chat(browser):
    """In the side pane the pane owns the height, and the stage left behind
    in the thread is empty. A grab bar under an empty box would resize
    something the person cannot see."""
    page = _page(browser, TOGGLE_JS(), TOGGLE_DRIVER)
    page.evaluate("__box(true)")
    assert page.evaluate("__shown()") is True
    page.evaluate("aiuiShowSizeHandle(window.__bar, false)")
    assert page.evaluate("__shown()") is False


def test_the_grab_bar_comes_back_when_the_app_comes_home(browser):
    page = _page(browser, TOGGLE_JS(), TOGGLE_DRIVER)
    page.evaluate("__box(true)")
    page.evaluate("aiuiShowSizeHandle(window.__bar, false)")
    page.evaluate("aiuiShowSizeHandle(window.__bar, true)")
    assert page.evaluate("__shown()") is True


def test_a_panel_with_no_grab_bar_is_left_alone(browser):
    """The video panel shares this split code and has no preview to size.
    Reaching for a handle that was never added must not throw."""
    page = _page(browser, TOGGLE_JS(), TOGGLE_DRIVER)
    page.evaluate("__box(false)")
    page.evaluate("aiuiShowSizeHandle(window.__bar, false)")
    assert page.evaluate("__shown()") is None


def test_the_handle_reports_the_height_it_is_on(browser):
    """aria-valuenow, so the control is not silent about what it just did."""
    page = _page(browser, SIZE_JS(), SIZE_DRIVER)
    page.evaluate("__make()")
    page.focus("[data-aiui-size-handle]")
    before = page.evaluate(
        "__handle().getAttribute('aria-valuenow')")
    page.keyboard.press("ArrowDown")
    after = page.evaluate("__handle().getAttribute('aria-valuenow')")
    assert before and after and int(after) > int(before)
