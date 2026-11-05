"""A reply says what it carries, instead of the page reading its prose.

The page has been working out what a message is about by reading things
OUT of its text: a preview.html link means a build to watch, and the
sentence "Its id is <uuid>" means a video.

The second one keys on a sentence a tool writes in English. Reword that
sentence and video watching stops, with nothing failing and nothing
saying so.

A reply may now declare what it carries, as a markdown link reference
definition the parser consumes and does not render:

    [aiui-artifact]: #app/nike-tshirt-landing-6430
    [aiui-artifact]: #build/528f5422-...
    [aiui-artifact]: #video/55785e0a-...

Nothing writes those yet. This is the reading half, so the writing half
is one line wherever a reply is composed.

These run the REAL function through node rather than reading the source,
the same way test_chat_build_watcher.py does. A structural test would not
have caught what this caught.
"""
import json
import os
import subprocess

import pytest

JS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                  "gdrive", "integrations-ui.js"))
UUID = "528f5422-5dea-4c5a-8638-8e919a01109b"
OTHER = "11112222-3333-4444-5555-666677778888"

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
    script = HARNESS % (json.dumps(JS), body)
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-900:]
    return json.loads(out.stdout.strip())


def _found(text):
    return _node("console.log(JSON.stringify(aiuiArtifactsIn(%s)))"
                 % json.dumps(text))


def _ids(text, kind):
    return _node("console.log(JSON.stringify(aiuiArtifactIds(%s, %s)))"
                 % (json.dumps(text), json.dumps(kind)))


# --- it runs at all --------------------------------------------------------

def test_the_parser_runs():
    """It is built by a script that writes JavaScript, and a variable from
    the WRITING language once leaked into the written code. That parsed
    cleanly and threw on every call, which would have stopped every build
    and every video being watched. Only running it finds that."""
    assert _found("nothing here") == []


# --- what a reply declares -------------------------------------------------

@pytest.mark.parametrize("kind,ident", [
    ("app", "nike-tshirt-landing-6430"),
    ("build", UUID),
    ("video", UUID),
])
def test_a_declared_artifact_is_found(kind, ident):
    text = "Here you go.\n\n[aiui-artifact]: #%s/%s" % (kind, ident)
    assert _found(text) == [{"kind": kind, "id": ident}]


def test_a_kind_nobody_knows_is_ignored():
    """The marker is ours, but it sits in text a model composes. An
    unknown kind reaching the page as something to act on is how a
    scanner becomes an injection point."""
    assert _found("[aiui-artifact]: #wormhole/abc") == []


def test_an_id_cannot_be_anything_at_all():
    """It becomes part of a URL further down."""
    assert _found("[aiui-artifact]: #app/../../etc/passwd") == []
    assert _found("[aiui-artifact]: #app/" + "x" * 200) == []


# --- what the prose used to say -------------------------------------------

def test_a_build_link_still_counts():
    """Every message already in somebody's history says it this way."""
    text = "Watch it here: https://x/tasks/static/preview.html?task=" + UUID
    assert _found(text) == [{"kind": "build", "id": UUID}]


def test_the_video_sentence_still_counts():
    assert _found("Its id is " + UUID) == [{"kind": "video", "id": UUID}]


def test_a_declaration_and_the_prose_are_one_artifact():
    """A reply that does both must not start two watchers on one thing."""
    text = ("[aiui-artifact]: #build/%s and /tasks/static/preview.html?task=%s"
            % (UUID, UUID))
    assert _found(text) == [{"kind": "build", "id": UUID}]


def test_two_different_things_are_two_artifacts():
    text = "[aiui-artifact]: #app/shop\n[aiui-artifact]: #video/" + UUID
    assert _found(text) == [{"kind": "app", "id": "shop"},
                            {"kind": "video", "id": UUID}]


# --- the two scanners that used to be separate -----------------------------

def test_asking_for_one_kind_does_not_return_another():
    """The bug this shape prevents: a build id watched as a video, which
    polls the wrong endpoint forever and reports nothing."""
    text = "/tasks/static/preview.html?task=" + UUID
    assert _ids(text, "build") == [UUID]
    assert _ids(text, "video") == []


def test_the_build_scanner_delegates():
    src = open(JS, encoding="utf-8").read()
    body = src[src.index("function aiuiBuildIdsIn"):]
    body = body[:body.index("\n  }") + 4]
    assert "aiuiArtifactIds(content, 'build')" in body
    assert "while" not in body, "it still has a scanner of its own"


def test_the_video_scanner_delegates():
    src = open(JS, encoding="utf-8").read()
    body = src[src.index("function aiuiVideoIdsIn"):]
    body = body[:body.index("\n  }") + 4]
    assert "aiuiArtifactIds(content, 'video')" in body
    assert "while" not in body, "it still has a scanner of its own"


def test_an_empty_or_missing_message_is_not_an_error():
    """The scan runs over every message in a chat, including ones with no
    content at all."""
    assert _found("") == []
    assert _node("console.log(JSON.stringify(aiuiArtifactsIn(null)))") == []
