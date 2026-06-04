"""Read the trusted gateway headers and expose the current admin user."""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class AdminUser:
    email: str
    is_admin: bool


def current_admin(request: Request) -> AdminUser:
    """FastAPI dependency. Returns the current admin or raises 401/403."""
    # Normalize email to lowercase here so every downstream comparison sees
    # the canonical form. The gateway does not normalize; mismatched case
    # would otherwise silently fail role checks against lowercased DB rows.
    email = request.headers.get("x-user-email", "").strip().lower()
    is_admin = request.headers.get("x-user-admin", "").strip().lower() == "true"
    if not email:
        raise HTTPException(status_code=401, detail="Missing X-User-Email")
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return AdminUser(email=email, is_admin=True)


@dataclass(frozen=True)
class CurrentUser:
    email: str


def current_user(request: Request) -> CurrentUser:
    """FastAPI dep — like current_admin but no admin gate.

    Used by list-my-* endpoints that any authenticated user should reach.
    Email is lowercased to match the canonical form used in DB rows.
    """
    email = request.headers.get("x-user-email", "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Missing X-User-Email")
    return CurrentUser(email=email)


def current_admin_or_capability(task_id: UUID, request: Request) -> AdminUser:
    """FastAPI dep for the Visual Editor: accept EITHER the admin gateway
    headers OR a single-task edit capability (`X-Edit-Capability`).

    When a capability is present it must be valid and bound to THIS exact
    `task_id`; we then return the owner as a NON-admin principal so the
    endpoint's `_require_role(..., is_admin=False)` still re-checks the owner's
    live role on the app (least privilege — a stale or revoked role is caught).
    A capability never falls back to `current_admin`, so it works behind the
    gateway's `X-User-Admin: false`. With no capability header, behavior is the
    unchanged admin path."""
    cap = request.headers.get("x-edit-capability", "").strip()
    if cap:
        from edit_capability import verify_capability
        data = verify_capability(cap)
        if not data or data["task_id"] != str(task_id):
            raise HTTPException(status_code=403, detail="Invalid edit capability")
        return AdminUser(email=(data["owner"] or "").strip().lower(),
                         is_admin=False)
    return current_admin(request)
