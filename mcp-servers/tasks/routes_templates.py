"""GET /api/templates — returns the template catalog for the frontend dropdown.

Public-ish: any authenticated admin can see the catalog (it's not secret).
The `rules` field is intentionally omitted from the response — those only
travel agent-side to close a prompt-injection vector.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import AdminUser, current_admin
from templates import TEMPLATES

router = APIRouter(prefix="/api")


class TemplateOut(BaseModel):
    key: str
    label: str
    emoji: str
    description: str
    placeholder: str


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(user: AdminUser = Depends(current_admin)) -> list[TemplateOut]:
    return [
        TemplateOut(
            key=t.key,
            label=t.label,
            emoji=t.emoji,
            description=t.description,
            placeholder=t.placeholder,
        )
        for t in TEMPLATES
    ]
