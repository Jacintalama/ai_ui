"""A finished build shows the app, not a link to it.

Measured from Ralph's own chat, 2026-11-05. The build finished and the
reply was:

    juicethere-landing-page-7f8c is built.
    Open it here: https://.../tasks/preview-app/juicethere-landing-page-7f8c/

and nothing else. A link, which is the thing the inline panel existed to
replace.

Two faults, both here:

1. Every pattern the parser had wanted a task UUID. The message that
   announces a FINISHED app carries a slug and no uuid anywhere, so the
   one message that says an app exists was the one message nothing could
   read.

2. The panel was drawn in a single place: the moment the watcher saw a
   build complete. Once the chat holds the done marker the watcher skips
   that build entirely, so a reload, a second tab, or any build that
   finished while the tab was shut showed the bare link forever.

The parser half runs the REAL function through node, like
test_what_a_reply_carries.py, because a structural test of a regex tells
you the regex is present, not that it matches the sentence a person
actually got.
"""
import json
import os
import subprocess

import pytest

JS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                  "gdrive", "integrations-ui.js"))

#: The exact reply, taken from the screenshot, not invented.
REAL_REPLY = (
    "juicethere-landing-page-7f8c is built."
    "\nOpen it here: https://ai-ui.coolestdomain.win"
    "/tasks/preview-app/juicethere-landing-page-7f8c/"
)

HARNESS = """
const fs = require('fs');
const src = fs.readFileSync(%s, 'utf8');
const a = src.indexOf('// ===== What a reply carries =====');
const b = src.indexOf('// ===== End what a reply carries =====');
if (a < 0 || b < 0) { throw new Error('section markers missing'); }
eval(src.slice(a, b));
%s
"""


def _node(body):
    if not __import__("shutil").which("node"):
        pytest.skip("node is not installed")
    script = HARNESS % (json.dumps(JS), body)
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-900:]
    return json.loads(out.stdout.strip())


def _ids(text, kind):
    return _node("console.log(JSON.stringify(aiuiArtifactIds(%s, %s)))"
                 % (json.dumps(text), json.dumps(kind)))


def _js():
    with open(JS, encoding="utf-8") as fh:
        return fh.read()


# --- the message Ralph actually got --------------------------------------

def test_the_reply_that_announces_a_finished_app_names_that_app():
    assert _ids(REAL_REPLY, "app") == ["juicethere-landing-page-7f8c"]


def test_that_same_reply_is_not_mistaken_for_a_build_to_watch():
    """It carries no task id, so there is nothing to poll. Treating it as
    a build would start a watcher that can never finish."""
    assert _ids(REAL_REPLY, "build") == []
    assert _ids(REAL_REPLY, "video") == []


def test_a_declared_app_still_wins_and_is_not_listed_twice():
    """A build written after today declares the app AND carries the URL.
    Both name the same slug, and the panel must be drawn once."""
    both = REAL_REPLY + "\n\n[aiui-artifact]: #app/juicethere-landing-page-7f8c"
    assert _ids(both, "app") == ["juicethere-landing-page-7f8c"]


def test_two_apps_in_one_chat_are_both_found():
    text = (REAL_REPLY + "\nand "
            + "https://x/tasks/preview-app/bean-there/")
    assert _ids(text, "app") == ["juicethere-landing-page-7f8c", "bean-there"]


@pytest.mark.parametrize("nasty", [
    "/tasks/preview-app/../../etc/passwd",
    "/tasks/preview-app/..",
])
def test_a_path_that_climbs_out_is_not_an_app(nasty):
    assert _ids(nasty, "app") == []


@pytest.mark.parametrize("nasty", [
    "[aiui-artifact]: #app/../../etc/passwd",
    "[aiui-artifact]: #app/..",
    "[aiui-artifact]: #app/a..b",
])
def test_a_declared_app_that_climbs_out_is_refused(nasty):
    """The URL form cannot carry a dot at all, so the test above never
    reaches the guard that stops this. The DECLARED form does allow dots
    in a slug, and is the input that guard exists for; removing it left
    every test green.
    """
    assert _ids(nasty, "app") == []


def test_the_building_message_is_still_a_build_and_not_an_app():
    """The message BEFORE this one, which does carry a task id. It must
    keep being watched, and must not also draw an empty app panel."""
    said = ("Building your JuiceThere landing page now. You can watch it "
            "here: https://ai-ui.coolestdomain.win/tasks/static/preview.html"
            "?task=109db3d8-57c9-46df-86ad-6fcf71678d86")
    assert _ids(said, "build") == ["109db3d8-57c9-46df-86ad-6fcf71678d86"]
    assert _ids(said, "app") == []


# --- what the finished build writes --------------------------------------

def test_a_finished_build_declares_its_app():
    """So the next one does not depend on the wording of a sentence.

    The whole statement, not the string inside it. Asserting only the
    marker text passed with `said +=` replaced by a `void`, which is the
    declaration deleted and every test still green.
    """
    src = _js()
    done = src[src.index("if (status === 'completed') {"):]
    done = done[:done.index("} else if")]
    assert ("said += '" + chr(92) + "n" + chr(92) + "n"
            "[aiui-artifact]: #app/' + task.built_app_slug;") in done
    assert "if (task && task.built_app_slug) {" in done


# --- it is drawn from the chat, not only when a build completes ----------

def test_the_app_is_drawn_from_what_the_chat_says():
    src = _js()
    watcher = src[src.index("function aiuiWatchBuilds()"):]
    watcher = watcher[:watcher.index("\n  }\n")]
    assert "aiuiArtifactIds(html, 'app').forEach(function (slug) {" in watcher
    assert "aiuiShowAppInline(chatId, slug);" in watcher


def test_it_is_drawn_before_the_watcher_gives_up_on_a_closed_build():
    """This is the whole bug. Everything below the early return is
    skipped for a build the chat has already closed, which is every
    finished build after a reload."""
    src = _js()
    watcher = src[src.index("function aiuiWatchBuilds()"):]
    watcher = watcher[:watcher.index("\n  }\n")]
    drawn = watcher.index("aiuiArtifactIds(html, 'app')")
    gives_up = watcher.index("if (!fresh.length) return;")
    assert drawn < gives_up, (
        "the app is drawn after the early return, so a finished build "
        "still shows a bare link")


def test_the_thread_is_read_once_per_look():
    """It runs on a mutation observer and a long chat's innerHTML is not
    cheap. Two reads per look would double that for nothing."""
    src = _js()
    watcher = src[src.index("function aiuiWatchBuilds()"):]
    watcher = watcher[:watcher.index("\n  }\n")]
    assert watcher.count("thread.innerHTML") == 1
    assert "var html = thread ? thread.innerHTML : '';" in watcher
