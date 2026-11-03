"""A workflow has to be able to run the script it names.

The Deploy workflow failed 15 times. Fourteen were a missing secret. The
fifteenth, once the secret was set, was this:

    ./scripts/deploy_orchestrator.sh: Permission denied
    Process completed with exit code 126

Every shell script in this repository is stored mode 100644, because the
people who write them work on Windows, where git records no executable
bit. So `./script` cannot run on a Linux runner, and the job dies before
it reaches anything of its own.

Making one script the exception would work until somebody re-added it from
Windows and the mode quietly went back. Invoking through `bash` does not
care, so that is the rule, and this is the test that keeps it.
"""
import re

from repo_checkout import repo_root_or_skip

ROOT = repo_root_or_skip()
WORKFLOWS = ROOT / ".github" / "workflows"


def _runs():
    """(workflow, command) for every `run:` line that invokes a repo script."""
    out = []
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        for line in wf.read_text(encoding="utf-8").splitlines():
            if re.search(r"\bscripts/[\w./-]+\.sh\b", line) and "run:" in line:
                out.append((wf.name, line.split("run:", 1)[1].strip()))
    return out


def test_at_least_one_workflow_runs_a_script():
    """If this fails the search above has stopped matching anything, and
    every other test in this file passes vacuously."""
    assert _runs(), "no workflow step runs a repo script any more"


def test_no_workflow_invokes_a_script_directly():
    """`./scripts/x.sh` is Permission denied on the runner. `bash
    scripts/x.sh` is not.

    The test is on the FIRST token, not on the text appearing anywhere:
    `bash ./scripts/x.sh` contains "./scripts/x.sh" and is exactly the
    thing we want. The first version of this test flagged the fix.
    """
    bad = [(wf, cmd) for wf, cmd in _runs()
           if re.match(r"\./scripts/[\w./-]+\.sh", cmd.strip())]
    assert bad == [], (
        "these run a script directly, and every script here is mode 100644, "
        "so the runner answers Permission denied: "
        + "; ".join("%s: %s" % (w, c) for w, c in bad))


def test_the_deploy_workflow_still_runs_the_orchestrator():
    """The fix must not have removed the thing it was fixing."""
    text = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    assert re.search(r"run:\s*bash\s+\./?scripts/deploy_orchestrator\.sh", text)
