import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
import scheduler


class _S:  # minimal stand-in for a Schedule row
    def __init__(self, run_once):
        self.run_once = run_once


def test_fire_values_disables_run_once():
    now = datetime(2026, 6, 15, 1, 30, tzinfo=timezone.utc)
    v = scheduler.fire_values(_S(run_once=True), now)
    assert v["enabled"] is False
    assert v["last_run_at"] == now
    assert v["last_run_status"] == "running"


def test_fire_values_keeps_repeating_enabled():
    now = datetime(2026, 6, 15, 1, 30, tzinfo=timezone.utc)
    v = scheduler.fire_values(_S(run_once=False), now)
    assert "enabled" not in v  # repeating rows stay enabled
    assert v["last_run_at"] == now and v["last_run_status"] == "running"
