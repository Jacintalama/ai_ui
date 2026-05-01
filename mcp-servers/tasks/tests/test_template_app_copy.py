"""Tests for the "copy a pre-built reference app, then customize" pipeline.

When `template_apps/<key>/` exists on disk, BUILD tasks copy that folder
into `apps/<slug>/` (with placeholder substitution) and the BUILD prompt
switches from "generate from scratch" to "customize this base app". When
the folder is absent, the existing generation path runs unchanged.

These tests cover:
  • _has_template_app — disk lookup + per-key cache
  • _copy_template_app — recursive copy + placeholder substitution
  • _humanize_slug — kebab-case slug -> Title Case display name
  • create_task — end-to-end: a template-app-backed BUILD copies the
    reference app and substitutes the APP_NAME placeholder
  • build_rules_for — switches between CUSTOMIZE MODE and FILE LAYOUT
"""
from cryptography.fernet import Fernet as _Fernet
_AIUI_TEST_KEY = _Fernet.generate_key().decode()

import os

os.environ.setdefault("AIUI_FERNET_KEY", _AIUI_TEST_KEY)

from httpx import ASGITransport, AsyncClient

import templates as templates_mod
from main import app
from routes_tasks import _copy_template_app, _humanize_slug


ADMIN_HEADERS = {"X-User-Email": "ralph@aiui.com", "X-User-Admin": "true"}


# ---------------------------------------------------------------------------
# _humanize_slug
# ---------------------------------------------------------------------------

def test_humanize_slug():
    assert _humanize_slug("my-cool-app") == "My Cool App"
    assert _humanize_slug("invoice") == "Invoice"
    assert _humanize_slug("my_todo_list") == "My Todo List"
    assert _humanize_slug("") == ""


# ---------------------------------------------------------------------------
# _has_template_app
# ---------------------------------------------------------------------------

def test_has_template_app_detects_existing_dir(tmp_path, monkeypatch):
    """_has_template_app probes <module_dir>/template_apps/<key>/index.html.

    Monkeypatch __file__ on the templates module so the lookup root is
    inside tmp_path; verify both positive and negative cases.
    """
    # Reset cache so prior tests don't bleed in.
    templates_mod._TEMPLATE_APP_CACHE.clear()

    fake_module_path = tmp_path / "templates.py"
    fake_module_path.write_text("# fake")
    monkeypatch.setattr(templates_mod, "__file__", str(fake_module_path))

    foo_dir = tmp_path / "template_apps" / "foo"
    foo_dir.mkdir(parents=True)
    (foo_dir / "index.html").write_text("<!doctype html><title>x</title>")

    assert templates_mod._has_template_app("foo") is True
    assert templates_mod._has_template_app("does-not-exist") is False

    # Cache is per-key — clear after to avoid leaking into other tests.
    templates_mod._TEMPLATE_APP_CACHE.clear()


# ---------------------------------------------------------------------------
# _copy_template_app
# ---------------------------------------------------------------------------

def test_copy_template_app_substitutes_placeholders(tmp_path, monkeypatch):
    # Set up a fake source tree at <tmp>/template_apps/test/.
    here = tmp_path / "module"
    here.mkdir()
    fake_module_path = here / "routes_tasks.py"
    fake_module_path.write_text("# fake")

    # Patch __file__ on the module so _copy_template_app's `here` resolves
    # into tmp_path.
    import routes_tasks as rt
    monkeypatch.setattr(rt, "__file__", str(fake_module_path))

    src = here / "template_apps" / "test"
    (src / "src").mkdir(parents=True)
    (src / "index.html").write_text("<title><%= APP_NAME %></title>", encoding="utf-8")
    (src / "src" / "main.js").write_text(
        "// for <%= APP_SLUG %>\nconsole.log('<%= APP_NAME %>');",
        encoding="utf-8",
    )
    # Binary file should be copied verbatim — no placeholder substitution
    # even if the bytes happen to contain the placeholder marker.
    (src / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n<%= APP_NAME %>")
    # Ignored file shouldn't make it across.
    (src / ".DS_Store").write_bytes(b"junk")

    # Workspace = tmp/<workspace>; destination is <workspace>/apps/<slug>/.
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(workspace))

    _copy_template_app("test", "my-app", "My App")

    dst = workspace / "apps" / "my-app"
    assert (dst / "index.html").read_text(encoding="utf-8") == "<title>My App</title>"
    js_text = (dst / "src" / "main.js").read_text(encoding="utf-8")
    assert "// for my-app" in js_text
    assert "console.log('My App');" in js_text
    # Binary copied verbatim, placeholder bytes preserved.
    assert (dst / "logo.png").read_bytes() == b"\x89PNG\r\n\x1a\n<%= APP_NAME %>"
    # Ignored file skipped.
    assert not (dst / ".DS_Store").exists()
    # New apps must ignore .attachments/ in their git history.
    assert ".attachments/" in (dst / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_copy_template_app_falls_back_to_humanized_slug_when_name_blank(
    tmp_path, monkeypatch
):
    here = tmp_path / "module"
    here.mkdir()
    fake_module_path = here / "routes_tasks.py"
    fake_module_path.write_text("# fake")

    import routes_tasks as rt
    monkeypatch.setattr(rt, "__file__", str(fake_module_path))

    src = here / "template_apps" / "blank"
    src.mkdir(parents=True)
    (src / "index.html").write_text("<title><%= APP_NAME %></title>", encoding="utf-8")

    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(workspace))

    _copy_template_app("blank", "my-invoices", "")

    dst = workspace / "apps" / "my-invoices" / "index.html"
    assert dst.read_text(encoding="utf-8") == "<title>My Invoices</title>"


