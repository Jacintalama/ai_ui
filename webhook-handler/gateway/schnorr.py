"""BIP-340 Schnorr signatures over secp256k1.

Every Nostr event is signed, so without this there is no Buzz channel. The
obvious implementation is `coincurve`, and this module uses it whenever it is
importable. It also carries a pure-Python implementation, for one reason: the
native wheel does not build on Windows, and a signing layer that can only be
exercised inside the production container is a signing layer nobody checks. The
repository already carries one tier of tests that has never run anywhere for
exactly that reason.

So both exist and `test_gateway_schnorr.py` asserts they agree wherever both
are installed. Production signs with the audited C library; a developer machine
signs with the Python and still runs every test.

The pure path is NOT constant time. Scalar multiplication branches on the bits
of the nonce, which is the classic side channel. It is the fallback rather than
the default precisely because of that, and the only way to observe the timing
is to already be executing code on the box that holds the key, at which point
the key is readable directly.

Reference: BIP-340. The tagged hashes and the even-y conventions below are the
parts everyone gets wrong, so each carries the reason it exists.
"""
import hashlib
import secrets

try:                                     # pragma: no cover - import-time only
    import coincurve
except Exception:                        # noqa: BLE001
    coincurve = None

#: The secp256k1 field and group order.
P = 2 ** 256 - 2 ** 32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    """sha256(sha256(tag) || sha256(tag) || msg).

    The doubled tag hash is what stops a signature made for one purpose from
    being replayed as another: an aux hash can never collide with a challenge
    hash even on identical bytes.
    """
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def _inv(a: int) -> int:
    return pow(a, P - 2, P)


def _add(p1, p2):
    """Affine point addition. None is the point at infinity."""
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = 3 * x1 * x1 * _inv(2 * y1) % P
    else:
        lam = (y2 - y1) * _inv(x2 - x1) % P
    x3 = (lam * lam - x1 - x2) % P
    return (x3, (lam * (x1 - x3) - y1) % P)


def _mul(k: int, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def _even(point) -> bool:
    return point[1] % 2 == 0


def _lift_x(x: int):
    """The point with this x and an even y, or None if x is not on the curve.

    Nostr identities are x-only: a pubkey is 32 bytes, and the y is recovered
    by this rule. Without the even-y convention a key would be ambiguous.
    """
    if x >= P:
        return None
    c = (pow(x, 3, P) + 7) % P
    y = pow(c, (P + 1) // 4, P)
    if pow(y, 2, P) != c:
        return None
    return (x, y if y % 2 == 0 else P - y)


def pubkey_from_seckey(seckey: bytes) -> bytes:
    """The 32-byte x-only public key for a private key.

    Pure Python always, even when coincurve is present: this runs once per
    saved credential, and having one implementation of it means the npub shown
    on the Channels page cannot differ between machines.
    """
    d = int.from_bytes(seckey, "big")
    if not 1 <= d <= N - 1:
        raise ValueError("private key out of range")
    return _mul(d, G)[0].to_bytes(32, "big")


def _pure_sign(msg32: bytes, seckey: bytes, aux: bytes) -> bytes:
    d0 = int.from_bytes(seckey, "big")
    if not 1 <= d0 <= N - 1:
        raise ValueError("private key out of range")
    point = _mul(d0, G)
    # Signing always happens as if the key had an even y, which is what makes
    # the 32-byte x-only pubkey enough to verify against.
    d = d0 if _even(point) else N - d0
    t = (d ^ int.from_bytes(_tagged_hash("BIP0340/aux", aux), "big"))
    rand = _tagged_hash(
        "BIP0340/nonce",
        t.to_bytes(32, "big") + point[0].to_bytes(32, "big") + msg32)
    k0 = int.from_bytes(rand, "big") % N
    if k0 == 0:                                        # pragma: no cover
        raise ValueError("nonce was zero, which cannot happen in practice")
    r_point = _mul(k0, G)
    k = k0 if _even(r_point) else N - k0
    e = int.from_bytes(_tagged_hash(
        "BIP0340/challenge",
        r_point[0].to_bytes(32, "big") + point[0].to_bytes(32, "big") + msg32,
    ), "big") % N
    return r_point[0].to_bytes(32, "big") + ((k + e * d) % N).to_bytes(32, "big")


def _pure_verify(msg32: bytes, pubkey: bytes, sig: bytes) -> bool:
    if len(sig) != 64 or len(pubkey) != 32 or len(msg32) != 32:
        return False
    point = _lift_x(int.from_bytes(pubkey, "big"))
    if point is None:
        return False
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    if r >= P or s >= N:
        return False
    e = int.from_bytes(_tagged_hash(
        "BIP0340/challenge", sig[:32] + pubkey + msg32), "big") % N
    computed = _add(_mul(s, G), _mul(N - e, point))
    if computed is None or not _even(computed):
        return False
    return computed[0] == r


def sign(msg32: bytes, seckey: bytes, aux: bytes | None = None) -> bytes:
    """Sign a 32-byte message (for Nostr, the event id).

    `aux` exists for the test vectors, which fix it to make signing
    deterministic. Left alone it is fresh randomness, which is what BIP-340
    recommends: it does not make the nonce secret, it makes a fault or a
    repeated message far less likely to leak the key.
    """
    if len(msg32) != 32:
        raise ValueError("BIP-340 signs exactly 32 bytes")
    if coincurve is not None and aux is None:
        return coincurve.PrivateKey(seckey).sign_schnorr(msg32)
    return _pure_sign(msg32, seckey, aux if aux is not None else secrets.token_bytes(32))


def verify(msg32: bytes, pubkey: bytes, sig: bytes) -> bool:
    """True if `sig` is a valid BIP-340 signature. Never raises."""
    try:
        if coincurve is not None:
            return coincurve.PublicKeyXOnly(pubkey).verify(sig, msg32)
        return _pure_verify(msg32, pubkey, sig)
    except Exception:                                  # noqa: BLE001
        return False
