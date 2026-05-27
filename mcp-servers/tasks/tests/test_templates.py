"""Tests for the server-side template catalog (Phase D).

The canonical build rules used to live in projects.html as JS dicts,
which the browser could rewrite (prompt-injection vector). They now live
in templates.py and are looked up server-side. These tests pin the shape
of that catalog and the secrecy of the rules field over the wire.
"""
from httpx import ASGITransport, AsyncClient

from main import app
from templates import TEMPLATES, build_rules_for, get_template

ADMIN_HEADERS = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}

EXPECTED_KEYS = {
    "landing", "dashboard", "crud", "crm", "portfolio", "docs",
    "ecommerce", "booking", "chat", "auth", "blog", "blank",
    "invoice", "project-tracker", "ai-chatbot", "expense-tracker",
    "form-builder", "social-feed", "custom",
    # Design-forward templates (2026-05-08):
    "agency", "restaurant", "photography", "event", "real-estate",
    # Functional templates (2026-05-11):
    "flight-booking", "food-delivery", "job-board", "movie-tickets", "recipe-site",
}

# The synthetic 'custom' key is the escape hatch — it intentionally has no
# template-specific rules block (the agent runs on _BASE_RULES +
# _GENERATION_LAYOUT alone). Skip it for rules/section checks.
_RULES_EXEMPT = {"custom"}

REQUIRED_SECTIONS = ("PURPOSE", "TECH", "MUST INCLUDE", "LAYOUT")


def test_rules_exempt_set_is_minimal():
    """The _RULES_EXEMPT set lets templates skip per-template content checks
    (PURPOSE/TECH/MUST INCLUDE/LAYOUT). It exists ONLY for synthetic keys
    whose `rules=""` is intentional. If you're adding a key here, document
    the WHY in the module-level comment above _RULES_EXEMPT — and update
    this assertion."""
    from tests.test_templates import _RULES_EXEMPT
    assert _RULES_EXEMPT == {"custom"}, (
        "Adding a key to _RULES_EXEMPT requires explicit review. See the "
        "comment above the constant for guidance."
    )


def test_29_templates_present():
    assert len(TEMPLATES) == 29
    assert {t.key for t in TEMPLATES} == EXPECTED_KEYS


def test_keys_unique():
    keys = [t.key for t in TEMPLATES]
    assert len(keys) == len(set(keys))


def test_each_template_has_rules():
    for t in TEMPLATES:
        if t.key in _RULES_EXEMPT:
            continue
        body = t.rules.strip()
        assert body, f"{t.key} has empty rules"
        assert len(body) > 200, f"{t.key} rules suspiciously short ({len(body)} chars)"


def test_each_template_has_required_sections():
    for t in TEMPLATES:
        if t.key in _RULES_EXEMPT:
            continue
        for section in REQUIRED_SECTIONS:
            assert section in t.rules, f"{t.key} missing section {section!r}"


def test_each_template_has_required_metadata():
    for t in TEMPLATES:
        assert t.label, f"{t.key} missing label"
        assert t.emoji, f"{t.key} missing emoji"
        assert t.description, f"{t.key} missing description"
        assert t.placeholder, f"{t.key} missing placeholder"


def test_get_template_returns_object():
    t = get_template("crud")
    assert t is not None
    assert t.key == "crud"


def test_get_template_unknown_returns_none():
    assert get_template("does-not-exist") is None


def test_build_rules_for_returns_universal_plus_template():
    out = build_rules_for("crud")
    assert "RULES (strict):" in out
    assert "PURPOSE: Manage one main entity" in out
    assert len(out) > 500


def test_build_rules_for_unknown_key():
    assert build_rules_for("nope") == ""


def test_build_rules_for_with_supabase_storage_appends_block():
    out = build_rules_for("crud", "supabase")
    assert "Supabase project will be attached" in out


def test_build_rules_for_with_none_storage_appends_block():
    out = build_rules_for("crud", "none")
    assert "NO persistence" in out


async def test_get_endpoint_excludes_rules_field():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/templates", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 29
    expected_fields = {
        "key", "label", "emoji", "description", "placeholder",
        "storage", "role_tag", "feature_bullets", "has_app", "svg_mockup",
    }
    for item in items:
        assert set(item.keys()) == expected_fields, (
            f"unexpected fields on {item.get('key')}: {set(item.keys())}"
        )
        assert "rules" not in item


async def test_get_endpoint_requires_admin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/templates")
    assert r.status_code in (401, 403)
