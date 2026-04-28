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
    storage: str  # "none" | "supabase" — UI hint for the new-project modal.
    role_tag: str = ""
    feature_bullets: list[str] = []
    has_app: bool = False  # True iff a base app exists; gallery only shows these.
    svg_mockup: str = ""  # inline SVG preview rendered in the gallery card.


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(user: AdminUser = Depends(current_admin)) -> list[TemplateOut]:
    from templates import _has_template_app
    return [
        TemplateOut(
            key=t.key,
            label=t.label,
            emoji=t.emoji,
            description=t.description,
            placeholder=t.placeholder,
            storage=t.storage,
            role_tag=t.role_tag,
            feature_bullets=list(t.feature_bullets),
            has_app=_has_template_app(t.key),
            svg_mockup=t.svg_mockup,
        )
        for t in TEMPLATES
    ]
