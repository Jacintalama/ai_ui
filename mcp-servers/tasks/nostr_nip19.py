"""NIP-19 bech32 identifiers: the nsec/npub forms a person actually copies.

Nostr keys are 32 raw bytes, but nothing shows them that way. Buzz hands its
users an `nsec1...` and displays an `npub1...`, so those are the strings that
arrive in the Channels form and the ones a user can recognise on the page.

bech32 carries a checksum, which is the point of accepting this form rather
than raw hex: a key with a typo is rejected here, immediately and with a reason
the user can act on, instead of connecting as an identity nobody owns and
failing later as a silent authentication refusal from the relay.

Reference: BIP-173 for the encoding, NIP-19 for the prefixes.
"""
CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

#: The prefixes this codebase handles. NIP-19 defines more (note, nprofile,
#: nevent), and they carry TLV payloads rather than a bare key, so they are
#: refused rather than half-parsed.
PRIVATE = "nsec"
PUBLIC = "npub"


class Bech32Error(ValueError):
    """Malformed identifier. Message is safe to show a user."""


def _polymod(values) -> int:
    generator = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp: str) -> list:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _convertbits(data, frombits: int, tobits: int, pad: bool):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        # Leftover bits that are not zero padding mean the payload was not a
        # whole number of bytes. Accepting it would silently truncate a key.
        return None
    return ret


def decode(text: str, expect: str) -> bytes:
    """`nsec1...`/`npub1...` to the 32 raw bytes, or raise Bech32Error.

    `expect` is required rather than inferred. Pasting an npub where an nsec
    belongs is the likely mistake, and it has to fail loudly: IO would connect
    with a public key as a private key, producing a valid-looking identity that
    is not the user's and cannot be reached.
    """
    text = (text or "").strip()
    if not text:
        raise Bech32Error("No key given.")
    # A key is copied from another window, and bech32 is case-insensitive but
    # must not be mixed, so normalise rather than reject on capitalisation.
    if text.lower() != text and text.upper() != text:
        raise Bech32Error("That key mixes upper and lower case.")
    text = text.lower()

    pos = text.rfind("1")
    if pos < 1 or pos + 7 > len(text):
        raise Bech32Error("That does not look like a Nostr key.")
    hrp, data_part = text[:pos], text[pos + 1:]
    if hrp != expect:
        raise Bech32Error(f"That is a {hrp or 'unknown'} key. Paste an {expect}.")
    if any(c not in CHARSET for c in data_part):
        raise Bech32Error("That key has characters that cannot appear in one.")

    data = [CHARSET.index(c) for c in data_part]
    if _polymod(_hrp_expand(hrp) + data) != 1:
        raise Bech32Error("That key is not complete or has a typo in it.")

    decoded = _convertbits(data[:-6], 5, 8, False)
    if decoded is None or len(decoded) != 32:
        raise Bech32Error("That key is the wrong length.")
    return bytes(decoded)


def encode(raw: bytes, hrp: str) -> str:
    """32 raw bytes to `npub1...`/`nsec1...`."""
    if len(raw) != 32:
        raise ValueError("a Nostr key is 32 bytes")
    data = _convertbits(raw, 8, 5, True)
    checksum_input = _hrp_expand(hrp) + data + [0, 0, 0, 0, 0, 0]
    polymod = _polymod(checksum_input) ^ 1
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(CHARSET[d] for d in data + checksum)


def shorten(npub: str) -> str:
    """`npub1abcd…wxyz`, for showing which identity is connected.

    A full npub is 63 characters and unreadable on a row. The ends are what
    a person compares against the key in their Buzz window.
    """
    return npub if len(npub) <= 20 else f"{npub[:12]}…{npub[-6:]}"
