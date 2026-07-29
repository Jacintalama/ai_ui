"""The suite must behave the same whether you run one file or all of them.

CLAUDE.md documents `python -m pytest tests/test_app_smoke.py -q` as a normal
workflow, but several files could only be collected as part of a full run:

  crypto_utils.py raises at IMPORT time when AIUI_FERNET_KEY is unset, and
  routes_projects imports it (added by the export feature, b627b88be). Any test
  that transitively imports routes_projects therefore needed the key just to be
  COLLECTED. Eight files carried their own `os.environ.setdefault(...)`
  boilerplate; in a full run the alphabetically-first of those set the key and
  every later file passed BY ACCIDENT. Alone, they failed.

conftest.py already solves this for DATABASE_URL ("Ensure tests that don't touch
the DB can be collected without DATABASE_URL set"). This pins the same property
for the fernet key so it cannot regress silently again.

This is the third environment-dependent test bug in this repo, after the
container-vs-laptop port assumption in test_app_smoke. Run one file, get the
same answer.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TASKS_DIR = Path(__file__).resolve().parents[1]

# Representative files that import routes_projects transitively and carry no
# fernet boilerplate of their own.
STANDALONE_FILES = [
    "tests/test_app_regression.py",
    "tests/test_app_export_bundle.py",
]


@pytest.mark.parametrize("test_file", STANDALONE_FILES)
def test_file_can_be_collected_on_its_own(test_file):
    """Collect ONE file in a clean environment, the way a developer would."""
    env = {k: v for k, v in os.environ.items() if k != "AIUI_FERNET_KEY"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=TASKS_DIR, env=env, capture_output=True, text=True, timeout=180,
    )
    combined = proc.stdout + proc.stderr
    assert "AIUI_FERNET_KEY is not set" not in combined, (
        f"{test_file} cannot be collected standalone; conftest must provide a "
        f"default so single-file runs work"
    )
    assert proc.returncode == 0, (
        f"{test_file} failed to collect standalone:\n{combined[-800:]}"
    )
