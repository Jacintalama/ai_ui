"""A channel this server cannot reach on its own still has to explain itself.

Buzz is the case that forced this. Every other channel is reached by IO calling
somebody's API, so connecting is entirely our side of the work. Buzz is a Nostr
workspace: IO is not called at all, it joins the workspace as an agent, which
somebody who owns that workspace has to mint first.

The row used to paper over that difference by borrowing Telegram's sentence,
"Message IO from Buzz and it will reply with a code". No Buzz user could carry
that out, because IO was not in their workspace to be messaged, and the page
offered no other clue. The whole point of these tests is that the page answers
the question the row exists to raise: how do I connect this?
"""
import os
import pathlib

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import routes_gateway as rg

PAGE = pathlib.Path(__file__).resolve().parents[1] / "static" / "gateway-link.html"
HTML = PAGE.read_text(encoding="utf-8")


def _row(platform, **env):
    entry = next(c for c in rg.CHANNEL_CATALOGUE if c["platform"] == platform)
    return rg._channel_status(entry, {})


def _buzz_off(monkeypatch):
    monkeypatch.delenv("BUZZ_ENABLED", raising=False)
    return _row("buzz")


# --- what the server describes ----------------------------------------------

def test_buzz_explains_its_setup(monkeypatch):
    row = _buzz_off(monkeypatch)
    assert row["setup"]["steps"], "a row with no steps answers nothing"


def test_the_off_row_no_longer_gives_an_instruction_nobody_can_follow(monkeypatch):
    # "Message IO from Buzz" is only possible once IO is an agent in that
    # workspace. Said before then, it sends a user looking for something that
    # is not there and gives them no way to tell why.
    note = _buzz_off(monkeypatch)["note"].lower()
    assert "message io from buzz" not in note


def test_the_pairing_instruction_waits_until_io_is_actually_there(monkeypatch):
    monkeypatch.setenv("BUZZ_ENABLED", "1")
    assert "message io from buzz" in _row("buzz")["note"].lower()


def test_the_only_thing_a_user_has_to_find_is_the_relay_url(monkeypatch):
    # The steps used to send someone into Buzz to "create an agent identity",
    # which Buzz has no way to do: Nostr identities are not issued by anyone.
    # Asking for one made the form require something a user could not produce.
    # IO mints its own, so the relay URL is the whole search.
    joined = " ".join(_buzz_off(monkeypatch)["setup"]["steps"]).lower()
    assert "wss://" in joined, "the user still has to be told what to look for"
    assert "create an agent identity" not in joined


def test_the_key_is_optional_and_says_so(monkeypatch):
    key = next(f for f in rg.CONNECT_FORMS["buzz"]["fields"] if f["name"] == "token")
    assert "optional" in key["label"].lower()
    assert key["secret"] is True, "it is still stored encrypted when given"


def test_a_generated_key_is_a_usable_nostr_identity():
    # Retried inside new_agent_key if random bytes land outside the group
    # order, which would produce a key that cannot sign.
    import nostr_nip19
    import nostr_schnorr
    seen = set()
    for _ in range(25):
        nsec = rg.new_agent_key()
        assert nsec.startswith("nsec1")
        raw = nostr_nip19.decode(nsec, "nsec")
        assert len(nostr_schnorr.pubkey_from_seckey(raw)) == 32
        seen.add(nsec)
    assert len(seen) == 25, "generated the same identity twice"


def test_the_saved_identity_is_offered_to_be_copied_elsewhere(monkeypatch):
    # A workspace that only admits invited members needs IO's public key, and
    # a 63 character npub is not something anyone retypes.
    row = _buzz_off(monkeypatch)
    assert row["identity_public"]["label"].strip()
    assert "npub" in row["identity_public"]["help"]
    assert "c.identity_public" in HTML


def test_only_buzz_asks_a_user_to_carry_an_identity_elsewhere():
    carriers = [c["platform"] for c in rg.CHANNEL_CATALOGUE
                if rg._channel_status(c, {})["identity_public"]]
    assert carriers == ["buzz"]


def test_the_last_step_ends_where_the_user_actually_continues(monkeypatch):
    last = _buzz_off(monkeypatch)["setup"]["steps"][-1].lower()
    assert "code" in last


def test_the_preview_asks_for_the_same_fields_the_real_form_will(monkeypatch):
    # The disabled fields are drawn from connect_form, not invented alongside
    # it, so the preview cannot drift from what is eventually accepted.
    row = _buzz_off(monkeypatch)
    names = {f["name"] for f in row["connect_form"]["fields"]}
    assert names == {"endpoint", "token"}


def test_every_row_carries_a_setup_slot():
    # One shape for every row, so a channel cannot quietly omit it.
    for entry in rg.CHANNEL_CATALOGUE:
        assert "setup" in rg._channel_status(entry, {})


def test_only_a_channel_we_cannot_reach_alone_carries_setup():
    # Everything else is an API we call. Adding steps to those rows would be
    # busywork shown to a user who has nothing to do.
    needs = [c["platform"] for c in rg.CHANNEL_CATALOGUE
             if rg._channel_status(c, {})["setup"]]
    assert needs == ["buzz"]


# --- what the page does with it ---------------------------------------------

def test_a_row_with_setup_can_be_opened():
    # Without this it stays a disabled button, and the reason lives in one
    # line of small print that cannot explain a three-step process.
    assert "|| !!c.setup" in HTML


def test_the_steps_sit_directly_above_the_form_they_explain():
    # Separated, they read as two unrelated things and a user fills in fields
    # whose values they have not been told how to get.
    assert "if (c.setup) box.appendChild(setupSteps(c));" in HTML


def test_the_form_is_named_for_what_it_connects():
    # "Use my own bot" over the Buzz fields sends someone looking for a bot
    # token that does not exist in Buzz.
    assert 'c.connect_form.title' in HTML
    assert rg.CONNECT_FORMS["buzz"]["title"] == "Connect my Buzz workspace"


def test_a_channel_with_setup_but_no_way_in_still_says_set_up():
    # Kept for the next channel in this position. Buzz has a live form now, so
    # its own button reads Connect.
    assert '"Set up"' in HTML


def test_the_setup_block_still_builds_its_dom_safely():
    # Everything here is a server-supplied string rendered into the page.
    assert "innerHTML" not in HTML


def test_a_channel_with_no_shared_bot_puts_its_own_form_first():
    # Buzz has no identity IO runs for everyone, so pasting a pairing code is
    # impossible until the user's own workspace is connected. Rendered in the
    # other order, the page showed a code box above the form that makes codes
    # possible, which is step two above step one.
    assert "const bringFirst = c.can_bring_bot && !c.has_shared_bot;" in HTML
    assert "if (bringFirst) panel.append(botSection(c, load));" in HTML


def test_telegram_keeps_the_quick_path_first():
    # There IS a bot anyone can message, so the fastest way in stays on top and
    # bringing your own stays the alternative below it.
    rows = {c["platform"]: rg._channel_status(c, {}) for c in rg.CHANNEL_CATALOGUE}
    assert rows["telegram"]["has_shared_bot"] is True
    assert rows["buzz"]["has_shared_bot"] is False


def test_every_row_says_whether_io_runs_a_bot_there():
    for entry in rg.CHANNEL_CATALOGUE:
        assert "has_shared_bot" in rg._channel_status(entry, {})
