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


def test_completed_discord_is_output_only():
    """A successful run shows ONLY the output — no prompt echo, no when footer."""
    out = _format_schedule_result(
        "every day at 9:41 PM: give me the best quote",
        "completed",
        "Be yourself.",
        platform="discord",
    )
    assert out == "Be yourself."
    assert "give me the best quote" not in out
    assert "9:41 PM" not in out
    assert "✅" not in out


def test_completed_slack_is_output_only():
    out = _format_schedule_result(
        "give me the best quote", "completed", "Be yourself.", platform="slack"
    )
    assert out == "Be yourself."
    assert "give me the best quote" not in out


def test_completed_empty_output_shows_placeholder():
    out = _format_schedule_result("x", "completed", "", platform="slack")
    assert out == "_(no output)_"


def test_failed_keeps_name_and_warning():
    """A failed run still names the schedule so you know what broke."""
    out = _format_schedule_result(
        "give me the best quote", "failed", "boom", platform="slack"
    )
    assert out.startswith("⚠️")
    assert "**give me the best quote**" in out
    assert "boom" in out


def test_failed_discord_strips_when_prefix_from_title():
    out = _format_schedule_result(
        "every day at 9:41 PM: give me the best quote", "failed", "boom",
        platform="discord",
    )
    assert "**give me the best quote**" in out
    assert "9:41 PM" not in out  # the "<when>: " prefix is stripped off the title


def test_huge_result_truncated_to_1990():
    out = _format_schedule_result(
        "x: do thing", "completed", "y" * 5000, platform="discord"
    )
    assert len(out) <= 1990
