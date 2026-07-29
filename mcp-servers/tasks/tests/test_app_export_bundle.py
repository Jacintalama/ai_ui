"""The bundle is a WORKING repo that RUNS standalone. The subtle bug this
guards: Supabase URL + anon key are injected at request time in prod and are
NOT in the app files, so a naive export ships a broken app."""
import subprocess
import zipfile
from pathlib import Path

import app_export
from app_export import ExportError, export_app


def _mk_app(root, slug, extra=None):
    d = root / slug
    d.mkdir(parents=True)
    (d / "index.html").write_text("<html><head></head><body>hi</body></html>",
                                  encoding="utf-8")
    for rel, text in (extra or {}).items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


def _no_history_git(monkeypatch):
    """Force the fresh-repo fallback: monorepo reports zero commits."""
    real = app_export._run_git

    async def fake(*args, **kw):
        if "log" in args:
            return 0, ""
        return await real(*args, **kw)
    monkeypatch.setattr(app_export, "_run_git", fake)


def _zip_names(zpath):
    with zipfile.ZipFile(zpath) as z:
        return set(z.namelist())


def _zip_bytes(zpath):
    with zipfile.ZipFile(zpath) as z:
        return b"".join(z.read(n) for n in z.namelist())


async def test_fresh_fallback_produces_working_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "shop")
    _no_history_git(monkeypatch)

    zpath, filename = await export_app("shop", actor_email="a@b.com",
                                       supabase_row=None)
    names = _zip_names(zpath)
    assert filename == "shop-export-fresh.zip"
    assert any(n.startswith(".git/") for n in names), "must include .git"
    assert "index.html" in names and "README.md" in names
    # and it is a REAL repo: git log works in the unzipped tree
    out = tmp_path / "unzipped"
    with zipfile.ZipFile(zpath) as z:
        z.extractall(out)
    log = subprocess.run(["git", "log", "--oneline"], cwd=out,
                         capture_output=True, text=True)
    assert log.returncode == 0 and "Exported from IO" in log.stdout


async def test_readme_carries_no_history_note_and_guide(tmp_path, monkeypatch):
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "shop")
    _no_history_git(monkeypatch)
    zpath, _ = await export_app("shop", actor_email="a@b.com", supabase_row=None)
    with zipfile.ZipFile(zpath) as z:
        readme = z.read("README.md").decode()
    assert "history was not available" in readme.lower()
    assert "Where this app can run" in readme


async def test_linked_supabase_bundle_runs_out_of_the_box(tmp_path, monkeypatch):
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "crm", {"app.js": "supabase.createClient(window.SUPABASE_URL)"})
    _no_history_git(monkeypatch)
    row = app_export.SupabaseInfo(url="https://ref.supabase.co", anon_key="anon-123",
                                  schema_runner=None)
    zpath, _ = await export_app("crm", actor_email="a@b.com", supabase_row=row)
    with zipfile.ZipFile(zpath) as z:
        cfg = z.read("aiui-config.js").decode()
        idx = z.read("index.html").decode()
    assert "https://ref.supabase.co" in cfg and "anon-123" in cfg
    assert '<script src="./aiui-config.js"></script>' in idx


async def test_unlinked_supabase_app_gets_example_config(tmp_path, monkeypatch):
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "crm", {"app.js": "window.SUPABASE_URL"})
    _no_history_git(monkeypatch)
    zpath, _ = await export_app("crm", actor_email="a@b.com", supabase_row=None)
    names = _zip_names(zpath)
    assert "aiui-config.example.js" in names and "aiui-config.js" not in names


async def test_artifacts_and_secrets_never_in_the_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "shop", {
        ".attachments/leak.txt": "attachment",
        ".video/clip.mp4": "fake-mp4",
    })
    _no_history_git(monkeypatch)
    row = app_export.SupabaseInfo(url="https://ref.supabase.co", anon_key="anon-123",
                                  schema_runner=None,
                                  never_export=("postgresql://user:dbpass@host/db",
                                                "service-role-secret", "oauth-tok"))
    zpath, _ = await export_app("shop", actor_email="a@b.com", supabase_row=row)
    names = _zip_names(zpath)
    assert not any(".attachments" in n or ".video" in n for n in names)
    blob = _zip_bytes(zpath)
    for secret in (b"dbpass", b"service-role-secret", b"oauth-tok"):
        assert secret not in blob, f"secret {secret!r} leaked into the bundle"


async def test_monorepo_tree_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    app = _mk_app(tmp_path, "shop")
    before = sorted(p.relative_to(app) for p in app.rglob("*"))
    _no_history_git(monkeypatch)
    await export_app("shop", actor_email="a@b.com", supabase_row=None)
    assert sorted(p.relative_to(app) for p in app.rglob("*")) == before


async def test_missing_app_raises_export_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    try:
        await export_app("ghost", actor_email="a@b.com", supabase_row=None)
        assert False, "should have raised"
    except ExportError as e:
        assert "no such app" in str(e).lower()


