"""Per-user limits on schedule creation.

Each schedule spawns a Claude Code agent run (scheduler.py dispatches through
the remote executor), and concurrency is capped at 3 purely to avoid OOM on a
3.8GB box. Before this, create_schedule validated only that the cron expression
parsed — so `* * * * *`, an agent run every minute forever, was accepted. That
was survivable while the page was admin-only; opening it to everyone makes a cap
necessary rather than nice to have.

The helper is pure and uses a FIXED base time so the result is deterministic and
does not depend on when the suite runs.
"""
import os
import sys

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope/nope")
if not os.environ.get("AIUI_FERNET_KEY"):
    from cryptography.fernet import Fernet as _Fernet
    os.environ["AIUI_FERNET_KEY"] = _Fernet.generate_key().decode()
os.environ.setdefault("CRON_SHARED_SECRET", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from routes_schedules import min_interval_minutes  # noqa: E402


@pytest.mark.parametrize("expr,expected", [
    ("* * * * *", 1),        # every minute — the pathological case
    ("*/5 * * * *", 5),      # a step, not the literal every-minute
    ("*/15 * * * *", 15),    # exactly the boundary
    ("0,30 * * * *", 30),    # comma list
    ("0 * * * *", 60),       # hourly
    ("0 9 * * *", 1440),     # daily
])
def test_min_interval_is_the_smallest_gap(expr, expected):
    assert min_interval_minutes(expr) == expected


def test_uneven_schedules_report_their_SMALLEST_gap():
    """Mon and Tue at 09:00: gaps are 1 day, 6 days, 1 day. The smallest is
    what matters — an average would hide a burst."""
    assert min_interval_minutes("0 9 * * 1,2") == 1440


def test_a_garbage_expression_does_not_raise():
    """The caller validates with croniter.is_valid first, but this must never
    be the thing that 500s a request."""
    assert min_interval_minutes("not a cron") == 0.0
