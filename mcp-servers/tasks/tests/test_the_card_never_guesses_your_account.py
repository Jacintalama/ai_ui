"""A card never says "Connect" about an account it did not ask about.

Reported from the live platform 2026-11-17: Google flipped from Connected
to Connect overnight. It had not. All three status endpoints answered
`connected: true` for the real address at the moment of the complaint, so
the credential was fine and the CARD was wrong.

Two faults, and the second is mine from the same morning.

THE ADDRESS IS A GUESS WHEN IT IS NOT KNOWN YET. getEffectiveEmail reads
Open WebUI's user object out of localStorage, and returns the placeholder
`default@local` when it is not there yet. Measured against the live
endpoint:

    ?user_email=ralphbenitez32@gmail.com   {"connected": true}
    ?user_email=default@local              {"connected": false}
    ?user_email=                           {"connected": false}

So asking about the placeholder cannot answer anything except "not
connected". That is worse than not asking: an unanswered card says
"checking", and a wrongly answered one says "Connect" about a live
account and invites somebody to reconnect over a working credential.

AND I OPENED THE DIALOG TOO EARLY. The /connections address shipped the
same morning opened the modal on a fixed 400ms timer, which on a cold
load fires while Open WebUI is still booting and the address is still the
placeholder. The route made the existing fault reachable on purpose,
every time, instead of rarely.

Also fixed here: landing on /connections rewrote the URL with
replaceState, which changes the address bar without re-rendering, so the
dialog opened over the SPA's own "404: Not Found". A real navigation
renders the chat behind it.
"""
import json
import os
import shutil
import subprocess

import pytest

PANEL = os.path.join(os.path.dirname(__file__), "..", "..", "gdrive",
                     "integrations-ui.js")

#: Addresses that are not somebody, and must never be asked about.
NOT_A_PERSON = ["", "default@local", "undefined", "null", "   ",
                "not-an-email"]
A_PERSON = ["ralphbenitez32@gmail.com", "someone@example.co.uk"]


def _source():
    return open(PANEL, encoding="utf-8").read()


def _lift(name):
    src = _source()
    start = src.index("  function " + name + "(")
    return src[start:src.index("\n  }\n", start) + 5]


def test_there_is_one_name_for_the_placeholder():
    """A literal scattered through the file is a guard somebody forgets."""
    src = _source()
    assert "AIUI_UNKNOWN_EMAIL" in src, (
        "the placeholder address has no name, so nothing can guard on it")
    assert src.count("'default@local'") <= 1, (
        "the placeholder is still written out by hand in %d places; it "
        "should be the named constant" % src.count("'default@local'"))


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_a_placeholder_is_never_mistaken_for_a_person():
    src = _source()
    const = [l for l in src.splitlines()
             if "AIUI_UNKNOWN_EMAIL =" in l]
    assert const, "no AIUI_UNKNOWN_EMAIL to run against"
    # _isEmail too: aiuiEmailIsKnown calls it, and a lift that leaves a
    # dependency behind tests a function that cannot run.
    script = (const[0].strip() + "\n"
              + _lift("_isEmail") + "\n"
              + _lift("aiuiEmailIsKnown") + "\n"
              + "console.log(JSON.stringify("
              + json.dumps(NOT_A_PERSON + A_PERSON)
              + ".map(aiuiEmailIsKnown)));")
    out = subprocess.run(["node", "-e", script], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr[:400]
    got = json.loads(out.stdout.strip())
    want = [False] * len(NOT_A_PERSON) + [True] * len(A_PERSON)
    wrong = [(a, w, g) for a, w, g
             in zip(NOT_A_PERSON + A_PERSON, want, got) if w != g]
    assert wrong == [], (
        "these were judged wrongly (address, should be known, was): %s"
        % (wrong,))


def test_google_is_not_asked_about_an_address_we_do_not_have():
    """The call that caused the complaint. An unanswered card says
    'checking'; a wrongly answered one says 'Connect' about a live
    account and invites a reconnect over a working credential."""
    src = _source()
    # EVERY site, not the first one. The first version of this test looked
    # at one occurrence, I guarded the one I had in mind, and it passed
    # while four others still asked about the placeholder.
    unguarded, at = [], 0
    while True:
        i = src.find("/auth/google/status?user_email=", at)
        if i == -1:
            break
        at = i + 1
        if "aiuiEmailIsKnown" not in src[max(0, i - 900):i]:
            unguarded.append(src[:i].count("\n") + 1)
    assert unguarded == [], (
        "these Google status calls are still made with whatever "
        "getEffectiveEmail returned, placeholder included. Lines: %s"
        % (unguarded,))


def test_the_address_navigates_rather_than_rewriting_the_url():
    """replaceState changes the address bar without re-rendering, so the
    dialog opened over the SPA's own 404 page."""
    src = _source()
    i = src.index("aiuiWantsConnections(location.pathname)")
    after = src[i:i + 900]
    assert "location.replace" in after, (
        "landing on /connections must really navigate, or the SPA's 404 "
        "stays rendered behind the dialog")
    assert "replaceState" not in after.split("location.replace")[0], (
        "still rewriting the URL in place before navigating")


def test_the_dialog_waits_for_the_address_rather_than_a_fixed_delay():
    src = _source()
    assert "aiuiOpenConnectionsWhenReady" in src, (
        "nothing waits for the address; a fixed timer is what made Google "
        "read as disconnected on a cold load")
    fn = _lift("aiuiOpenConnectionsWhenReady")
    assert "aiuiEmailIsKnown" in fn, "it does not check the address"
    assert "setTimeout" in fn, "it does not try again"
    # Bounded: a person whose address never resolves must still get the
    # dialog, rather than a spinner for ever.
    assert "TRIES" in fn or "tries" in fn, "the wait is not bounded"
