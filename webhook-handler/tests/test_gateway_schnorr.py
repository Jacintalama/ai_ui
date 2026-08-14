"""BIP-340 signing, checked against the BIP's own vectors.

A signature layer that only round-trips against itself proves nothing: an
implementation can be self-consistently wrong and every event it signs is then
rejected by a relay with no error saying why. The vectors below are from the
BIP-340 specification, so a mistake fails against the standard.
"""
import pytest

from gateway import schnorr

# BIP-340 test vectors: (seckey, pubkey, aux, msg, sig)
VECTORS = [
    ("0000000000000000000000000000000000000000000000000000000000000003",
     "F9308A019258C31049344F85F89D5229B531C845836F99B08601F113BCE036F9",
     "0000000000000000000000000000000000000000000000000000000000000000",
     "0000000000000000000000000000000000000000000000000000000000000000",
     "E907831F80848D1069A5371B402410364BDF1C5F8307B0084C55F1CE2DCA8215"
     "25F66A4A85EA8B71E482A74F382D2CE5EBEEE8FDB2172F477DF4900D310536C0"),
    ("B7E151628AED2A6ABF7158809CF4F3C762E7160F38B4DA56A784D9045190CFEF",
     "DFF1D77F2A671C5F36183726DB2341BE58FEAE1DA2DECED843240F7B502BA659",
     "0000000000000000000000000000000000000000000000000000000000000001",
     "243F6A8885A308D313198A2E03707344A4093822299F31D0082EFA98EC4E6C89",
     "6896BD60EEAE296DB48A229FF71DFE071BDE413E6D43F917DC8DCF8C78DE3341"
     "8906D11AC976ABCCB20B091292BFF4EA897EFCB639EA871CFA95F6DE339E4B0A"),
    ("C90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B14E5C9",
     "DD308AFEC5777E13121FA72B9CC1B7CC0139715309B086C960E18FD969774EB8",
     "C87AA53824B4D7AE2EB035A2B5BBBCCC080E76CDC6D1692C4B0B62D798E6D906",
     "7E2D58D8B3BCDF1ABADEC7829054F90DDA9805AAB56C77333024B9D0A508B75C",
     "5831AAEED7B44BB74E5EAB94BA9D4294C49BCF2A60728D8B4C200F50DD313C1B"
     "AB745879A5AD954A72C45A91C3A51D3C7ADEA98D82F8481E0E1E03674A6F3FB7"),
]


def _b(hexstr):
    return bytes.fromhex(hexstr)


@pytest.mark.parametrize("sk,pk,aux,msg,sig", VECTORS)
def test_the_public_key_matches_the_specification(sk, pk, aux, msg, sig):
    assert schnorr.pubkey_from_seckey(_b(sk)).hex().upper() == pk


@pytest.mark.parametrize("sk,pk,aux,msg,sig", VECTORS)
def test_signing_reproduces_the_specifications_signature(sk, pk, aux, msg, sig):
    # Deterministic given aux, which is the whole reason the vectors fix it.
    got = schnorr._pure_sign(_b(msg), _b(sk), _b(aux))
    assert got.hex().upper() == sig


@pytest.mark.parametrize("sk,pk,aux,msg,sig", VECTORS)
def test_the_specifications_signatures_verify(sk, pk, aux, msg, sig):
    assert schnorr._pure_verify(_b(msg), _b(pk), _b(sig)) is True


def test_a_tampered_message_does_not_verify():
    sk, pk, aux, msg, sig = VECTORS[1]
    other = bytes.fromhex(msg)[:-1] + b"\x00"
    assert schnorr._pure_verify(other, _b(pk), _b(sig)) is False


def test_a_tampered_signature_does_not_verify():
    sk, pk, aux, msg, sig = VECTORS[1]
    bad = bytearray(_b(sig))
    bad[-1] ^= 1
    assert schnorr._pure_verify(_b(msg), _b(pk), bytes(bad)) is False


def test_another_key_does_not_verify():
    _, _, _, msg, sig = VECTORS[1]
    assert schnorr._pure_verify(_b(msg), _b(VECTORS[0][1]), _b(sig)) is False


def test_a_pubkey_that_is_not_on_the_curve_is_refused():
    # lift_x has no solution here, and returning a point anyway would let a
    # made-up identity verify against something.
    assert schnorr._pure_verify(b"\x01" * 32, b"\xff" * 32, b"\x00" * 64) is False


def test_garbage_lengths_are_refused_rather_than_raising():
    # verify() is called on whatever a relay sends. It must answer false, not
    # explode inside the read loop and drop the connection.
    assert schnorr.verify(b"", b"", b"") is False
    assert schnorr.verify(b"\x01" * 32, b"\x02" * 32, b"\x03" * 10) is False


def test_a_private_key_outside_the_group_is_refused():
    for bad in (b"\x00" * 32, (schnorr.N).to_bytes(32, "big")):
        with pytest.raises(ValueError):
            schnorr.pubkey_from_seckey(bad)


def test_signing_is_randomised_when_no_aux_is_given():
    # Same key, same message, different signature. Both must verify. A fixed
    # nonce here would be the classic key-recovery bug.
    sk = _b(VECTORS[1][0])
    msg = _b(VECTORS[1][3])
    a = schnorr.sign(msg, sk)
    b = schnorr.sign(msg, sk)
    pk = schnorr.pubkey_from_seckey(sk)
    assert a != b
    assert schnorr.verify(msg, pk, a) and schnorr.verify(msg, pk, b)


def test_a_signature_round_trips_through_the_public_entry_points():
    sk = bytes.fromhex("11" * 32)
    pk = schnorr.pubkey_from_seckey(sk)
    msg = bytes.fromhex("22" * 32)
    assert schnorr.verify(msg, pk, schnorr.sign(msg, sk))


def test_signing_refuses_anything_but_a_32_byte_digest():
    # Nostr signs an event id. Passing the event body by mistake would produce
    # a signature over the wrong thing that still looks fine.
    with pytest.raises(ValueError):
        schnorr.sign(b"not a digest", bytes.fromhex("11" * 32))


@pytest.mark.skipif(schnorr.coincurve is None, reason="coincurve not installed")
def test_the_two_implementations_agree():
    # Production signs with the C library and every test above exercises the
    # Python. This is the only thing tying them together, so it runs wherever
    # both exist: on the server, and in CI if coincurve is ever added there.
    sk = bytes.fromhex("42" * 32)
    pk = schnorr.pubkey_from_seckey(sk)
    assert pk == bytes(schnorr.coincurve.PrivateKey(sk).public_key_xonly.format())
    for i in range(8):
        msg = bytes.fromhex(f"{i:02x}" * 32)
        native = schnorr.coincurve.PrivateKey(sk).sign_schnorr(msg)
        assert schnorr._pure_verify(msg, pk, native), "python rejects C's signature"
        assert schnorr.coincurve.PublicKeyXOnly(pk).verify(
            schnorr._pure_sign(msg, sk, bytes(32)), msg), "C rejects python's"
