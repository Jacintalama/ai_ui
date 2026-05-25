import pytest
from handlers.commands import CommandRouter, CommandContext
from clients.tasks import TasksAPIError


class FakeTasks:
    def __init__(self, status=None, error=None):
        self._status = status or {}
        self._error = error
    async def get_project_status(self, email, slug):
        if self._error:
            raise self._error
        return {"slug": slug, **self._status}


def _router(tasks, email_map=None):
    return CommandRouter(
        None, None,
        discord_user_email_map={"u1": "a@b.com"} if email_map is None else email_map,
        tasks_client=tasks,
    )


def _ctx():
    sent = {"text": [], "comp": []}
    async def respond(msg): sent["text"].append(msg)
    async def respond_components(msg, components): sent["comp"].append((msg, components))
    ctx = CommandContext(
        user_id="u1", user_name="ralph", channel_id="c1", raw_text="", subcommand="aiuibuilder",
        arguments="", platform="discord", respond=respond, respond_components=respond_components,
    )
    return ctx, sent


async def test_run_panel_menu_published_uses_respond_components():
    tasks = FakeTasks(status={"name": "Shop", "role": "owner", "published": True,
                              "public_url": "https://shop.live"})
    ctx, sent = _ctx()
    await _router(tasks).run_panel_menu(ctx, "shop")
    assert len(sent["comp"]) == 1
    header, components = sent["comp"][0]
    assert "Shop" in header and "published" in header
    labels = [c.get("label") for c in components[0]["components"]]
    assert any("Unpublish" in l for l in labels)


async def test_run_panel_menu_not_linked():
    ctx, sent = _ctx()
    await _router(FakeTasks(), email_map={}).run_panel_menu(ctx, "shop")
    assert sent["comp"] == []
    assert any("isn't linked" in m for m in sent["text"])


async def test_run_panel_menu_404():
    tasks = FakeTasks(error=TasksAPIError(404, "nope"))
    ctx, sent = _ctx()
    await _router(tasks).run_panel_menu(ctx, "shop")
    assert any("not found" in m.lower() for m in sent["text"])
    assert sent["comp"] == []


async def test_run_panel_status_text():
    tasks = FakeTasks(status={"name": "Shop", "role": "owner", "published": False})
    ctx, sent = _ctx()
    await _router(tasks).run_panel_status(ctx, "shop")
    joined = "\n".join(sent["text"])
    assert "Shop" in joined and "Role: owner" in joined and "Published: no" in joined


async def test_run_panel_status_minimal_no_crash():
    # API returns only a name (no role/published) — must not KeyError.
    tasks = FakeTasks(status={"name": "Shop"})
    ctx, sent = _ctx()
    await _router(tasks).run_panel_status(ctx, "shop")
    joined = "\n".join(sent["text"])
    assert "Shop" in joined and "Role: ?" in joined and "Published: no" in joined


class FakeTasksList(FakeTasks):
    def __init__(self, projects):
        super().__init__()
        self._projects = projects
    async def list_projects(self, email):
        return self._projects


async def test_list_attaches_dropdown_when_projects_exist():
    tasks = FakeTasksList([
        {"slug": "shop", "name": "Shop", "role": "owner", "public_url": "https://x"},
    ])
    ctx, sent = _ctx()
    ctx.arguments = "list"
    await _router(tasks)._handle_aiuibuilder(ctx)
    assert len(sent["comp"]) == 1
    reply, components = sent["comp"][0]
    assert "Your apps" in reply
    select = components[0]["components"][0]
    assert select["custom_id"] == "aiuibuild:appselect"


async def test_list_empty_no_dropdown():
    ctx, sent = _ctx()
    ctx.arguments = "list"
    await _router(FakeTasksList([]))._handle_aiuibuilder(ctx)
    assert sent["comp"] == []
    assert any("no projects yet" in m for m in sent["text"])
