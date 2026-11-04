"""A deploy that lies about its outcome is worse than one that fails.

2026-11-03, the first deploys this pipeline ever ran for real. One of them
built the image, recreated the container, and then smoke-tested
/tasks/healthz immediately:

    ==> [6/6] post-deploy smoke
    curl: (22) The requested URL returned error: 502

The service was still starting. It answered 200 moments later, and the code
was live. But the run was marked failed and .deploy-state was left stale,
so the NEXT deploy computed its changed paths from the wrong commit.

Checked against the script rather than by running a deploy, because running
one costs a production restart. The live proof is the next green run.
"""
import re

import pytest

from repo_checkout import repo_root_or_skip

ROOT = repo_root_or_skip()
SCRIPT = ROOT / "scripts" / "deploy_orchestrator.sh"


def _smoke():
    """The smoke section only, from its heading to the decision after it."""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("[6/6] post-deploy smoke")
    end = text.index("SMOKE_FAIL}\" -eq 1", start)
    return text[start:end]


def test_the_smoke_retries_rather_than_asking_once():
    """One curl at a just-restarted service is a 502 and a false failure."""
    smoke = _smoke()
    assert re.search(r"for attempt in \$\(seq 1 \"\$\{SMOKE_TRIES\}\"\)", smoke), (
        "the health check is not in a retry loop")
    assert "sleep" in smoke


def test_it_waits_long_enough_to_be_worth_waiting():
    """A couple of seconds would reproduce the same false failure."""
    text = SCRIPT.read_text(encoding="utf-8")
    tries = int(re.search(r'SMOKE_TRIES="\$\{SMOKE_TRIES:-(\d+)\}"', text).group(1))
    wait = int(re.search(r'SMOKE_WAIT="\$\{SMOKE_WAIT:-(\d+)\}"', text).group(1))
    assert tries * wait >= 30, "a restarted container is given under 30s"


def test_it_still_gives_up(monkeypatch):
    """Waiting for ever would hang the pipeline on a genuinely broken
    deploy, which is the other way to make the result meaningless."""
    text = SCRIPT.read_text(encoding="utf-8")
    tries = int(re.search(r'SMOKE_TRIES="\$\{SMOKE_TRIES:-(\d+)\}"', text).group(1))
    wait = int(re.search(r'SMOKE_WAIT="\$\{SMOKE_WAIT:-(\d+)\}"', text).group(1))
    assert tries * wait <= 300, "a broken deploy holds the runner too long"


def test_a_failure_still_fails():
    """The point is to stop FALSE failures, not to stop failing."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "SMOKE_FAIL=1" in _smoke()
    assert "DEPLOY SMOKE FAILED" in text
    assert "exit 2" in text


def test_the_state_is_only_recorded_after_a_passing_smoke():
    """The whole safety property of this script. .deploy-state is what the
    next deploy diffs against, so stamping it on a failure would make the
    next one skip the files this one did not land."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.index("exit 2") < text.index("recording .deploy-state")


def test_the_script_parses():
    """It is bash, so nothing else in this suite would notice a typo."""
    import shutil
    import subprocess
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash here")
    out = subprocess.run([bash, "-n", str(SCRIPT)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# --- the bind-mounted file (2026-11-04) -----------------------------------

def test_rsync_writes_through_the_existing_inode():
    """mcp-servers/gdrive/integrations-ui.js is bind-mounted into
    open-webui as a SINGLE FILE. rsync's default is write-temp-then-rename,
    which gives the path a new inode; a single-file mount follows the
    inode, so the container goes on serving the old file and the page
    silently stays on yesterday's code.

    That is why that file had always been placed by hand, and why every
    change to it sat outside this pipeline. --inplace is what lets the
    pipeline own it.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    line = re.search(r"^rsync .*$", text, re.M)
    assert line, "the rsync call moved; re-point this test"
    assert "--inplace" in line.group(0), (
        "rsync will rename over the bind-mounted file and break the mount")


def test_the_bind_mounted_file_is_still_inside_a_watched_path():
    """If it ever leaves mcp-servers/, --inplace protects nothing and the
    file goes back to needing a hand."""
    text = (ROOT / "docker-compose.unified.yml").read_text(encoding="utf-8")
    assert "./mcp-servers/gdrive/integrations-ui.js:" in text
