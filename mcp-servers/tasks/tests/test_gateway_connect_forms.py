"""What a user has to fill in to connect a channel with their own credentials.

Described on the server so that adding a channel is a catalogue entry rather
than new UI. Before this, Telegram's fields were written into the page's
markup, which meant no other channel could be set up from the browser at all.
"""
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      "hUZ3RkVvY0JmS3FnWlp4TXcyN0RkNTZWc1RCQzNKS1E=")

import routes_gateway as rg


def form(platform):
    return rg.CONNECT_FORMS[platform]


def test_telegram_still_tells_a_user_where_to_get_a_token():
    fields = {f["name"]: f for f in form("telegram")["fields"]}
    assert "BotFather" in fields["token"]["help"]


def test_a_credential_field_is_marked_secret():
    # `secret` drives two things at once: the field renders as a password and
    # its value is the one encrypted at rest. A credential that is not marked
    # would be shoulder-readable AND stored in the clear.
    assert form("telegram")["fields"][0]["secret"] is True
    buzz = {f["name"]: f for f in form("buzz")["fields"]}
    assert buzz["token"]["secret"] is True


def test_a_non_secret_field_is_not_marked_secret():
    # The relay URL is not a credential, and hiding it would stop a user
    # checking they typed their own workspace correctly.
    buzz = {f["name"]: f for f in form("buzz")["fields"]}
    assert buzz["endpoint"]["secret"] is False


def test_buzz_asks_for_a_workspace_and_a_key():
    names = [f["name"] for f in form("buzz")["fields"]]
    assert names == ["endpoint", "token"], (
        "relay first: a user picks the workspace before the identity in it")


def test_every_field_can_be_rendered_without_guessing():
    # The page draws these blind. A field missing any of these would render
    # as an unlabelled box.
    for platform, spec in rg.CONNECT_FORMS.items():
        assert spec["pitch"].strip(), platform
        assert spec["submit"].strip(), platform
        for f in spec["fields"]:
            assert f["label"].strip(), (platform, f)
            assert isinstance(f["secret"], bool), (platform, f)
            assert "placeholder" in f and "help" in f, (platform, f)


def test_the_pitch_says_what_saving_grants():
    # The only place a user is told what they are agreeing to. Boilerplate
    # here would mean nobody ever learns it.
    for platform, spec in rg.CONNECT_FORMS.items():
        assert "IO" in spec["pitch"], platform
        assert "Nobody else" in spec["pitch"], platform


def test_a_channel_that_cannot_carry_a_connection_offers_no_form():
    row = rg._channel_status(
        next(c for c in rg.CHANNEL_CATALOGUE if c["platform"] == "cli"), {})
    assert row["connect_form"] is None


def test_every_form_belongs_to_a_real_channel():
    known = {c["platform"] for c in rg.CHANNEL_CATALOGUE}
    assert set(rg.CONNECT_FORMS) <= known


def test_a_credential_is_never_displayed_in_capitals_it_must_not_be_typed_in():
    # The page styles the pairing code uppercase, because a code is
    # case-insensitive and easier to read spaced out. That rule was written
    # against every input on the page, so a bot token, a relay URL and an
    # nsec key were all displayed in capitals while storing what was actually
    # typed. Case matters in all three, and the mismatch is invisible: the
    # value is right and looks wrong.
    import pathlib
    html = (pathlib.Path(__file__).resolve().parents[1]
            / "static" / "gateway-link.html").read_text(encoding="utf-8")
    assert ".entry input { letter-spacing" in html
    for line in html.splitlines():
        stripped = line.strip()
        if stripped.startswith("input {"):
            block = html.split(stripped, 1)[1].split("}", 1)[0]
            assert "text-transform" not in block, (
                "uppercase belongs to the code box, not to every field")
