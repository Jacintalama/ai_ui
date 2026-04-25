"""Round-trip + key-handling tests for crypto_utils."""
import pytest


def test_encrypt_decrypt_round_trip(monkeypatch):
    monkeypatch.setenv("AIUI_FERNET_KEY", "v3KGZ9ZpQAQ-HeaR_R-nXvI3T8cPOFYYJQHe3VJYJpw=")
    from importlib import reload
    import crypto_utils
    reload(crypto_utils)

    plain = "eyJhbGciOiJIUzI1NiJ9.example.payload"
    enc = crypto_utils.encrypt(plain)
    assert enc != plain
    assert crypto_utils.decrypt(enc) == plain


def test_decrypt_with_wrong_key_raises(monkeypatch):
    monkeypatch.setenv("AIUI_FERNET_KEY", "v3KGZ9ZpQAQ-HeaR_R-nXvI3T8cPOFYYJQHe3VJYJpw=")
    from importlib import reload
    import crypto_utils
    reload(crypto_utils)
    enc = crypto_utils.encrypt("hello")

    monkeypatch.setenv("AIUI_FERNET_KEY", "yvULp7B9z1Hbj2vU9GvrPK0p3Z4F5K1d_W6mV5L9bIo=")
    reload(crypto_utils)
    from cryptography.fernet import InvalidToken
    with pytest.raises(InvalidToken):
        crypto_utils.decrypt(enc)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("AIUI_FERNET_KEY", raising=False)
    from importlib import reload
    import crypto_utils
    with pytest.raises(RuntimeError, match="AIUI_FERNET_KEY"):
        reload(crypto_utils)
