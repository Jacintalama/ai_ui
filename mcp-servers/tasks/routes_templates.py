"""GET /api/templates — returns the template catalog for the frontend dropdown.

Public-ish: any authenticated user can see the catalog (it's not secret).
The `rules` field is intentionally omitted from the response — those only
travel agent-side to close a prompt-injection vector.

The admin header used to be required as well, which left the App Builder's
"Select template" gallery empty for a regular user. It never protected
anything: the same catalog is already served to non-admins by
/api/aiuibuilder/templates, and the secret part (`rules`) is not in either
response.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import CurrentUser, current_user
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
async def list_templates(user: CurrentUser = Depends(current_user)) -> list[TemplateOut]:
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
