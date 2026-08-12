"""The sidebar nav config must expose all five features to regular users.

task-panel.js is browser JS with no JS test harness in this repo, so this
parses the config out of the source. That is weaker than running it — it
cannot prove the entries actually appear — but it does pin the five flags
against a silent edit, which is the failure this file exists to catch.
"""
import pathlib
import re

JS = (pathlib.Path(__file__).resolve().parents[1]
      / "static" / "task-panel.js").read_text(encoding="utf-8")

EXPECTED = {"App Builder", "Video Generation", "Cron Jobs", "Graph", "Chat Apps"}


def _entries():
    """[(label, has_allUsers)] parsed from the NAV_ENTRIES literal."""
    block = JS.split("const NAV_ENTRIES = [", 1)[1]
    out = []
    for chunk in block.split("attr:")[1:]:
        m = re.search(r'label:\s*"([^"]+)"', chunk)
        if m:
            out.append((m.group(1), "allUsers: true" in chunk))
    return out


def test_all_five_entries_exist():
    assert {label for label, _ in _entries()} >= EXPECTED


def test_every_entry_is_visible_to_regular_users():
    hidden = [label for label, all_users in _entries()
              if label in EXPECTED and not all_users]
    assert not hidden, f"still admin-only: {hidden}"


def test_the_injector_does_not_depend_only_on_the_workspace_link():
    """The root cause. Open WebUI renders a[href="/workspace"] only for admins
    or users holding >=1 workspace permission (upstream Sidebar.svelte,
    isMenuItemVisible), and this deployment sets all five to false. With a
    single anchor, non-admins got NO entries at all — even the three already
    flagged allUsers."""
    anchors = re.findall(r'a\[href="(/[a-z-]+)"\]', JS)
    assert "/workspace" in anchors, "admins must still anchor under Workspace"
    fallbacks = [a for a in anchors if a != "/workspace"]
    assert fallbacks, "no fallback anchor — non-admins would still see nothing"


def test_the_fallback_targets_something_non_admins_can_see():
    """features.notes and features.calendar are true for regular users in this
    deployment; workspace.* are all false."""
    anchors = set(re.findall(r'a\[href="(/[a-z-]+)"\]', JS))
    assert anchors & {"/notes", "/calendar"}
