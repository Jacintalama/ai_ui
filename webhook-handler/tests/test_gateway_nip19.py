"""The key format a user actually pastes.

The vectors are NIP-19's own worked examples. bech32 is checksummed, so a
mistyped vector here fails on the checksum rather than quietly asserting
something wrong, which is what makes these worth pinning.
"""
import pytest

from gateway import nip19

# From NIP-19.
NSEC = "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5"
NSEC_HEX = "67dea2ed018072d675f5415ecfaed7d2597555e202d85b3d65ea4e58d2d92ffa"
NPUB = "npub10elfcs4fr0l0r8af98jlmgdh9c8tcxjvz9qkw038js35mp4dma8qzvjptg"
NPUB_HEX = "7e7e9c42a91bfef19fa929e5fda1b72e0ebc1a4c1141673e2794234d86addf4e"


def test_the_specifications_private_key_decodes():
    assert nip19.decode(NSEC, "nsec").hex() == NSEC_HEX


def test_the_specifications_public_key_decodes():
    assert nip19.decode(NPUB, "npub").hex() == NPUB_HEX


def test_encoding_is_the_inverse_of_decoding():
    assert nip19.encode(bytes.fromhex(NSEC_HEX), "nsec") == NSEC
    assert nip19.encode(bytes.fromhex(NPUB_HEX), "npub") == NPUB


def test_a_public_key_pasted_where_a_private_one_belongs_is_refused():
    # The likely mistake, and the dangerous one: IO would connect using a
    # public key as its private key, producing an identity nobody owns and an
    # authentication failure with no obvious cause.
    with pytest.raises(nip19.Bech32Error) as e:
        nip19.decode(NPUB, "nsec")
    assert "npub" in str(e.value) and "nsec" in str(e.value)


def test_a_typo_is_caught_by_the_checksum():
    # This is the whole reason for accepting bech32 rather than raw hex.
    bad = NSEC[:-1] + ("q" if NSEC[-1] != "q" else "p")
    with pytest.raises(nip19.Bech32Error):
        nip19.decode(bad, "nsec")


def test_a_truncated_key_is_refused():
    with pytest.raises(nip19.Bech32Error):
        nip19.decode(NSEC[:40], "nsec")


def test_an_empty_value_says_so_plainly():
    with pytest.raises(nip19.Bech32Error) as e:
        nip19.decode("   ", "nsec")
    assert "No key" in str(e.value)


def test_something_that_is_not_a_key_at_all_is_refused():
    for junk in ("hello", "1", "nsec", "wss://relay.example", "nsec1"):
        with pytest.raises(nip19.Bech32Error):
            nip19.decode(junk, "nsec")


def test_characters_outside_the_alphabet_are_refused():
    # b, i, o and 1 are excluded from bech32 precisely because they are
    # misread. Saying so beats a checksum error the user cannot interpret.
    with pytest.raises(nip19.Bech32Error) as e:
        nip19.decode("nsec1bbbbio", "nsec")
    assert "cannot appear" in str(e.value)


def test_surrounding_whitespace_from_a_paste_is_tolerated():
    assert nip19.decode("  " + NSEC + "\n", "nsec").hex() == NSEC_HEX


def test_capitalisation_from_a_paste_is_tolerated():
    assert nip19.decode(NSEC.upper(), "nsec").hex() == NSEC_HEX


def test_mixed_case_is_refused_rather_than_guessed():
    # bech32 forbids it: the checksum is defined over one case, so a mixed
    # string is corrupt rather than merely untidy.
    with pytest.raises(nip19.Bech32Error):
        nip19.decode(NSEC[:20].upper() + NSEC[20:], "nsec")


def test_a_key_is_shortened_for_display_at_both_ends():
    # A person compares the ends against what Buzz shows them, so both must
    # survive. Truncating one end would make two identities look identical.
    short = nip19.shorten(NPUB)
    assert short.startswith(NPUB[:12]) and short.endswith(NPUB[-6:])
    assert len(short) < len(NPUB)


def test_the_round_trip_holds_for_arbitrary_keys():
    for i in range(0, 256, 37):
        raw = bytes([i]) * 32
        assert nip19.decode(nip19.encode(raw, "npub"), "npub") == raw
