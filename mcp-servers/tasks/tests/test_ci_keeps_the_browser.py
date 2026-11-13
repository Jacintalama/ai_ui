"""CI must not download the browser on every run.

Measured from the workflow's own comment and from two real mornings: the
fragile step in this pipeline was `playwright install --with-deps
chromium`, because `--with-deps` runs apt against Ubuntu's mirrors. On
2026-11-11 security.ubuntu.com was unresolvable from the runner for
twenty minutes, twice in a row, and every deploy behind it was blocked,
other people's as well. Every package it could not fetch was a FONT.

So the browser is cached, keyed on the playwright version pip actually
resolved, and the install step is skipped on a hit. A key built from
requirements.txt would be wrong: it says `playwright>=1.40.0`, so the
resolved version and its browser build id both move while the file does
not, and the cache would serve a browser the installed playwright cannot
use.

These are the three statements that make that true. They are asserted
rather than the step's name, because a cache step that caches the wrong
path, or an install step that runs anyway, costs the same twenty minutes
while looking right.
"""
import yaml

from repo_checkout import repo_root_or_skip

ROOT = repo_root_or_skip()
WORKFLOWS = ROOT / ".github" / "workflows"


def _browser_jobs():
    """(workflow, job name, steps) for every job that installs chromium."""
    out = []
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        for name, job in (doc.get("jobs") or {}).items():
            steps = job.get("steps") or []
            if any("playwright install" in str(s.get("run") or "")
                   for s in steps):
                out.append((wf.name, name, steps))
    return out


def test_some_job_installs_a_browser():
    """Without this the rest of the file passes vacuously the day somebody
    renames the step."""
    assert _browser_jobs(), "no workflow installs chromium any more"


def test_every_job_that_installs_a_browser_caches_it():
    missing = []
    for wf, job, steps in _browser_jobs():
        cached = [s for s in steps
                  if str(s.get("uses") or "").startswith("actions/cache")
                  and "ms-playwright" in str((s.get("with") or {}).get("path"))]
        if not cached:
            missing.append(wf + ":" + job)
    assert missing == [], (
        "these download the browser on every run: " + ", ".join(missing))


def test_the_install_is_skipped_when_the_cache_hit():
    """A cache that is restored and then overwritten by a fresh install
    saves nothing, and leaves apt in the path on every run."""
    ungated = []
    for wf, job, steps in _browser_jobs():
        for s in steps:
            if "playwright install" in str(s.get("run") or ""):
                if "cache-hit" not in str(s.get("if") or ""):
                    ungated.append(wf + ":" + job)
    assert ungated == [], (
        "the install runs even on a cache hit in: " + ", ".join(ungated))


def test_the_cache_key_follows_the_installed_playwright_not_the_file():
    """requirements.txt pins a FLOOR (`playwright>=1.40.0`). Keying on that
    file would serve the browser of whatever version was resolved the first
    time, to every later version."""
    for wf, job, steps in _browser_jobs():
        key = ""
        for s in steps:
            if str(s.get("uses") or "").startswith("actions/cache"):
                key = str((s.get("with") or {}).get("key") or "")
        assert key, (wf, job)
        assert "requirements" not in key, (wf, job, key)
        assert "steps." in key and "outputs." in key, (
            "the key must come from a step that read the resolved version: "
            + wf + ":" + job + " -> " + key)


def _version_step(steps):
    for s in steps:
        if s.get("id") == "pw":
            return s
    return None


def test_the_version_step_exists_and_can_be_referenced():
    for wf, job, steps in _browser_jobs():
        step = _version_step(steps)
        assert step is not None, (
            wf + ":" + job + " has no step that reads the resolved version")
        assert step.get("run"), (wf, job)


def test_the_version_step_actually_prints_a_version():
    """RUN IT, rather than read it.

    The first version of this test asserted that some step mentioned
    `playwright.__version__` and that the cache key mentioned
    `steps.`/`outputs.`. Both were true and both passed, while the step
    produced NOTHING: the playwright package has no `__version__`
    attribute, so `python -c` failed, the `$( )` was empty, `echo`
    succeeded, and the key was "ms-playwright-Linux-" with no version in
    it. Three runs in the logs of 2026-11-13 say "Cache not found for
    input keys: ms-playwright-Linux-".

    That is the exact mistake this file was written to prevent, made by
    the file itself, so the check is now the script's own behaviour: run
    what the workflow runs, with GITHUB_OUTPUT pointed at a temp file,
    and read what it wrote.
    """
    import os
    import shutil
    import subprocess
    import tempfile

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash to run the step's script with")

    for wf, job, steps in _browser_jobs():
        script = _version_step(steps)["run"]
        with tempfile.TemporaryDirectory() as tmp:
            out_file = os.path.join(tmp, "out")
            open(out_file, "w").close()
            env = dict(os.environ, GITHUB_OUTPUT=out_file)
            r = subprocess.run([bash, "-e", "-c", script], env=env,
                               capture_output=True, text=True)
            wrote = open(out_file, encoding="utf-8").read().strip()
        assert r.returncode == 0, (wf, job, r.stdout, r.stderr)
        assert wrote.startswith("v="), (wf, job, wrote)
        version = wrote.split("=", 1)[1].strip()
        assert version, (
            wf + ":" + job + " wrote an EMPTY version, so every playwright "
            "release would share one cache key")
        assert version[0].isdigit(), (wf, job, version)


def test_an_unreadable_version_fails_the_step_rather_than_keying_on_nothing():
    """The guard that makes the above impossible to break silently again.
    Without it a failing lookup leaves an empty key and a green step."""
    for wf, job, steps in _browser_jobs():
        script = _version_step(steps)["run"]
        assert "test -n" in script or "[ -n" in script, (
            wf + ":" + job + " writes the version without checking it is "
            "not empty")
