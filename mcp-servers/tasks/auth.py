"""Read the trusted gateway headers and expose the current admin user."""
from dataclasses import dataclass

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