async def test_subtree_path_uses_split_and_clone(tmp_path, monkeypatch):
    """History exists: assert the git choreography without real subtree."""
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "shop")
    calls = []

    async def fake(*args, cwd=None, **kw):
        calls.append(list(args))
        if "log" in args:
            return 0, "abc123 built\n"
        if "subtree" in args:
            return 0, "deadbeefcafe\n"
        if "clone" in args:
            dest = Path(args[-1])
            (dest / ".git").mkdir(parents=True)
            (dest / "index.html").write_text("<html><head></head></html>",
                                             encoding="utf-8")
            return 0, ""
        if "rev-parse" in args:
            return 0, "deadbee\n"
        return 0, ""
    monkeypatch.setattr(app_export, "_run_git", fake)

    _, filename = await export_app("shop", actor_email="a@b.com", supabase_row=None)
    flat = ["\x00".join(c) for c in calls]
    assert any("subtree" in f and "--prefix=apps/shop" in f for f in flat)
    assert any(f.startswith("clone") or "\x00clone\x00" in "\x00" + f + "\x00" for f in flat)
    assert any("branch" in c and "-D" in c for c in calls), "temp branch cleaned up"
    assert filename == "shop-export-deadbee.zip"


async def test_split_failure_raises_and_leaves_no_tmp(tmp_path, monkeypatch):
    """A failed export must surface ExportError AND clean up its temp dir."""
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "shop")

    async def fake(*args, cwd=None, **kw):
        if "log" in args:
            return 0, "abc123 built\n"
        if "subtree" in args:
            return 1, "fatal: subtree exploded"
        return 0, ""
    monkeypatch.setattr(app_export, "_run_git", fake)

    import glob
    import os
    import tempfile as _tf
    before = set(glob.glob(os.path.join(_tf.gettempdir(), "ioexport-*")))
    try:
        await export_app("shop", actor_email="a@b.com", supabase_row=None)
        assert False, "should raise"
    except ExportError as e:
        assert "history extraction failed" in str(e)
    after = set(glob.glob(os.path.join(_tf.gettempdir(), "ioexport-*")))
    assert after == before, "failed export must not leak its temp dir"


async def test_stale_temp_branch_is_deleted_before_split(tmp_path, monkeypatch):
    """A crashed prior export can leave export-tmp-<slug> behind; the next
    export must delete it BEFORE splitting so it can never wedge the slug."""
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "shop")
    calls = []

    async def fake(*args, cwd=None, **kw):
        calls.append(list(args))
        if "log" in args:
            return 0, "abc123 x\n"
        if "subtree" in args:
            return 0, "deadbeefcafe\n"
        if "clone" in args:
            dest = Path(args[-1])
            (dest / ".git").mkdir(parents=True)
            (dest / "index.html").write_text("<html><head></head></html>",
                                             encoding="utf-8")
            return 0, ""
        if "rev-parse" in args:
            return 0, "deadbee\n"
        return 0, ""
    monkeypatch.setattr(app_export, "_run_git", fake)

    await export_app("shop", actor_email="a@b.com", supabase_row=None)
    split_i = next(i for i, c in enumerate(calls) if "subtree" in c)
    pre = [i for i, c in enumerate(calls)
           if "branch" in c and "-D" in c and i < split_i]
    assert pre, "stale export-tmp branch must be deleted before split"


# --- the bundle must not carry the monorepo's upstream history --------------
# Measured on prod 2026-07-29: exporting `icecreamery` produced a 295 MB zip
# for a 28 KB app. `git clone --branch <b> file://<monorepo>` copies EVERY tag
# and everything each tag reaches. This repo is a fork of Open WebUI, so 119
# upstream `v0.1.x` tags anchored a 280.6 MB pack file. The app itself was
# index.html plus a few small JS/CSS files.
#
# Not a data leak - no other user's app is reachable and the only .env paths
# are .env.example templates, both re-verified on prod. It is a size bug: a
# 10,000x download, built and zipped on a 3.8 GB box.

def _record_clone_git(monkeypatch, calls):
    """History path, capturing the clone argv."""
    async def fake(*args, **kw):
        calls.append(list(args))
        if "log" in args:
            return 0, "abc123\n"          # pretend the app has history
        if "clone" in args:
            return 1, "stopped by test"   # abort right after we captured it
        return 0, ""
    monkeypatch.setattr(app_export, "_run_git", fake)


async def _clone_argv(tmp_path, monkeypatch):
    monkeypatch.setattr(app_export, "_APPS_ROOT", tmp_path)
    _mk_app(tmp_path, "sizeapp")
    calls = []
    _record_clone_git(monkeypatch, calls)
    try:
        await export_app("sizeapp", actor_email="a@b.com", supabase_row=None)
    except ExportError:
        pass
    return next((c for c in calls if "clone" in c), None)


async def test_export_clone_takes_only_the_export_branch(tmp_path, monkeypatch):
    argv = await _clone_argv(tmp_path, monkeypatch)
    assert argv is not None, "expected a clone on the history path"
    assert "--single-branch" in argv, (
        "without --single-branch the clone drags in every branch of the monorepo"
    )


async def test_export_clone_carries_no_tags(tmp_path, monkeypatch):
    argv = await _clone_argv(tmp_path, monkeypatch)
    assert argv is not None
    assert "--no-tags" in argv, (
        "119 upstream Open WebUI tags anchored a 280MB pack in the bundle"
    )
