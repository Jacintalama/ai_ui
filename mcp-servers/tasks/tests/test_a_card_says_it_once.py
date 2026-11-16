"""An app with no way to connect says so ONCE, and says it definitely.

Seen on the live panel 2026-11-16, clicking Connect on Dropbox:

    Dropbox connects by signing in, so there is nothing to paste. If no
    Connect button appears, IO's Dropbox app is not set up on this
    server yet.

    Dropbox connects by signing in, and IO's Dropbox app is not set up on
    this server yet. Nothing to paste.

The same thing twice, and the first one is conditional ("if no Connect
button appears") to a person who has just pressed Connect, which reads as
though the panel does not know its own state.

It comes from two places that each have a good reason to exist:

  * `provider.where` is the subtitle, and for a paste-a-token app it is
    genuinely useful: it says where to go and get the credential.
  * the panel's own block, which fires only when there is no paste form
    AND no OAuth app, and which is the DEFINITE statement: this
    deployment cannot connect this app at all.

So the rule is about which one owns the sentence. The panel's block owns
it, because only the panel knows whether the button is there. A
provider's `where` must not try to say it as well, and the subtitle steps
aside when the block is going to fire.
"""
import os
import re

os.environ.setdefault("AIUI_FERNET_KEY",
                      "SFNQQkFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import connections as C

PANEL = os.path.join(os.path.dirname(__file__), "..", "..", "gdrive",
                     "integrations-ui.js")

#: The sentence the panel owns. Matched loosely on the distinctive part,
#: because the wording around it is allowed to change.
OWNED = "not set up on this server"


def _panel():
    return open(PANEL, encoding="utf-8").read()


def test_the_panel_still_says_it():
    """If this disappears, the tests below pass by saying nothing."""
    assert _panel().count(OWNED) == 1, (
        "the panel should state exactly once that this deployment cannot "
        "connect an app; found %d" % _panel().count(OWNED))


def test_no_provider_repeats_what_the_panel_owns():
    """A provider that says it too is the duplicate a person reads."""
    guilty = [p.id for p in C.PROVIDERS.values()
              if OWNED in (p.where or "")]
    assert guilty == [], (
        "these providers repeat a sentence the panel already says, so it "
        "appears twice on the card: " + ", ".join(guilty))


def test_a_provider_with_no_paste_form_does_not_talk_about_the_button():
    """"If no Connect button appears" is a guess about the panel's state,
    written in a string that cannot see it."""
    guilty = [p.id for p in C.PROVIDERS.values()
              if re.search(r"if no connect button", p.where or "", re.I)]
    assert guilty == [], (
        "these guess at whether the panel drew a button: "
        + ", ".join(guilty))


def test_the_subtitle_stands_aside_when_the_panel_will_say_it():
    """Belt and braces: even a future provider whose `where` is innocent
    must not have its subtitle printed above the definite statement."""
    src = _panel()
    assert "meta.where" in src, "the subtitle no longer reads `where`"
    # The subtitle is one conditional expression. Read it whole, from the
    # assignment that starts it to the `where` it ends on, rather than
    # guessing at a window of characters: the first version of this test
    # guessed 6000 and landed in the middle of the OAuth handler.
    start = src.index("sub.textContent")
    end = src.index("meta.where", start)
    chain = src[start:end]
    assert re.search(r"!fields\.length\s*&&\s*!meta\.oauth", chain), (
        "the subtitle must step aside when the no-connector block is "
        "going to fire, or the card says the same thing twice. The "
        "expression was:\n" + chain)


def test_the_providers_that_have_no_paste_form_still_explain_themselves():
    """Stepping aside must not leave a blank card for an app that IS
    configured: `where` is what a connectable sign-in app shows."""
    for pid in ("dropbox", "outlook"):
        p = C.provider(pid)
        assert p is not None, pid
        assert p.fields == [], "%s should have no paste form" % pid
        assert "signing in" in (p.where or "").lower(), (
            "%s should still say it connects by signing in" % pid)
