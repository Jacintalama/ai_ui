"""current_user_or_capability_for_slug: the publish-modal read dep.

No capability header -> behaves like current_user (any signed-in user, admin
NOT required); the per-project member/role checks live inside each route.
"""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from auth import current_user_or_capability_for_slug


def _req(headers: dict) -> Request:
    scope = {"type": "http",
             "headers": [(k.lower().encode(), v.encode())
                         for k, v in headers.items()]}
    return Request(scope)


def test_plain_user_passes_without_admin():
    u = current_user_or_capability_for_slug("myapp", _req({"X-User-Email": "USER@x.com"}))
    assert u.email == "user@x.com"
    assert u.is_admin is False


def test_admin_header_carries_through():
    u = current_user_or_capability_for_slug("myapp", _req(
        {"X-User-Email": "a@x.com", "X-User-Admin": "true"}))
    assert u.is_admin is True


def test_missing_email_is_401():
    with pytest.raises(HTTPException) as e:
        current_user_or_capability_for_slug("myapp", _req({}))
    assert e.value.status_code == 401


def test_bad_capability_is_403():
    with pytest.raises(HTTPException) as e:
        current_user_or_capability_for_slug("myapp", _req(
            {"X-Edit-Capability": "not-a-real-capability"}))
    assert e.value.status_code == 403
