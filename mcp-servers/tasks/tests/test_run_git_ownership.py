"""_run_git keeps working when the work tree's owner is not the caller.

On prod the work tree is a bind mount (/root/proxy-server ->
/workspace/ai_ui). A tar made on Windows and unpacked as root set its top
directory to uid 197609, and from then on every git command in the
container answered "detected dubious ownership". The commit sweep fails
open, so app version history and rollback died silently from 2026-08-20
until 2026-09-30.

Needs a real chown, so it runs only as root on POSIX (the tasks container),
and is skipped on a dev machine.
"""
import os
import subprocess

import pytest

import routes_projects as rp

pytestmark = pytest.mark.skipif(
    os.name != "posix" or os.geteuid() != 0,
    reason="needs root on POSIX to chown the work tree",
)


async def test_run_git_works_in_a_tree_owned_by_another_uid(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    os.chown(tmp_path, 197609, 197121)

    rc, out = await rp._run_git("status", "--porcelain", cwd=str(tmp_path))

    assert rc == 0, out
