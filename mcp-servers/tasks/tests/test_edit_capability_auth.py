"""current_admin_or_capability: task-scoped edit capability replaces the admin
gateway headers, bound to exactly one task_id; admin path unchanged."""
import importlib
import os
import uuid

import pytest
from fastapi import HTTPException


class _Req:
    def __init__(self, headers):
        self.headers = headers


def _auth(monkeypatch, secret="s3cr3t"):
    monkeypatch.setenv("OAUTH_STATE_SECRET", secret)
    import edit_capability
    importlib.reload(edit_capability)
    import auth
    importlib.reload(auth)
    return auth, edit_capability


def test_valid_capability_authorizes_matching_task(monkeypatch):
    auth, cap_mod = _auth(monkeypatch)
    tid = uuid.uuid4()
    cap = cap_mod.mint_capability("owner@x.com", "my-app", str(tid))
    user = auth.current_admin_or_capability(tid, _Req({"x-edit-capability": cap}))
    assert user.email == "owner@x.com"
    assert user.is_admin is False  # least privilege — role re-checked downstream


def test_capability_for_other_task_rejected(monkeypatch):
    auth, cap_mod = _auth(monkeypatch)
    cap = cap_mod.mint_capability("owner@x.com", "my-app", str(uuid.uuid4()))
    with pytest.raises(HTTPException) as ei:
        auth.current_admin_or_capability(uuid.uuid4(), _Req({"x-edit-capability": cap}))
    assert ei.value.status_code == 403


def test_expired_capability_rejected(monkeypatch):
    auth, cap_mod = _auth(monkeypatch)
    tid = uuid.uuid4()
    cap = cap_mod.mint_capability("owner@x.com", "my-app", str(tid), ttl=-1)
    with pytest.raises(HTTPException) as ei:
        auth.current_admin_or_capability(tid, _Req({"x-edit-capability": cap}))
    assert ei.value.status_code == 403


def test_no_capability_falls_back_to_admin_headers(monkeypatch):
    auth, _ = _auth(monkeypatch)
    tid = uuid.uuid4()
    # admin headers present → admin principal
    user = auth.current_admin_or_capability(
        tid, _Req({"x-user-email": "Admin@X.com", "x-user-admin": "true"}))
    assert user.email == "admin@x.com" and user.is_admin is True
    # neither capability nor admin → 403/401
    with pytest.raises(HTTPException):
        auth.current_admin_or_capability(tid, _Req({}))
