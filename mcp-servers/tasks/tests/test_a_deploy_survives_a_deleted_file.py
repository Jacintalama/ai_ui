"""A deploy must not die because the repo deleted a file.

2026-11-06. Three deploys in a row failed and the merges never reached the
server, while I kept telling Ralph a thing was live because the PR was
merged. The last one:

    rsync: [sender] link_stat ".../tests/browser/test_tasks_launcher.py"
           failed: No such file or directory (2)
    rsync error: some files/attrs were not transferred (code 23)

The orchestrator builds its file list with `git diff --name-only`, which
lists DELETED paths alongside changed ones, and then hands the whole list
to rsync as things to send. Deleting any watched file therefore breaks
every deploy until someone notices, and nothing about the failure says so:
it reads as an rsync problem.

Two rules here:

  * the copy list contains only files that exist at the current commit
  * a deletion is still REPORTED, because the file stays on the server and
    a stale module nobody mentioned is how a container keeps running code
    that is no longer in the repo
"""
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deploy_orchestrator.sh"


def _src():
    return SCRIPT.read_text(encoding="utf-8")


def test_the_script_is_where_this_thinks_it_is():
    assert SCRIPT.is_file(), SCRIPT


def test_the_copy_list_excludes_deleted_paths():
    """--diff-filter=d drops deletions. Without it rsync is asked for a
    file that is not there and exits 23."""
    src = _src()
    line = [l for l in src.splitlines()
            if "git diff --name-only" in l and "PREVIOUS_SHA" in l]
    assert line, "the changed-file line moved; re-read this test"
    assert any("--diff-filter=d" in l for l in line), (
        "deleted files are still in the list rsync is given:\n  "
        + "\n  ".join(l.strip() for l in line))


def test_a_deletion_is_still_named():
    """Excluding it from the copy is right; saying nothing is not. The
    file stays on the server."""
    src = _src()
    assert "--diff-filter=D" in src, (
        "nothing computes the deleted paths, so a deletion is invisible")
    assert "DELETED" in src


def test_git_really_behaves_the_way_this_assumes(tmp_path):
    """The whole fix rests on what --diff-filter does. Proven against a
    real repo rather than trusted, because getting the letter wrong
    (d excludes, D selects) silently inverts it.
    """
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path,
                              capture_output=True, text=True, check=True).stdout

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (tmp_path / "kept.txt").write_text("a", encoding="utf-8")
    (tmp_path / "gone.txt").write_text("b", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "one")
    first = git("rev-parse", "HEAD").strip()

    (tmp_path / "kept.txt").write_text("changed", encoding="utf-8")
    (tmp_path / "gone.txt").unlink()
    (tmp_path / "new.txt").write_text("c", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "two")
    second = git("rev-parse", "HEAD").strip()

    plain = set(git("diff", "--name-only", first + ".." + second).split())
    assert plain == {"kept.txt", "gone.txt", "new.txt"}, plain

    to_copy = set(git("diff", "--name-only", "--diff-filter=d",
                      first + ".." + second).split())
    assert to_copy == {"kept.txt", "new.txt"}, (
        "lowercase d must EXCLUDE deletions: %s" % to_copy)

    deleted = set(git("diff", "--name-only", "--diff-filter=D",
                      first + ".." + second).split())
    assert deleted == {"gone.txt"}, (
        "uppercase D must SELECT deletions: %s" % deleted)


def test_every_file_in_the_copy_list_can_be_opened():
    """The failure in plain terms: the list is what rsync is handed, so
    anything in it must exist. Run against the real repo and the real
    last-deployed state is not possible here, so this asserts the shape
    the script now guarantees."""
    src = _src()
    build = src[src.index("ORCH_PATH_PATTERN="):src.index("if [[ -z \"${CHANGED}\"")]
    assert "--diff-filter=d" in build
    assert re.search(r"CHANGED=\$\(git diff --name-only --diff-filter=d", build), (
        "the copy list is not the filtered one")
