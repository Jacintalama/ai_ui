"""Environment these tests need, set before any test module is imported.

`oauth_state` reads its secret at import time and keeps it in module state, so
setting it inside a test file only works if that file happens to be imported
first. Not a real secret.
"""
import os

os.environ.setdefault("OAUTH_STATE_SECRET", "test-secret-for-signing-states")
