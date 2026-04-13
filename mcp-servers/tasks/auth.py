"""Read the trusted gateway headers and expose the current admin user."""
from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class AdminUser:
    email: str
    is_admin: bool


def current_admin(request: Request) -> AdminUser:
    """FastAPI dependency. Returns the current admin or raises 401/403."""
    email = request.headers.get("x-user-email", "").strip()
    is_admin = request.headers.get("x-user-admin", "").strip().lower() == "true"
    if not email:
        raise HTTPException(status_code=401, detail="Missing X-User-Email")
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return AdminUser(email=email, is_admin=True)
