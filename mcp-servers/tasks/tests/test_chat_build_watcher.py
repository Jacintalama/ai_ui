"""A build started from the main chat says when it is done (2026-11-03).

Lukas, 2026-10-31: the chat says "Building X now" and then nothing, so a
person cannot tell whether it is working, finished, or broken. The page now
watches the build link in the reply and adds one message when the build
settles.

The section's functions are run for real under node, with only the network
and the chat store replaced, because a text search of this file can say a
function exists but not that it does the right thing. Skipped where node is
not installed.
"""
import json
import os
import shutil
import subprocess
import tempfile

import pytest

JS = os.path.join(os.path.dirname(__file__), "..", "..",
                  "gdrive", "integrations-ui.js")
START = "// ===== Build watcher ====="
END = "// ===== End build watcher ====="
ID = "0f2b8c1e-1d2a-4c3b-9e8f-7a6b5c4d3e2f"
OTHER = "11111111-2222-4333-8444-555555555555"
LINK = "https://ai-ui.coolestdomain.win/tasks/static/preview.html?task=" + ID


def _section():
    with open(JS, encoding="utf-8") as fh:
        js = fh.read()
    start, end = js.index(START), js.index(END)
    assert start < end
    return js[start:end]


def _node(script):
    """Run the section plus `script` under node; `script` prints JSON."""
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    stubs = """
var aiuiSaved = [], aiuiStored = null, aiuiReloads = 0;
function aiuiChainFromHistory(history) {
  var msgs = history && history.messages ? history.messages : {};
  var id = history ? history.currentId : null, chain = [];
  for (var g = 0; id && msgs[id] && g < 500; g++) { chain.unshift(msgs[id]); id = msgs[id].parentId; }
  return chain;
}
function aiuiFetchChat(chatId) { return Promise.resolve(JSON.parse(JSON.stringify(aiuiStored))); }
function aiuiSaveChat(chatId, chat) { aiuiSaved.push(chat); return Promise.resolve(); }
function aiuiSoftReload(chatId) { aiuiReloads++; }
function aiuiChatIdFromUrl() { return 'chat-1'; }
function aiuiUuid() { return 'new-1'; }
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(stubs + _section() + "\n" + script)
        path = fh.name
    try:
        out = subprocess.run(["node", path], capture_output=True, text=True,
                             timeout=30)
    finally:
        os.unlink(path)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _chat(*messages):
    """A stored chat whose messages follow one another, last one current."""
    msgs, parent = {}, None
    for i, m in enumerate(messages):
        mid = "m%d" % i
        msgs[mid] = dict({"id": mid, "parentId": parent, "childrenIds": [],
                          "done": True, "timestamp": 1}, **m)
        if parent:
            msgs[parent]["childrenIds"].append(mid)
        parent = mid
    return {"chat": {"title": "T", "history": {"messages": msgs, "currentId": parent}}}


# --- reading a reply ----------------------------------------------------------

def test_a_build_link_is_found_once_however_often_it_is_linked():
    got = _node("console.log(JSON.stringify([aiuiBuildIdsIn(%s), aiuiBuildIdsIn('no build here')]))"
                % json.dumps("Building it.\nWatch it here: " + LINK + "\n(" + LINK + ")"))
    assert got == [[ID], []]


def test_a_closed_build_is_closed_and_an_open_one_is_not():
    chain = [{"role": "assistant", "content": "done " + "<!-- aiui:build-done %s -->" % ID}]
    got = _node("var c = %s; console.log(JSON.stringify([aiuiBuildIsClosed(c, %s), aiuiBuildIsClosed(c, %s)]))"
                % (json.dumps(chain), json.dumps(ID), json.dumps(OTHER)))
    assert got == [True, False]


# --- what the closing message says ----------------------------------------------

def _outcome(task):
    return _node("console.log(JSON.stringify(aiuiBuildOutcome(%s, %s, 'https://x.test')))"
                 % (json.dumps(task), json.dumps(ID)))


@pytest.mark.parametrize("status", ["running", "planning"])
def test_a_build_still_running_has_nothing_to_say(status):
    assert _outcome({"status": status, "built_app_slug": "shop"}) is None


def test_a_finished_build_gives_the_link_to_the_app():
    said = _outcome({"status": "completed", "built_app_slug": "shop"})
    assert said.startswith("shop is built.\nOpen it here: https://x.test/tasks/preview-app/shop/")
    # The marker is a markdown link reference since #110, which renders as
    # nothing; the old HTML comment was printed to the person.
    assert said.rstrip().endswith("[aiui-build-done]: #%s" % ID)


def test_a_build_waiting_on_a_question_asks_it_and_says_where_to_answer():
    said = _outcome({"status": "awaiting_input", "built_app_slug": "shop",
                     "result": "Which colour?"})
    assert "shop is waiting on an answer." in said
    assert "Which colour?" in said
    assert "https://x.test/tasks/static/preview.html?task=" + ID in said


def test_a_failed_build_says_so_with_the_reason():
    said = _outcome({"status": "failed", "built_app_slug": None,
                     "result": "Provider refused: billing"})
    assert said.startswith("The app did not finish building.")
    assert "Provider refused: billing" in said


# --- writing the closing message -------------------------------------------------

def _close(stored):
    return _node("""
aiuiStored = %s;
aiuiCloseBuild('chat-1', %s, 'shop is built. <!-- aiui:build-done %s -->').then(function (done) {
  console.log(JSON.stringify({done: done, saved: aiuiSaved, reloads: aiuiReloads}));
});""" % (json.dumps(stored), json.dumps(ID), ID))


def test_the_closing_message_goes_under_the_last_reply_and_saves_only_the_history():
    got = _close(_chat({"role": "user", "content": "build me a shop"},
                       {"role": "assistant", "content": "Building. " + LINK,
                        "model": "auto_router.auto", "modelName": "Auto (Free)"}))
    assert got["done"] is True and got["reloads"] == 1
    assert len(got["saved"]) == 1
    # {history} only: posting the whole chat back reverts a title Open WebUI
    # generated moments earlier (see aiuiSaveChat).
    assert list(got["saved"][0]) == ["history"]
    h = got["saved"][0]["history"]
    new = h["messages"]["new-1"]
    assert h["currentId"] == "new-1"
    assert new["parentId"] == "m1" and new["role"] == "assistant" and new["done"] is True
    assert new["model"] == "auto_router.auto"
    assert "new-1" in h["messages"]["m1"]["childrenIds"]


def test_a_build_another_tab_already_closed_is_not_closed_twice():
    got = _close(_chat({"role": "assistant", "content": "Building. " + LINK},
                       {"role": "assistant", "content": "x <!-- aiui:build-done %s -->" % ID}))
    assert got["done"] is True and got["saved"] == []


def test_nothing_is_written_while_a_reply_is_still_being_written():
    """The person sent something and the answer is streaming. Writing now
    would race Open WebUI's own save; the next tick tries again."""
    got = _close(_chat({"role": "assistant", "content": "Building. " + LINK},
                       {"role": "user", "content": "and make it blue"}))
    assert got["done"] is False and got["saved"] == []


# --- wiring ---------------------------------------------------------------------

def test_the_watcher_is_started_from_the_existing_scan():
    with open(JS, encoding="utf-8") as fh:
        js = fh.read()
    scan = js[js.index("function aiuiScanAgentNameHeaders()"):]
    scan = scan[:scan.index("\n  }\n")]
    assert "aiuiWatchBuilds()" in scan


def test_the_watcher_never_hard_reloads_the_page():
    assert "location.reload" not in _section()
