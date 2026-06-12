"""Layer-2 integration: synthetic signed Discord interaction → webhook-handler
→ TasksClient call. Test keypair, not Discord's live public key.

CRITICAL: discord_commands.py dispatches via asyncio.create_task(...) and
returns DEFERRED immediately. To assert the background task ran AND ran
against respx mocks, the test MUST:
  1. Use httpx.AsyncClient + ASGITransport (one event loop owned by the test),
     not fastapi.testclient.TestClient (which spins a sync thread + its own
     loop that exits when the response returns).
  2. Hold the respx.mock context open AND await a short sleep INSIDE that
     context, so the create_task fires before the mocks are torn down.
  3. Stub the Ed25519 public key + DISCORD_USER_EMAIL_MAP BEFORE the
     webhook-handler app is imported (env-stub-before-import pattern,
     same as mcp-servers/tasks/tests).

Lifespan note:
  httpx.ASGITransport does not trigger FastAPI's lifespan events.  Rather than
  running the full lifespan (which brings up APScheduler, voice_bot, etc.) we
  directly wire a DiscordCommandHandler into main.discord_command_handler after
  import.  This isolates the test to the webhook route + Ed25519 verification +
  fire-and-forget dispatch — the three things this Layer-2 test is meant to
  cover.

Import-isolation note:
  conftest.py runs before this module and seeds the settings singleton with
  DISCORD_PUBLIC_KEY="00"*32.  We patch settings.discord_public_key to our
  test keypair inside the test function body (before the route handler reads it)
  and restore it in the finally block.
"""
import asyncio
import json
import os
import sys
import types

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response
from nacl.signing import SigningKey


# ---------------------------------------------------------------------------
# Stub optional hard deps BEFORE sys.path modification.
# voice_bot imports audioop (removed in Py3.13) and discord (not installed
# locally).  apscheduler is also not installed locally.
# We register stubs in sys.modules so that `from main import app` works.
# ---------------------------------------------------------------------------
_stub_voice_bot = types.ModuleType("voice_bot")


async def _noop_start_voice_bot(*args, **kwargs):
    return None


_stub_voice_bot.start_voice_bot = _noop_start_voice_bot
_stub_voice_bot.current_text_channel_id = lambda: None
sys.modules.setdefault("voice_bot", _stub_voice_bot)

# Stub audioop and discord so transitive imports don't fail.
for _mod in ("audioop", "discord", "discord.ext", "discord.ext.voice_recv"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

# Stub apscheduler hierarchy (not installed in dev env).
for _mod in (
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
    "apscheduler.triggers",
    "apscheduler.triggers.cron",
):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))


class _FakeScheduler:
    def __init__(self):
        self.running = False

    def add_job(self, *args, **kwargs):
        pass

    def start(self):
        self.running = True

    def shutdown(self, *args, **kwargs):
        pass


class _FakeCronTrigger:
    def __init__(self, *args, **kwargs):
        pass


sys.modules["apscheduler.schedulers.asyncio"].AsyncIOScheduler = _FakeScheduler  # type: ignore[attr-defined]
sys.modules["apscheduler.triggers.cron"].CronTrigger = _FakeCronTrigger  # type: ignore[attr-defined]

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Set env defaults for first-import case (standalone run).
os.environ.setdefault("TASKS_URL", "http://tasks-test:8210")


