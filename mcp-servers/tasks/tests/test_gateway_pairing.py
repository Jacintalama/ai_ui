"""Pairing code primitives.

Codes are hashed at rest so a database leak grants nothing, and the alphabet
excludes 0/O/1/I because these get read off a phone screen and typed into a
browser by hand.
"""
import gateway_pairing as gp


def test_code_shape():
    code = gp.generate_code()
    assert len(code) == gp.CODE_LENGTH == 8
    assert set(code) <= set(gp.CODE_ALPHABET)


def test_alphabet_excludes_confusable_characters():
    for ch in "01OI":
        assert ch not in gp.CODE_ALPHABET


def test_codes_are_not_repeated_across_many_draws():
    codes = {gp.generate_code() for _ in range(500)}
    assert len(codes) > 490          # 32**8 space; collisions here mean a bad RNG


def test_hash_is_not_the_code():
    code = gp.generate_code()
    digest = gp.hash_code(code)
    assert code not in digest
    assert len(digest) == 64


def test_matching_is_case_and_whitespace_insensitive():
    code = gp.generate_code()
    digest = gp.hash_code(code)
    assert gp.codes_match(code.lower(), digest)
    assert gp.codes_match(f"  {code[:4]} {code[4:]}  ", digest)


def test_a_wrong_code_does_not_match():
    digest = gp.hash_code("ABCD2345")
    assert not gp.codes_match("ABCD2346", digest)


def test_matching_against_an_empty_hash_is_false():
    assert not gp.codes_match("ABCD2345", "")


def test_normalize_strips_junk_but_keeps_order():
    assert gp.normalize_code(" ab-cd 2345 ") == "ABCD2345"
