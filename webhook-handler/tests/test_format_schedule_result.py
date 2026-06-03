"""Tests for _format_schedule_result — clean & quiet result message."""
import sys
import types

# voice_bot imports audioop (removed in Py3.13) and discord (not installed
# locally); apscheduler is also absent. Stub before importing main.
_stub_voice_bot = types.ModuleType("voice_bot")


async def _noop_start_voice_bot(*args, **kwargs):
    return None


_stub_voice_bot.start_voice_bot = _noop_start_voice_bot
sys.modules.setdefault("voice_bot", _stub_voice_bot)
for _mod in (
    "audioop",
    "discord",
    "discord.ext",
    "discord.ext.voice_recv",
    "apscheduler",
    "apscheduler.schedulers",
    "apscheduler.schedulers.asyncio",
    "apscheduler.triggers",
    "apscheduler.triggers.cron",
):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))


class _FakeScheduler:  # minimal apscheduler stand-ins
    def __init__(self, *a, **k):
        self.running = False

    def add_job(self, *a, **k):
        return None

    def start(self, *a, **k):
        self.running = True


class _FakeCronTrigger:
    def __init__(self, *a, **k):
        pass

    @classmethod
    def from_crontab(cls, *a, **k):
        return cls()


sys.modules["apscheduler.schedulers.asyncio"].AsyncIOScheduler = _FakeScheduler  # type: ignore[attr-defined]
sys.modules["apscheduler.triggers.cron"].CronTrigger = _FakeCronTrigger  # type: ignore[attr-defined]

from main import _format_schedule_result  # noqa: E402


def test_discord_style_completed_has_title_and_when_no_emoji():
    out = _format_schedule_result(
        "every day at 9:41 PM: give me the best quote", "completed", "Be yourself."
    )
    assert "**give me the best quote**" in out
    assert "_every day at 9:41 PM_" in out
    assert "✅" not in out


def test_slack_style_completed_has_title_no_footer_no_emoji():
    out = _format_schedule_result("give me the best quote", "completed", "Be yourself.")
    assert "**give me the best quote**" in out
    assert "_" not in out  # no italic footer line at all
    assert "✅" not in out


def test_failed_status_starts_with_warning():
    out = _format_schedule_result("give me the best quote", "failed", "boom")
    assert out.startswith("⚠️")


def test_huge_result_truncated_to_1990():
    out = _format_schedule_result("x: do thing", "completed", "y" * 5000)
    assert len(out) <= 1990