# ---------------------------------------------------------------------------
# build_rules_for switches modes
# ---------------------------------------------------------------------------

def test_build_rules_for_switches_to_customize_mode(monkeypatch):
    """When _has_template_app(key) is True, build_rules_for emits the
    CUSTOMIZE MODE directive and omits the FILE LAYOUT block. When False,
    it emits the generation FILE LAYOUT and not the CUSTOMIZE MODE block.
    """
    layout_marker = "FILE LAYOUT (MANDATORY — create the project folder first"

    # Force the lookup result rather than touching disk. _has_template_app
    # consults its own cache first, so seed that.
    templates_mod._TEMPLATE_APP_CACHE.clear()
    templates_mod._TEMPLATE_APP_CACHE["landing"] = True
    out_customize = templates_mod.build_rules_for("landing")
    assert "CUSTOMIZE MODE" in out_customize
    assert layout_marker not in out_customize

    templates_mod._TEMPLATE_APP_CACHE["landing"] = False
    out_generate = templates_mod.build_rules_for("landing")
    assert "CUSTOMIZE MODE" not in out_generate
    assert layout_marker in out_generate

    templates_mod._TEMPLATE_APP_CACHE.clear()


# ---------------------------------------------------------------------------
# Integration: POST /api/tasks copies the template app on disk
# ---------------------------------------------------------------------------

async def test_create_task_uses_template_app_when_present(
    db_session, tmp_path, monkeypatch
):
    """A BUILD task whose template_key has a base app on disk results in
    apps/<slug>/index.html existing post-create, with placeholders
    substituted (no `<%= APP_NAME %>` literal left over)."""
    # 1. Build a fake template_apps/landing/ tree.
    here = tmp_path / "module"
    here.mkdir()
    fake_module_path = here / "routes_tasks.py"
    fake_module_path.write_text("# fake")

    import routes_tasks as rt
    monkeypatch.setattr(rt, "__file__", str(fake_module_path))

    src = here / "template_apps" / "landing"
    (src / "src").mkdir(parents=True)
    (src / "index.html").write_text(
        "<!doctype html><title><%= APP_NAME %></title>", encoding="utf-8"
    )
    (src / "src" / "main.js").write_text("// <%= APP_SLUG %>", encoding="utf-8")

    # 2. Workspace points at tmp; force _has_template_app True for "landing".
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(workspace))
    templates_mod._TEMPLATE_APP_CACHE.clear()
    monkeypatch.setattr(rt, "_has_template_app", lambda k: k == "landing")

    # 3. POST a BUILD task.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks",
            headers=ADMIN_HEADERS,
            json={
                "description": "Landing page for a coffee shop.",
                "action_type": "BUILD",
                "priority": "IMPORTANT",
                "assignee": "self",
                "template_key": "landing",
                "storage": "none",
                "slug": "bean-there",
            },
        )
    assert r.status_code == 201, r.text

    # 4. apps/<slug>/ should now exist with substituted placeholders.
    dst_index = workspace / "apps" / "bean-there" / "index.html"
    assert dst_index.exists(), "template_apps content was not copied"
    text = dst_index.read_text(encoding="utf-8")
    assert "<%= APP_NAME %>" not in text
    # Default app_name = humanized slug.
    assert "Bean There" in text
    js_text = (workspace / "apps" / "bean-there" / "src" / "main.js").read_text(
        encoding="utf-8"
    )
    assert "<%= APP_SLUG %>" not in js_text
    assert "bean-there" in js_text

    templates_mod._TEMPLATE_APP_CACHE.clear()


async def test_create_task_falls_back_to_skeleton_when_no_template_app(
    db_session, tmp_path, monkeypatch
):
    """A template_key without a corresponding template_apps/<key>/ folder
    must still go through _ensure_app_skeleton (the legacy generate path).
    The 13 templates without a base app folder rely on this.
    """
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CLAUDE_WORKSPACE", str(workspace))
    templates_mod._TEMPLATE_APP_CACHE.clear()

    import routes_tasks as rt
    monkeypatch.setattr(rt, "_has_template_app", lambda k: False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/api/tasks",
            headers=ADMIN_HEADERS,
            json={
                "description": "Recipe manager.",
                "action_type": "BUILD",
                "priority": "IMPORTANT",
                "assignee": "self",
                "template_key": "crud",
                "storage": "none",
                "slug": "recipe-box",
            },
        )
    assert r.status_code == 201, r.text

    # _ensure_app_skeleton should have created the canonical empty layout
    # and a placeholder README — no index.html, since the agent writes
    # that during the build.
    base = workspace / "apps" / "recipe-box"
    assert (base / "README.md").exists()
    assert (base / "src" / "components").is_dir()
    assert not (base / "index.html").exists()
    # And a .gitignore that excludes attachment blobs from build commits.
    assert ".attachments/" in (base / ".gitignore").read_text(encoding="utf-8").splitlines()

    templates_mod._TEMPLATE_APP_CACHE.clear()