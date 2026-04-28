"""Round-trip + key-handling tests for crypto_utils."""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import pytest



def test_encrypt_decrypt_round_trip(monkeypatch):
    monkeypatch.setenv("AIUI_FERNET_KEY", _AIUI_TEST_KEY)
    from importlib import reload
    import crypto_utils
    reload(crypto_utils)

    plain = "eyJhbGciOiJIUzI1NiJ9.example.payload"
    enc = crypto_utils.encrypt(plain)
    assert enc != plain
    assert crypto_utils.decrypt(enc) == plain


def test_decrypt_with_wrong_key_raises(monkeypatch):
    monkeypatch.setenv("AIUI_FERNET_KEY", _AIUI_TEST_KEY)
    from importlib import reload
    import crypto_utils
    reload(crypto_utils)
    enc = crypto_utils.encrypt("hello")

    monkeypatch.setenv("AIUI_FERNET_KEY", _AIUI_TEST_KEY)
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