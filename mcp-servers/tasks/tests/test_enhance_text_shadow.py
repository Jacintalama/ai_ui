"""Regression: enhance() must not shadow the module-level sqlalchemy text().

A local variable named `text` in enhance() made `text` a function-local for
the whole function, so the advisory-lock call
`text("SELECT pg_advisory_xact_lock(...)")` (which runs BEFORE the assignment)
raised `UnboundLocalError` on EVERY /enhance call — a live 500 on 2026-06-18
(reproduced by attaching a PDF, but it broke text-only enhances too). The
attachment-text local must not be named `text`. The route itself needs
Postgres, so this guards the exact scoping footgun directly.
"""
import base64
import os

# env-before-import: routes_tasks -> crypto_utils requires a Fernet key, and
# db reads DATABASE_URL at import (it does not connect here).
os.environ.setdefault("AIUI_FERNET_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
os.environ.setdefault("DATABASE_URL", "postgresql://t:t@localhost/test")

import routes_tasks  # noqa: E402


def test_enhance_does_not_shadow_sqlalchemy_text():
    assert "text" not in routes_tasks.enhance.__code__.co_varnames, (
        "enhance() assigns a local named `text`, shadowing the sqlalchemy "
        "text() import used at the advisory-lock call (line ~829) -> "
        "UnboundLocalError on every /enhance. Rename the local."
    )


def test_module_text_is_sqlalchemy_text():
    # Sanity: the module-level `text` is the SQLAlchemy text() construct.
    from sqlalchemy import text as sa_text
    assert routes_tasks.text is sa_text
