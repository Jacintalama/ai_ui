"""Environment these tests need, set before any test module is imported.

Both `crypto_utils` and `oauth_state` read their secrets at import time and
keep them in module state, and a test module that imports `main` pulls both
in. So setting these inside a test file only works if that file happens to be
imported first: collection order decided whether the suite passed, which it
did here until a second test module arrived.

Neither value is a real secret.
"""
import base64
import os

os.environ.setdefault("AIUI_FERNET_KEY",
                      base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-for-signing-states")
