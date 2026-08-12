"""The few slash commands the gateway understands.

Kept deliberately small. Everything a person actually wants to do is a sentence
to the model; commands exist only for things the model cannot do to itself,
which right now is exactly one thing: point this conversation at a different
transcript.
"""
import logging

from gateway.events import SessionSource

log = logging.getLogger(__name__)

KNOWN = ("/resume", "/help", "/start")


def is_command(text: str) -> bool:
    return (text or "").strip().startswith("/")


async def handle(text: str, tasks, source: SessionSource,
                 owui_user_id: str) -> str | None:
    """Run a command and return its reply, or None if `text` is not a command."""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None

    parts = raw.split()
    verb = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if verb in ("/help", "/start"):
        return _help()
    if verb == "/resume":
        return await _resume(tasks, source, owui_user_id, arg)
    return f"I don't know {verb}. Try /help."


def _help() -> str:
    return (
        "Just talk to me and I'll answer with your own IO account: your memory, "
        "your tools, your models.\n\n"
        "/resume  see your recent conversations and pick one up here\n"
        "/help    this message"
    )


async def _resume(tasks, source: SessionSource, owui_user_id: str,
                  arg: str) -> str:
    sessions = await tasks.gateway_recent_sessions(owui_user_id, limit=10)
    if not sessions:
        return "You have nothing to resume yet. Send me a message and we'll start one."

    if not arg:
        return _listing(sessions)

    if not arg.isdigit():
        return f"Pick a number.\n\n{_listing(sessions)}"
    pick = int(arg)
    if not 1 <= pick <= len(sessions):
        return f"There's no {pick}.\n\n{_listing(sessions)}"

    chosen = sessions[pick - 1]
    await tasks.gateway_put_session(
        source.platform, source.chat_id, chosen["owui_chat_id"], owui_user_id)
    return (
        f"Picked up your {chosen.get('platform', 'previous')} conversation. "
        "Carry on from where you left off."
    )


def _listing(sessions: list[dict]) -> str:
    lines = ["Your recent conversations. Reply /resume <number> to continue one:"]
    for i, s in enumerate(sessions, start=1):
        when = (s.get("updated_at") or "")[:10]
        lines.append(f"{i}. {s.get('platform', 'unknown')}  {when}")
    return "\n".join(lines)
