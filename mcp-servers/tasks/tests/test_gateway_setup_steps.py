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

def test_buzz_explains_its_setup_even_though_it_cannot_be_connected(monkeypatch):
    row = _buzz_off(monkeypatch)
    assert row["status"] == "off"
    assert row["setup"]["steps"], "an off row with no steps answers nothing"


def test_the_off_row_no_longer_gives_an_instruction_nobody_can_follow(monkeypatch):
    # "Message IO from Buzz" is only possible once IO is an agent in that
    # workspace. Said before then, it sends a user looking for something that
    # is not there and gives them no way to tell why.
    note = _buzz_off(monkeypatch)["note"].lower()
    assert "message io from buzz" not in note


def test_the_pairing_instruction_waits_until_io_is_actually_there(monkeypatch):
    monkeypatch.setenv("BUZZ_ENABLED", "1")
    assert "message io from buzz" in _row("buzz")["note"].lower()


def test_the_steps_name_both_things_a_user_has_to_fetch(monkeypatch):
    # A key without a relay, or a relay without a key, connects to nothing.
    joined = " ".join(_buzz_off(monkeypatch)["setup"]["steps"]).lower()
    assert "nsec1" in joined, "the user has to be told what the key looks like"
    assert "wss://" in joined, "and where the relay URL comes from"


def test_the_setup_says_why_it_will_not_take_the_key_yet(monkeypatch):
    # The fields render disabled. A form that silently does nothing is the one
    # thing no control on this page is allowed to be.
    assert _buzz_off(monkeypatch)["setup"]["blocked"].strip()


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


def test_the_setup_fields_are_rendered_disabled():
    assert "input.disabled = true" in HTML


def test_the_button_says_set_up_rather_than_connect():
    # It does not connect anything. Calling it Connect is the same lie in a
    # smaller place.
    assert '"Set up"' in HTML


def test_setup_gives_way_to_the_real_path_once_the_channel_goes_live():
    # Otherwise the day Buzz works, the row still shows preparation steps
    # instead of the way in.
    assert 'c.setup && c.status !== "available"' in HTML


def test_the_setup_block_still_builds_its_dom_safely():
    # Everything here is a server-supplied string rendered into the page.
    assert "innerHTML" not in HTML
