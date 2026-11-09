"""The deploy pipeline stopped deploying, and the sweep was right to stop it.

2026-11-06 through 2026-11-09. Nothing deployed automatically for three
days. Eight Deploy runs, six failures and two cancelled, no success. The
last one died here:

    ==> [2b] server-edit sweep
    ERROR: these files were changed on the server since the last deploy;
           deploying would overwrite that work:
        mcp-servers/tasks/agent_approvals.py

That sweep exists for a good reason and it must stay: teammates edit files
directly on the box, and a repo-wins rsync over their work silently
reverts it. It compares the server's copy against the version the LAST
deploy sent, and anything different is treated as somebody's edit.

But it cannot tell those apart from a file I deployed BY HAND. When a
deploy fails, I ship the merged file myself, so the box ends up holding the
repo's newer version while `.deploy-state` still names the old commit. The
sweep sees a difference and refuses, so one failed deploy blocks every
later one until a person intervenes. A hash sweep over all 1208 watched
files on 2026-11-09 found exactly 3 differing, every one of them the repo
being AHEAD of the box, and no teammate edit anywhere.

The discriminator is what the deploy intends to WRITE. If the server
already holds exactly the version at the current commit, the rsync is a
no-op for that file: you cannot destroy somebody's work by writing bytes
that are already there. That is safe without weakening anything, because a
teammate's own edit does not coincidentally equal the repo's new version.

Second half: mcp-proxy/ was never in the watch list at all. It is a
top-level directory, so nothing in it has ever deployed itself, and PRs
#139, #142, #149 and #150 all shipped by hand. Its image was three days
old when I found it. Hand-shipping is what created the state above, so the
two halves are one bug.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deploy_orchestrator.sh"


def _src() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _sweep() -> str:
    """Just the sweep, so a match in an unrelated block cannot pass."""
    src = _src()
    start = src.index("[2b] server-edit sweep")
    end = src.index("[3/6] map paths to services")
    return src[start:end]


def test_the_script_is_where_this_thinks_it_is():
    assert SCRIPT.is_file(), SCRIPT


# --- the protection must stay -------------------------------------------

def test_the_sweep_still_compares_against_the_last_deployed_version():
    """The whole point of the sweep. If this goes, a teammate's work on the
    box is silently reverted by the next deploy."""
    sweep = _sweep()
    assert 'git show "${PREVIOUS_SHA}:${path}"' in sweep
    assert "EDITED_ON_SERVER" in sweep
    assert "exit 3" in sweep


def test_the_override_is_still_the_way_to_force_it():
    assert "ORCH_OVERWRITE_SERVER_EDITS" in _sweep()


# --- the new rule -------------------------------------------------------

def test_the_sweep_knows_what_it_is_about_to_write():
    """It must compute the CURRENT commit's version, not only the previous
    one. Without this it has no way to recognise a hand-deploy."""
    sweep = _sweep()
    assert 'git show "${CURRENT_SHA}:${path}"' in sweep, (
        "the sweep never looks at the version it is about to deploy, so it "
        "cannot tell a hand-deploy from somebody's edit on the box")


def test_a_file_already_at_the_new_version_is_skipped():
    """And skipped BEFORE it is flagged, or the refusal still happens."""
    sweep = _sweep()
    flag = sweep.index("EDITED_ON_SERVER+=")
    before = sweep[:flag]
    assert "CURRENT_SHA" in before, (
        "the current-version check must come before the file is flagged")
    assert re.search(r"continue\b", before), "nothing skips the file"


def test_the_skip_is_an_equality_with_the_server_copy():
    """Specifically: server content == what we are about to write. Any
    looser condition (a date, a name, a count) would skip real edits."""
    sweep = _sweep()
    assert re.search(r'"\$\{have\}"\s*==\s*"\$\{want_now\}"', sweep), (
        "the skip is not an equality between the server copy and the "
        "version being deployed")


# --- mcp-proxy joins the watch list -------------------------------------

def test_mcp_proxy_is_watched():
    """It is a top-level directory, so it never deployed itself."""
    line = [l for l in _src().splitlines() if "ORCH_PATH_PATTERN=" in l]
    assert line, "the watch pattern moved; re-read this test"
    assert "mcp-proxy/" in line[0], (
        "mcp-proxy still ships by hand:\n  " + line[0].strip())


def test_mcp_proxy_maps_to_its_service():
    src = _src()
    assert re.search(r"mcp-proxy/\*\)\s*SERVICES\[mcp-proxy\]=1", src), (
        "mcp-proxy files would rsync but rebuild nothing")


def test_the_pattern_still_watches_everything_it_did():
    """A regex edit that drops an existing path would stop deploying a
    service without anyone noticing."""
    line = [l for l in _src().splitlines() if "ORCH_PATH_PATTERN=" in l][0]
    for was in ("mcp-servers/", "api-gateway/", "Caddyfile",
                "docker-compose", "scripts/"):
        assert was in line, "the pattern stopped watching " + was


def test_templates_py_is_still_never_sent():
    """The server's copy is ahead and deploying ours drops templates."""
    assert "templates\.py" in _src()
