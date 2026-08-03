"""The export's own commit must be verified, not assumed.

`export_app` writes README.md, aiui-config.js and schema.sql into the bundle
repo and commits them. The `git add` return code was checked; the `git commit`
return code was thrown away. A failed commit therefore produced a zip that
still LOOKS like "your app with its full history" — the files are on disk — but
whose `git status` is dirty and whose filename carries the pre-export SHA.

Same failure class as the App Builder commit bug in CLAUDE.md: an action was
announced and never checked. This asserts the outcome (the tree is clean), not
merely the return code, because that is what the user actually cares about.
"""
import zipfile

import app_export
from app_export import export_app


def _mk_app(root, slug):
    d = root / slug
    d.mkdir(parents=True)
    (d / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    return d


def _fresh_repo_git(monkeypatch, *, fail_commit=False, calls=None):
    """Force the no-history fallback, optionally breaking the export commit."""
    real = app_export._run_git

    async def fake(*args, **kw):
        if calls is not None:
            calls.append(args)
        if "log" in args:
            return 0, ""  # monorepo reports zero commits -> fresh fallback
        # Break ONLY the export metadata commit. The fresh-repo fallback makes
        # its own initial commit, which already checks its return code and
        # raises ExportError — matching on "commit" alone would hit that one
        # instead and prove nothing about the bug under test.
        if fail_commit and "Export from IO: config, schema and README" in args:
            # The real failure mode seen in the wild: an unusable identity.
            return 128, "fatal: empty ident name not allowed"
        return await real(*args, **kw)

    monkeypatch.setattr(app_export, "_run_git", fake)


async def test_export_commit_return_code_is_checked(tmp_path, monkeypatch, caplog):
    """A failed commit must be reported, not discarded."""
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "shop")
    _fresh_repo_git(monkeypatch, fail_commit=True)

    with caplog.at_level("WARNING"):
        zpath, _ = await export_app("shop", actor_email="a@b.com", supabase_row=None)

    assert zpath.exists(), "a failed metadata commit must not lose the bundle"
    logged = " ".join(r.getMessage() for r in caplog.records).lower()
    assert "commit" in logged, (
        "the export commit failed and nothing said so; this is the exact "
        "silent-failure pattern the git-commit sweep exists to prevent"
    )
    assert "empty ident name" in logged, "log the real git output, not a guess"


async def test_successful_export_leaves_a_clean_tree(tmp_path, monkeypatch):
    """The positive case: after a good export the bundle has no uncommitted
    files, so `git status` in the user's download is clean."""
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "shop")
    _fresh_repo_git(monkeypatch)

    zpath, _ = await export_app("shop", actor_email="a@b.com", supabase_row=None)

    out = tmp_path / "unzipped"
    with zipfile.ZipFile(zpath) as z:
        z.extractall(out)
    rc, dirty = await app_export._run_git_default(
        "status", "--porcelain", cwd=str(out))
    assert rc == 0
    assert dirty.strip() == "", f"bundle ships uncommitted files: {dirty!r}"


async def test_readme_is_actually_committed_not_just_written(tmp_path, monkeypatch):
    """README.md existing on disk is not proof it is in the repo."""
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "shop")
    _fresh_repo_git(monkeypatch)

    zpath, _ = await export_app("shop", actor_email="a@b.com", supabase_row=None)

    out = tmp_path / "unzipped"
    with zipfile.ZipFile(zpath) as z:
        z.extractall(out)
    rc, tracked = await app_export._run_git_default(
        "ls-files", "README.md", cwd=str(out))
    assert rc == 0 and tracked.strip() == "README.md", (
        "README.md is in the zip but not tracked by git"
    )