@pytest.mark.asyncio
async def test_signed_cronjob_list_reaches_tasks():
    """End-to-end: signed interaction → DEFERRED ACK → TasksClient.list_schedules."""
    import main as main_mod
    from config import settings
    from clients.discord import DiscordClient
    from clients.tasks import TasksClient
    from clients.openwebui import OpenWebUIClient
    from clients.n8n import N8NClient
    from handlers.commands import CommandRouter
    from handlers.discord_commands import DiscordCommandHandler

    # Generate a fresh test keypair.
    sk = SigningKey.generate()
    test_public_key_hex = sk.verify_key.encode().hex()

    # Patch settings.discord_public_key so verify_discord_signature uses our key.
    original_public_key = settings.discord_public_key
    settings.discord_public_key = test_public_key_hex  # type: ignore[attr-defined]

    # Build a minimal CommandRouter with our test email map and a TasksClient
    # pointed at the respx-intercepted URL.
    test_email_map = {"100": "e2e-test@local"}
    tasks_client = TasksClient(base_url=settings.tasks_url)
    router = CommandRouter(
        openwebui_client=OpenWebUIClient(base_url="http://noop", api_key=""),
        n8n_client=N8NClient(
            base_url="http://noop",
            api_key="",
            webhook_url="http://noop",
        ),
        discord_user_email_map=test_email_map,
        tasks_client=tasks_client,
    )

    # Wire a real DiscordCommandHandler directly into main — bypassing the
    # lifespan (which httpx.ASGITransport does not trigger).
    discord_client = DiscordClient(application_id="test-app", bot_token="test-token")
    handler = DiscordCommandHandler(
        discord_client=discord_client,
        command_router=router,
    )
    original_handler = main_mod.discord_command_handler
    main_mod.discord_command_handler = handler

    try:
        # Build the signed interaction payload.
        payload = {
            "type": 2,  # APPLICATION_COMMAND
            "id": "intx-1",
            "token": "intx-token",
            "data": {
                "name": "aiui",
                "options": [{
                    "name": "cronjob",
                    "type": 1,
                    "options": [{"name": "args", "type": 3, "value": "list"}],
                }],
            },
            "member": {"user": {"id": "100", "username": "tester"}},
            "channel_id": "c1",
            "guild_id": "g1",
        }
        body = json.dumps(payload).encode()
        timestamp = "1234567890"
        sig = sk.sign(timestamp.encode() + body).signature.hex()

        transport = ASGITransport(app=main_mod.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with respx.mock(base_url=settings.tasks_url, assert_all_called=False) as mock:
                list_route = mock.get("/schedules").mock(return_value=Response(200, json=[]))

                r = await client.post(
                    "/webhook/discord",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Signature-Ed25519": sig,
                        "X-Signature-Timestamp": timestamp,
                    },
                )

                # DEFERRED ack returns immediately.
                assert r.status_code == 200, r.text
                assert r.json()["type"] == 5

                # The dispatcher runs via asyncio.create_task. Yield repeatedly
                # so the background task runs on this same event loop before
                # respx is torn down.
                for _ in range(20):
                    await asyncio.sleep(0.01)
                    if list_route.called:
                        break

                assert list_route.called, "TasksClient.list_schedules must have been called"
                req = list_route.calls.last.request
                assert req.headers.get("x-user-email") == "e2e-test@local"
                assert "x-cron-secret" not in {k.lower() for k in req.headers}

    finally:
        # Restore globals to avoid leaking state into other tests.
        main_mod.discord_command_handler = original_handler
        settings.discord_public_key = original_public_key  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_signed_aiuibuilder_build_reaches_start_build():
    import main as main_mod
    from config import settings
    from clients.discord import DiscordClient, DISCORD_API_BASE
    from clients.tasks import TasksClient
    from clients.openwebui import OpenWebUIClient
    from clients.n8n import N8NClient
    from handlers.commands import CommandRouter
    from handlers.discord_commands import DiscordCommandHandler

    sk = SigningKey.generate()
    original_public_key = settings.discord_public_key
    settings.discord_public_key = sk.verify_key.encode().hex()

    tasks_client = TasksClient(base_url=settings.tasks_url)
    router = CommandRouter(
        openwebui_client=OpenWebUIClient(base_url="http://noop", api_key=""),
        n8n_client=N8NClient(base_url="http://noop", api_key="", webhook_url="http://noop"),
        discord_user_email_map={"100": "e2e-test@local"},
        tasks_client=tasks_client,
    )
    discord_client = DiscordClient(application_id="test-app", bot_token="test-token")
    handler = DiscordCommandHandler(discord_client=discord_client, command_router=router)
    original_handler = main_mod.discord_command_handler
    main_mod.discord_command_handler = handler

    try:
        payload = {
            "type": 2, "id": "intx-2", "token": "intx-token-2",
            "data": {"name": "aiui", "options": [{
                "name": "aiuibuilder", "type": 1,
                "options": [{"name": "args", "type": 3, "value": 'build "a todo app"'}],
            }]},
            "member": {"user": {"id": "100", "username": "tester"}},
            "channel_id": "c1", "guild_id": "g1",
        }
        body = json.dumps(payload).encode()
        timestamp = "1234567890"
        sig = sk.sign(timestamp.encode() + body).signature.hex()

        transport = ASGITransport(app=main_mod.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with respx.mock(assert_all_called=False) as mock:
                mock.get(f"{settings.tasks_url}/api/aiuibuilder/templates").mock(
                    return_value=Response(200, json=[]))
                build_route = mock.post(
                    f"{settings.tasks_url}/api/aiuibuilder/build"
                ).mock(return_value=Response(201, json={
                    "task_id": "t1", "slug": "a-todo-app-a1b2", "status": "running"}))
                mock.get(
                    f"{settings.tasks_url}/api/aiuibuilder/build/t1"
                ).mock(return_value=Response(200, json={
                    "status": "completed", "slug": "a-todo-app-a1b2",
                    "preview_url": "https://x/p/", "error": None}))
                mock.post(f"{DISCORD_API_BASE}/channels/c1/messages").mock(
                    return_value=Response(200, json={"id": "m1"}))
                mock.patch(
                    f"{DISCORD_API_BASE}/webhooks/test-app/intx-token-2/messages/@original"
                ).mock(return_value=Response(200, json={}))

                r = await client.post(
                    "/webhook/discord", content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Signature-Ed25519": sig,
                        "X-Signature-Timestamp": timestamp,
                    },
                )
                assert r.status_code == 200, r.text
                assert r.json()["type"] == 5

                for _ in range(30):
                    await asyncio.sleep(0.01)
                    if build_route.called:
                        break
                assert build_route.called, "start_build must be called"
                req = build_route.calls.last.request
                assert req.headers.get("x-user-email") == "e2e-test@local"
                assert "x-cron-secret" not in {k.lower() for k in req.headers}
    finally:
        main_mod.discord_command_handler = original_handler
        settings.discord_public_key = original_public_key
        # Cancel any still-pending _watch_build task so pytest doesn't warn
        # "task was destroyed but it is pending" (its first poll sleeps 12s).
        for t in [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]:
            t.cancel()
