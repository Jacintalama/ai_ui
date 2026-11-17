"""Connections has a URL you can give somebody.

Nine people are on this platform. tasks.connect_attempt, which records one
row per attempt, says exactly ONE of them has ever tried to connect
anything. Not tried and failed: never tried.

Here is why, with evidence rather than a hunch. On 2026-11-16 a capable
browser assistant was asked to connect Airtable in a real browser. It
tried, in order:

    Settings > Connections        model endpoints. A decoy with the right name.
    Settings > Integrations       tool servers. A second decoy.
    /connections                  the SPA renders nothing useful
    /connect                      same
    /connect/airtable             same

and gave up, reporting it could not find the page. The dialog is injected
into the chat composer's "+" menu, beside Upload Files, which is a fine
place to find it by accident and a hopeless place to be sent.

If an assistant whose entire task was to find it could not, the other
eight people have not either. A tenth connector is worth less than making
the nine they already have reachable, and the cheapest reachable thing is
an address: something to put in a message, a bookmark or a reply.

So the paths that person already tried now open the dialog. The matcher is
exact rather than a prefix, which matters more than it looks: /connect is
also the stem of /connect/<provider>/callback, the OAuth return address.
That page is served by the tasks service and never loads this script, so
the two cannot collide today, but a matcher that would swallow a callback
is one route change away from eating every connection on the platform.
"""
import json
import os
import re
import shutil
import subprocess

import pytest

PANEL = os.path.join(os.path.dirname(__file__), "..", "..", "gdrive",
                     "integrations-ui.js")

#: What the person actually typed, plus the shapes that must NOT match.
CASES = [
    ("/connections", True),
    ("/connections/", True),
    ("/Connections", True),
    ("/connect", True),
    ("/integrations", True),
    # The OAuth return address. Swallowing this would break every connect.
    ("/connect/airtable/callback", False),
    ("/connect/dropbox/callback", False),
    ("/connections-old", False),
    ("/", False),
    ("", False),
    ("/c/727e78e5-0000-0000-0000-000000000000", False),
    ("/admin/settings", False),
]


def _source():
    return open(PANEL, encoding="utf-8").read()


def _lift(name):
    """The function out of the shipped file, by name and indentation, so a
    rename fails here rather than quietly testing a stale copy."""
    src = _source()
    start = src.index("  function " + name + "(")
    return src[start:src.index("\n  }\n", start) + 5]


def test_the_matcher_exists_to_be_lifted():
    assert "  function aiuiWantsConnections(" in _source(), (
        "no aiuiWantsConnections in the shipped file; the tests below "
        "would have nothing to run")


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_addresses_people_actually_tried_open_connections():
    """Run the real function, not a copy of it."""
    fn = _lift("aiuiWantsConnections")
    const = re.search(r"var AIUI_CONNECTIONS_PATHS = \[[^\]]*\];",
                      _source())
    assert const, "the path list is not where the function can see it"
    script = (const.group(0) + "\n" + fn + "\n"
              + "const cases = " + json.dumps([c[0] for c in CASES]) + ";\n"
              + "console.log(JSON.stringify("
                "cases.map(aiuiWantsConnections)));")
    out = subprocess.run(["node", "-e", script], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr[:400]
    got = json.loads(out.stdout.strip())
    wrong = [(path, want, actually)
             for (path, want), actually in zip(CASES, got)
             if want != actually]
    assert wrong == [], (
        "these paths behave wrongly (path, should open, did open): %s"
        % (wrong,))


def test_a_callback_is_never_swallowed():
    """Worth its own name. /connect is the stem of the OAuth return
    address, and a prefix match here would eat every connection."""
    fn = _lift("aiuiWantsConnections")
    assert "indexOf" in fn or "includes" in fn, (
        "the matcher should test membership of an exact list; a regex or "
        "startsWith on /connect would swallow /connect/x/callback")
    assert "startsWith" not in fn


def test_landing_there_opens_the_dialog_and_tidies_the_url():
    """The SPA renders nothing at /connections, so the dialog must open
    over the chat rather than over an empty route."""
    src = _source()
    i = src.index("aiuiWantsConnections(location.pathname)")
    after = src[i:i + 700]
    assert "aiuiOpenConnections" in after, \
        "landing on the address does not open the dialog"
    assert "replaceState" in after, (
        "the address should be tidied to the chat, or a reload lands the "
        "person back on a route that renders nothing")
