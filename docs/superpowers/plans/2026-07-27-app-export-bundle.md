# App Export Bundle + Deploy Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An owner can download their app as a working git repository (history, runnable config, schema, README with a per-platform deploy guide) from the gallery.

**Architecture:** One new module `app_export.py` (analyze → capability table → schema introspection → bundle build), two GET routes on the projects router, one button + modal in the gallery. Errors surface (user-initiated); only optional enrichments (history, schema) degrade to README notes. Spec: `docs/superpowers/specs/2026-07-27-app-export-bundle-design.md`.

**Tech Stack:** Python 3.11, FastAPI, pytest (`asyncio_mode=auto`, no decorators), git subtree (verified in the tasks container), `shutil.make_archive`, vanilla JS in `static/projects.html` (vendored marked + DOMPurify).

**House rules that bind every task:** TDD (watch each test fail first). Module-level seams for tests (`_run_git = _run_git_default` pattern). Never `git add -A` in the monorepo. Plain text UI labels, no emoji. CRLF-normalize anything scp'd to the server. Never touch `.env` or deploy local `templates.py`.

---

### Task 1: `analyze_app` — what is this app made of

**Files:**
- Create: `mcp-servers/tasks/app_export.py`
- Create: `mcp-servers/tasks/tests/test_app_export_analyze.py`

- [ ] **Step 1: Write the failing tests**

```python
"""What analyze_app must see: index presence, Supabase usage, chat-proxy usage.

The chat-proxy flag exists because exported apps CANNOT reach the platform's
LLM proxy; silently shipping a broken AI feature is the failure mode."""
import app_export
from app_export import AppProfile, analyze_app


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_missing_app_returns_none(tmp_path):
    assert analyze_app("nope", apps_root=tmp_path) is None


def test_plain_static_app(tmp_path):
    _write(tmp_path / "shop", "index.html", "<html><body>hi</body></html>")
    _write(tmp_path / "shop", "styles/main.css", "body{}")
    p = analyze_app("shop", apps_root=tmp_path)
    assert p == AppProfile(has_index=True, uses_supabase=False,
                           uses_chat_proxy=False, size_bytes=p.size_bytes,
                           file_count=2)
    assert p.size_bytes > 0


def test_supabase_markers_detected(tmp_path):
    _write(tmp_path / "crm", "index.html", "<html></html>")
    _write(tmp_path / "crm", "src/main.js",
           "const c = supabase.createClient(window.SUPABASE_URL, window.SUPABASE_ANON_KEY);")
    assert analyze_app("crm", apps_root=tmp_path).uses_supabase is True


def test_chat_proxy_detected(tmp_path):
    _write(tmp_path / "bot", "index.html", "<html></html>")
    _write(tmp_path / "bot", "app.js", "fetch('/api/chat-proxy', {method:'POST'})")
    assert analyze_app("bot", apps_root=tmp_path).uses_chat_proxy is True


def test_missing_index_is_flagged(tmp_path):
    _write(tmp_path / "raw", "readme.md", "no index here")
    assert analyze_app("raw", apps_root=tmp_path).has_index is False


def test_artifact_dirs_are_not_scanned(tmp_path):
    _write(tmp_path / "a", "index.html", "<html></html>")
    _write(tmp_path / "a", ".attachments/x.js", "window.SUPABASE_URL")
    _write(tmp_path / "a", ".video/y.js", "/api/chat-proxy")
    _write(tmp_path / "a", ".git/config", "[core]")
    p = analyze_app("a", apps_root=tmp_path)
    assert p.uses_supabase is False and p.uses_chat_proxy is False
    assert p.file_count == 1
```

- [ ] **Step 2: Run, verify they fail** — `cd mcp-servers/tasks && python -m pytest tests/test_app_export_analyze.py -q` → `ModuleNotFoundError: No module named 'app_export'`.

- [ ] **Step 3: Minimal implementation** (start of `app_export.py`)

```python
"""Take Your App With You: export bundle + deploy guide.

Spec: docs/superpowers/specs/2026-07-27-app-export-bundle-design.md
User-initiated, so errors SURFACE (unlike the fail-open build sweeps); only the
optional enrichments (history, schema) degrade to README notes."""
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_APPS_ROOT = Path(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")) / "apps"
_SKIP_DIRS = {".git", ".attachments", ".video", "node_modules"}
_TEXT_SUFFIXES = {".html", ".htm", ".js", ".css", ".json", ".md", ".txt"}
_SUPABASE_MARKERS = ("window.SUPABASE", "aiui-config", "createClient(")
_CHAT_PROXY_MARKER = "/api/chat-proxy"


@dataclass(frozen=True)
class AppProfile:
    has_index: bool
    uses_supabase: bool
    uses_chat_proxy: bool
    size_bytes: int
    file_count: int


def _app_files(app_dir: Path):
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            yield Path(root) / name


def analyze_app(slug: str, *, apps_root: Path | None = None) -> AppProfile | None:
    app_dir = (apps_root or _APPS_ROOT) / slug
    if not app_dir.is_dir():
        return None
    uses_supabase = uses_chat_proxy = False
    size = count = 0
    for f in _app_files(app_dir):
        count += 1
        try:
            size += f.stat().st_size
        except OSError:
            continue
        if f.suffix.lower() in _TEXT_SUFFIXES:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not uses_supabase and any(m in text for m in _SUPABASE_MARKERS):
                uses_supabase = True
            if not uses_chat_proxy and _CHAT_PROXY_MARKER in text:
                uses_chat_proxy = True
    return AppProfile(
        has_index=(app_dir / "index.html").is_file(),
        uses_supabase=uses_supabase,
        uses_chat_proxy=uses_chat_proxy,
        size_bytes=size,
        file_count=count,
    )
```

- [ ] **Step 4: Run, verify green** — same command → `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/app_export.py mcp-servers/tasks/tests/test_app_export_analyze.py
git commit -m "feat(export): analyze_app profiles an app (index, supabase, chat-proxy)"
```

---

### Task 2: `DEPLOY_TARGETS` + `build_deploy_guide` — the capability table

**Files:**
- Modify: `mcp-servers/tasks/app_export.py` (append)
- Create: `mcp-servers/tasks/tests/test_app_export_guide.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Lukas's 'AI knows what is possible where' as a data table. Today every
target supports every app (all static); the supports() seam is where real
constraints live when server-side app types exist."""
from app_export import DEPLOY_TARGETS, AppProfile, build_deploy_guide

STATIC = AppProfile(True, False, False, 10_000, 3)
SUPA = AppProfile(True, True, False, 10_000, 3)
AI = AppProfile(True, False, True, 10_000, 3)


def test_five_targets_exist():
    keys = {t.key for t in DEPLOY_TARGETS}
    assert keys == {"github-pages", "netlify", "vercel", "cloudflare-pages", "own-server"}


def test_every_target_supports_todays_static_apps():
    for t in DEPLOY_TARGETS:
        ok, _ = t.supports(STATIC)
        assert ok, f"{t.key} should support a static app"


def test_every_target_has_steps():
    for t in DEPLOY_TARGETS:
        assert len(t.steps) >= 2, f"{t.key} needs real steps"


def test_guide_lists_every_target():
    md = build_deploy_guide(STATIC)
    for t in DEPLOY_TARGETS:
        assert t.name in md


def test_guide_warns_about_chat_proxy_only_when_used():
    assert "chat-proxy" in build_deploy_guide(AI)
    assert "chat-proxy" not in build_deploy_guide(STATIC)


def test_guide_mentions_supabase_config_only_when_used():
    assert "aiui-config.js" in build_deploy_guide(SUPA)
    assert "aiui-config.js" not in build_deploy_guide(STATIC)
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest tests/test_app_export_guide.py -q` → ImportError on `DEPLOY_TARGETS`.

- [ ] **Step 3: Implementation** (append to `app_export.py`)

```python
@dataclass(frozen=True)
class DeployTarget:
    key: str
    name: str
    steps: tuple[str, ...]

    def supports(self, profile: AppProfile) -> tuple[bool, str]:
        # Every IO app today is static files, which every target below hosts.
        # When server-side app types exist, per-target constraints go here
        # (e.g. "Vercel cannot run Docker containers").
        return True, ""


DEPLOY_TARGETS: tuple[DeployTarget, ...] = (
    DeployTarget("github-pages", "GitHub Pages", (
        "Create a new repository on github.com and push this folder to it "
        "(`git remote add origin <url> && git push -u origin main`).",
        "In the repository: Settings, Pages, set Source to `main` branch, root folder.",
        "Your app appears at `https://<user>.github.io/<repo>/` in about a minute.",
    )),
    DeployTarget("netlify", "Netlify", (
        "Go to app.netlify.com and log in (free tier works).",
        "Drag this whole folder onto the Netlify Drop area, or connect the "
        "GitHub repository if you pushed one.",
        "Netlify gives you a live URL immediately; no build settings needed.",
    )),
    DeployTarget("vercel", "Vercel", (
        "Push this folder to a GitHub repository first.",
        "On vercel.com, choose Add New Project and import that repository.",
        "Framework preset: Other. No build command. Output directory: `./`.",
    )),
    DeployTarget("cloudflare-pages", "Cloudflare Pages", (
        "Push this folder to a GitHub repository first.",
        "In the Cloudflare dashboard: Workers & Pages, Create, Pages, "
        "connect the repository.",
        "No build command; leave the output directory as `/`.",
    )),
    DeployTarget("own-server", "Your own server (any static host)", (
        "Copy this folder to the server.",
        "Serve it with any web server, e.g. `python -m http.server 8000` to "
        "test, or point nginx/Caddy at the folder for real hosting.",
    )),
)


def build_deploy_guide(profile: AppProfile) -> str:
    lines = ["## Where this app can run", ""]
    warnings = []
    if profile.uses_chat_proxy:
        warnings.append(
            "- **AI features will not work after export.** This app calls the IO "
            "platform's `/api/chat-proxy`, which only exists on IO. Standalone, "
            "those requests fail; you would need your own backend and API key.")
    if profile.uses_supabase:
        warnings.append(
            "- This app uses Supabase. The bundle's `aiui-config.js` must contain "
            "your project URL and anon key (see the Database section below).")
    if warnings:
        lines += ["### Before you deploy", *warnings, ""]
    for t in DEPLOY_TARGETS:
        ok, reason = t.supports(profile)
        lines.append(f"### {t.name}")
        if not ok:
            lines += [f"Not supported for this app: {reason}", ""]
            continue
        lines += [f"{i}. {s}" for i, s in enumerate(t.steps, 1)]
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run, verify green** — `6 passed`, and re-run Task 1 file too: `python -m pytest tests/test_app_export_analyze.py tests/test_app_export_guide.py -q` → `12 passed`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/app_export.py mcp-servers/tasks/tests/test_app_export_guide.py
git commit -m "feat(export): deploy-target capability table + per-app guide"
```

---

### Task 3: `build_schema_sql` — schema dumped from the live database

**Files:**
- Modify: `mcp-servers/tasks/app_export.py` (append)
- Create: `mcp-servers/tasks/tests/test_app_export_schema.py`

The introspection takes a `run_sql(sql) -> list[dict]` callable so tests feed
canned rows and the route wires the real dual path (`routes_db`'s
`_exec_via_management_api` / `_exec_via_asyncpg`, which cover OAuth-linked
projects; there is no pg_dump in the image). RLS state is reported as fact.

- [ ] **Step 1: Write the failing tests**

```python
"""schema.sql must come from the LIVE database, never from the agent's claim.
RLS state is part of the dump, reported as fact (on AND off)."""
import app_export


def _runner(by_query):
    async def run_sql(sql: str):
        for key, rows in by_query.items():
            if key in sql:
                return rows
        return []
    return run_sql


CANNED = {
    "information_schema.columns": [
        {"table_name": "todos", "column_name": "id", "data_type": "bigint",
         "is_nullable": "NO", "column_default": None},
        {"table_name": "todos", "column_name": "title", "data_type": "text",
         "is_nullable": "YES", "column_default": "'untitled'::text"},
    ],
    "relrowsecurity": [
        {"relname": "todos", "relrowsecurity": True},
    ],
    "pg_policies": [
        {"tablename": "todos", "policyname": "allow_all_anon", "cmd": "ALL",
         "roles": ["anon"], "qual": "true", "with_check": "true"},
    ],
}


async def test_dump_contains_create_table_with_columns():
    sql = await app_export.build_schema_sql(_runner(CANNED))
    assert 'CREATE TABLE "todos"' in sql
    assert '"id" bigint NOT NULL' in sql
    assert '"title" text DEFAULT \'untitled\'::text' in sql


async def test_dump_reports_rls_enabled_with_policy():
    sql = await app_export.build_schema_sql(_runner(CANNED))
    assert 'ALTER TABLE "todos" ENABLE ROW LEVEL SECURITY;' in sql
    assert 'CREATE POLICY "allow_all_anon" ON "todos" FOR ALL TO anon USING (true) WITH CHECK (true);' in sql


async def test_dump_flags_rls_off_as_fact():
    canned = dict(CANNED)
    canned["relrowsecurity"] = [{"relname": "todos", "relrowsecurity": False}]
    canned["pg_policies"] = []
    sql = await app_export.build_schema_sql(_runner(canned))
    assert "RLS is NOT enabled" in sql
    assert "ENABLE ROW LEVEL SECURITY" not in sql.replace(
        "-- ALTER TABLE", "")  # only the suggestion comment, never a live stmt


async def test_empty_database_yields_honest_header():
    sql = await app_export.build_schema_sql(_runner({}))
    assert "no tables found" in sql.lower()
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest tests/test_app_export_schema.py -q` → AttributeError `build_schema_sql`.

- [ ] **Step 3: Implementation** (append to `app_export.py`)

```python
_Q_COLUMNS = (
    "SELECT table_name, column_name, data_type, is_nullable, column_default "
    "FROM information_schema.columns WHERE table_schema = 'public' "
    "ORDER BY table_name, ordinal_position"
)
_Q_RLS = (
    "SELECT c.relname, c.relrowsecurity FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind = 'r'"
)
_Q_POLICIES = (
    "SELECT tablename, policyname, cmd, roles, qual, with_check "
    "FROM pg_policies WHERE schemaname = 'public'"
)


async def build_schema_sql(run_sql) -> str:
    """Introspect the live DB into CREATE TABLE / RLS / POLICY statements.

    `run_sql(sql) -> list[dict]` is injected: the route wires routes_db's dual
    path (Management API for OAuth links, asyncpg for db_uri). One statement
    per call, matching that endpoint's contract. Truth over completeness:
    constraints and indexes beyond RLS are out of scope and the header says so.
    """
    cols = await run_sql(_Q_COLUMNS)
    header = (
        "-- schema.sql generated by IO export from the LIVE database.\n"
        "-- Columns, RLS state and policies are reported as fact.\n"
        "-- Constraints and indexes beyond RLS are not included.\n\n"
    )
    if not cols:
        return header + "-- no tables found in schema public\n"

    by_table: dict[str, list[dict]] = {}
    for c in cols:
        by_table.setdefault(c["table_name"], []).append(c)
    rls = {r["relname"]: bool(r["relrowsecurity"]) for r in await run_sql(_Q_RLS)}
    policies: dict[str, list[dict]] = {}
    for p in await run_sql(_Q_POLICIES):
        policies.setdefault(p["tablename"], []).append(p)

    out = [header]
    for table, tcols in by_table.items():
        defs = []
        for c in tcols:
            d = f'  "{c["column_name"]}" {c["data_type"]}'
            if c.get("column_default"):
                d += f' DEFAULT {c["column_default"]}'
            if c.get("is_nullable") == "NO":
                d += " NOT NULL"
            defs.append(d)
        out.append(f'CREATE TABLE "{table}" (\n' + ",\n".join(defs) + "\n);\n")
        if rls.get(table):
            out.append(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;\n')
            for p in policies.get(table, []):
                roles = ", ".join(p.get("roles") or ["public"])
                stmt = (f'CREATE POLICY "{p["policyname"]}" ON "{table}" '
                        f'FOR {p.get("cmd") or "ALL"} TO {roles}')
                if p.get("qual"):
                    stmt += f' USING ({p["qual"]})'
                if p.get("with_check"):
                    stmt += f' WITH CHECK ({p["with_check"]})'
                out.append(stmt + ";\n")
        else:
            out.append(
                f'-- WARNING: RLS is NOT enabled on "{table}". With the anon key '
                "public by design, this table is readable by anyone.\n"
                f'-- To fix: ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY; '
                "then add a policy.\n")
        out.append("\n")
    return "".join(out)
```

- [ ] **Step 4: Run, verify green** — `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/app_export.py mcp-servers/tasks/tests/test_app_export_schema.py
git commit -m "feat(export): schema.sql introspected from the live DB, RLS as fact"
```

---

### Task 4: `export_app` — build the bundle

**Files:**
- Modify: `mcp-servers/tasks/app_export.py` (append)
- Create: `mcp-servers/tasks/tests/test_app_export_bundle.py`

Unit strategy: the **fresh-repo fallback runs real git** in tmp dirs (plain
`init/add/commit`, works everywhere); the **subtree path is argv-asserted**
through the `_run_git` seam (subtree itself was verified in the container on
2026-07-16 and the e2e in Task 7 exercises it for real). Zip-content and
secrets assertions run against the actual bytes.

- [ ] **Step 1: Write the failing tests**

```python
"""The bundle is a WORKING repo that RUNS standalone. The subtle bug this
guards: Supabase URL + anon key are injected at request time in prod and are
NOT in the app files, so a naive export ships a broken app."""
import io
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
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest tests/test_app_export_bundle.py -q` → ImportError on `ExportError` / `export_app`.

- [ ] **Step 3: Implementation** (append to `app_export.py`)

```python
from dataclasses import field  # add beside the existing dataclass import

from routes_projects import (  # module-level seams, app_git.py pattern
    _run_git as _run_git_default,
    _validate_slug as _validate_slug_default,
)

_run_git = _run_git_default
_validate_slug = _validate_slug_default


class ExportError(Exception):
    """User-visible export failure. The route maps it to a 4xx/5xx detail."""


@dataclass(frozen=True)
class SupabaseInfo:
    """Decrypted, export-safe subset of the project's Supabase link.

    Only url + anon key ever reach the bundle (both public by construction:
    they are injected into every served page today). `never_export` carries
    the decrypted secrets purely so tests can assert they are NOT in the zip.
    `schema_runner` is the injected run_sql for build_schema_sql, or None.
    """
    url: str
    anon_key: str
    schema_runner: object = None
    never_export: tuple = field(default_factory=tuple)


def _config_js(info: SupabaseInfo, slug: str) -> str:
    return (
        "// Written by IO export. Your own Supabase project; the anon key is\n"
        "// public by design (RLS is the security boundary).\n"
        f"window.SUPABASE_URL = {info.url!r};\n"
        f"window.SUPABASE_ANON_KEY = {info.anon_key!r};\n"
        f"window.AIUI_SLUG = {slug!r};\n"
    )


_EXAMPLE_CONFIG = (
    "// Copy to aiui-config.js and fill in from your Supabase project settings\n"
    "// (Project Settings, API). The anon key is safe to ship; RLS protects data.\n"
    "window.SUPABASE_URL = 'https://YOUR-PROJECT.supabase.co';\n"
    "window.SUPABASE_ANON_KEY = 'YOUR-ANON-KEY';\n"
)


def _inject_config_tag(index_html: str) -> str:
    tag = '<script src="./aiui-config.js"></script>'
    if tag in index_html:
        return index_html
    lowered = index_html.lower()
    i = lowered.find("</head>")
    if i == -1:
        return tag + "\n" + index_html
    return index_html[:i] + "  " + tag + "\n" + index_html[i:]


def _readme(slug: str, profile: AppProfile, *, had_history: bool,
            supabase: str, schema_note: str) -> str:
    parts = [
        f"# {slug}",
        "",
        "Exported from IO. This folder is a complete, standalone copy of your "
        "app, including its git history. You own it.",
        "",
        "## Run it locally",
        "",
        "```",
        "python -m http.server 8000",
        "```",
        "Then open http://localhost:8000 (or just open `index.html`).",
        "",
        build_deploy_guide(profile),
    ]
    if supabase:
        parts += ["## Database (Supabase)", "", supabase, ""]
    if schema_note:
        parts += [schema_note, ""]
    parts += ["## History", ""]
    parts.append(
        "Your full change history is in this repository: run `git log`."
        if had_history else
        "Prior history was not available for this app, so the repository "
        "starts at this export.")
    parts.append("")
    return "\n".join(parts)


async def _materialize_repo(slug: str, tmp: Path) -> tuple[Path, bool]:
    """Standalone repo at tmp/repo. Returns (repo_dir, had_history)."""
    repo = tmp / "repo"
    rc, out = await _run_git("log", "--max-count=1", "--format=%H",
                             "--", f"apps/{slug}/")
    if rc == 0 and out.strip():
        branch = f"export-tmp-{slug}"
        rc, out = await _run_git("subtree", "split", f"--prefix=apps/{slug}",
                                 "-b", branch)
        if rc != 0:
            raise ExportError(f"history extraction failed: {out[:300]}")
        try:
            from routes_projects import REPO_ROOT
            rc, out = await _run_git("clone", "--branch", branch,
                                     f"file://{REPO_ROOT}", str(repo))
            if rc != 0:
                raise ExportError(f"clone failed: {out[:300]}")
        finally:
            await _run_git("branch", "-D", branch)
        await _run_git("remote", "remove", "origin", cwd=str(repo))
        return repo, True

    # Fallback: no commits touch this app. Fresh repo from the tree on disk.
    src = _APPS_ROOT / slug
    shutil.copytree(src, repo,
                    ignore=shutil.ignore_patterns(*_SKIP_DIRS))
    for args in (("init", "-b", "main"), ("add", "--", ".")):
        rc, out = await _run_git(*args, cwd=str(repo))
        if rc != 0:
            raise ExportError(f"git {args[0]} failed: {out[:300]}")
    rc, out = await _run_git(
        "-c", "user.email=export@aiui", "-c", "user.name=IO Export",
        "commit", "-q", "-m", "Exported from IO (no prior history)",
        cwd=str(repo))
    if rc != 0:
        raise ExportError(f"initial commit failed: {out[:300]}")
    return repo, False


async def export_app(slug: str, *, actor_email: str,
                     supabase_row: SupabaseInfo | None) -> tuple[Path, str]:
    """Build the bundle. Returns (zip_path, filename); caller streams + cleans
    up the parent temp dir. Raises ExportError with a plain-words message."""
    _validate_slug(slug)
    profile = analyze_app(slug)
    if profile is None:
        raise ExportError(f"no such app: apps/{slug}/ does not exist")
    if not profile.has_index:
        raise ExportError(
            f"apps/{slug}/ has no index.html; only static apps can be exported")

    tmp = Path(tempfile.mkdtemp(prefix="ioexport-"))
    repo, had_history = await _materialize_repo(slug, tmp)

    supabase_section = ""
    schema_note = ""
    if supabase_row is not None:
        (repo / "aiui-config.js").write_text(
            _config_js(supabase_row, slug), encoding="utf-8")
        idx = repo / "index.html"
        if idx.is_file():
            idx.write_text(_inject_config_tag(
                idx.read_text(encoding="utf-8", errors="replace")),
                encoding="utf-8")
        supabase_section = (
            "This bundle includes `aiui-config.js` with YOUR Supabase project "
            "URL and anon key, so the app works out of the box. The anon key "
            "is public by design; Row Level Security is the boundary.")
        if supabase_row.schema_runner is not None:
            try:
                (repo / "schema.sql").write_text(
                    await build_schema_sql(supabase_row.schema_runner),
                    encoding="utf-8")
                supabase_section += (
                    " Your database structure is in `schema.sql`, generated "
                    "from the live database.")
            except Exception as exc:  # noqa: BLE001 - enrichment degrades
                logger.warning("export: schema introspection failed for %s: %s",
                               slug, exc)
                schema_note = ("Note: the database schema could not be read "
                               "at export time, so `schema.sql` is absent.")
    elif profile.uses_supabase:
        (repo / "aiui-config.example.js").write_text(_EXAMPLE_CONFIG,
                                                    encoding="utf-8")
        supabase_section = (
            "This app expects a Supabase project. Copy "
            "`aiui-config.example.js` to `aiui-config.js` and fill in your "
            "project URL and anon key, then add a `<script "
            'src="./aiui-config.js"></script>` tag to `index.html`.')

    (repo / "README.md").write_text(
        _readme(slug, profile, had_history=had_history,
                supabase=supabase_section, schema_note=schema_note),
        encoding="utf-8")

    rc, _ = await _run_git("add", "--", ".", cwd=str(repo))
    if rc == 0:
        await _run_git(
            "-c", f"user.email={actor_email or 'export@aiui'}",
            "-c", f"user.name={(actor_email or 'export').split('@')[0]}",
            "commit", "-q", "-m", "Export from IO: config, schema and README",
            cwd=str(repo))

    rc, out = await _run_git("rev-parse", "--short", "HEAD", cwd=str(repo))
    short = out.strip() if rc == 0 and had_history else ("fresh" if not had_history
                                                        else "export")
    filename = f"{slug}-export-{short}.zip"
    zip_base = tmp / "bundle"
    shutil.make_archive(str(zip_base), "zip", root_dir=str(repo))
    zip_path = tmp / filename
    (tmp / "bundle.zip").rename(zip_path)
    return zip_path, filename
```

- [ ] **Step 4: Run, verify green** — `python -m pytest tests/test_app_export_bundle.py -q` → `8 passed`. Then the whole export set: `python -m pytest tests/test_app_export_analyze.py tests/test_app_export_guide.py tests/test_app_export_schema.py tests/test_app_export_bundle.py -q` → `18 passed`.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/app_export.py mcp-servers/tasks/tests/test_app_export_bundle.py
git commit -m "feat(export): build the bundle - real repo, runnable config, README"
```

---

### Task 5: Routes — guide + download

**Files:**
- Modify: `mcp-servers/tasks/routes_projects.py` (append, near the docs route at ~line 650)
- Create: `mcp-servers/tasks/tests/test_app_export_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Route registration + the pure pieces. Full behavior needs the DB tier, so
it is covered by the server e2e (Task 7). Assert via app.openapi(), NOT
app.routes - container FastAPI 0.139 includes routers lazily (memory lesson)."""
from main import app


def test_export_routes_are_registered():
    paths = set(app.openapi()["paths"].keys())
    assert "/api/projects/{slug}/export" in paths
    assert "/api/projects/{slug}/export/guide" in paths


def test_export_route_is_a_get_returning_zip():
    spec = app.openapi()["paths"]["/api/projects/{slug}/export"]
    assert "get" in spec
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest tests/test_app_export_routes.py -q` → KeyError / assert fails (routes absent).

- [ ] **Step 3: Implementation** (append to `routes_projects.py`, after the docs route)

```python
# --- Export: Take Your App With You (spec 2026-07-27) ----------------------
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import app_export as _app_export
import crypto_utils as _crypto
from models import ProjectSupabase as _PS
import routes_db as _routes_db


async def _supabase_info_for(s, slug: str):
    """Decrypted export-safe Supabase info + schema runner, or None."""
    row = (await s.execute(
        select(_PS).where(_PS.slug == slug))).scalar_one_or_none()
    if row is None or not row.supabase_url:
        return None
    try:
        anon = _crypto.decrypt(row.anon_key_encrypted)
    except Exception:  # noqa: BLE001 - enrichment degrades to example config
        return None

    runner = None
    if (row.oauth_access_token_encrypted and row.linked_project_ref) \
            or row.db_uri_encrypted:
        async def runner(sql: str):
            if row.oauth_access_token_encrypted and row.linked_project_ref:
                resp = await _routes_db._exec_via_management_api(s, row, sql)
            else:
                resp = await _routes_db._exec_via_asyncpg(
                    _crypto.decrypt(row.db_uri_encrypted), sql)
            return resp.rows
    return _app_export.SupabaseInfo(url=row.supabase_url, anon_key=anon,
                                    schema_runner=runner)


@router.get("/{slug}/export/guide")
async def export_guide(slug: str,
                       user: AdminUser = Depends(current_admin_or_capability_for_slug)):
    """Deploy-guide markdown for the gallery modal."""
    _validate_slug(slug)
    profile = _app_export.analyze_app(slug)
    if profile is None:
        raise HTTPException(status_code=404, detail="App not found on disk")
    return {"markdown": _app_export.build_deploy_guide(profile)}


@router.get("/{slug}/export")
async def export_bundle(slug: str,
                        user: AdminUser = Depends(current_admin_or_capability_for_slug)):
    """Download the app as a working git repository (zip).

    User-initiated: a good bundle or a clear error, never a silent partial.
    Holds the per-slug build lock for the duration so we never zip a
    half-written tree; a live build/enhance means 409, not a wait."""
    _validate_slug(slug)
    async with session() as s:
        got = (await s.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:k))"),
            {"k": f"build:{slug}"})).scalar()
        if not got:
            raise HTTPException(
                status_code=409,
                detail="A build or enhance is running for this app; "
                       "try again when it finishes.")
        info = await _supabase_info_for(s, slug)
        try:
            zip_path, filename = await _app_export.export_app(
                slug, actor_email=getattr(user, "email", "") or "",
                supabase_row=info)
        except _app_export.ExportError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    return FileResponse(
        path=str(zip_path), filename=filename, media_type="application/zip",
        background=BackgroundTask(shutil.rmtree, str(zip_path.parent),
                                  ignore_errors=True))
```

Also add `import shutil` and `from sqlalchemy import text` to
`routes_projects.py` imports **if not already present** (check first: `text`
is already imported in several routers; `shutil` may not be).

- [ ] **Step 4: Run, verify green** — `python -m pytest tests/test_app_export_routes.py -q` → `2 passed`, then the import-guard from the regression suite: `python -m pytest tests/test_app_regression.py -q -k actually_exists` → `1 passed` (catches any name I forgot to import — this exact class of bug shipped once this week).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/routes_projects.py mcp-servers/tasks/tests/test_app_export_routes.py
git commit -m "feat(export): GET /api/projects/{slug}/export + /export/guide"
```

---

### Task 6: Gallery UI — Export button + modal

**Files:**
- Modify: `mcp-servers/tasks/static/projects.html` (three spots: modal markup near the docs-modal at line ~986, card buttons at line ~1372, JS wiring near openDocsModal at line ~2501)

No new framework. Mirror the Docs modal exactly, with **unique ids and vars**
(`export-modal`, `exportModal` — the duplicate-`dmModal` SyntaxError of
2026-07-16 killed the whole gallery script; Ralph's `test_static_page_js`
now pins unique ids, so it will catch a collision).

- [ ] **Step 1: Add the modal markup** (immediately after the `docs-modal` div)

```html
  <div id="export-modal" class="modal-backdrop" hidden>
    <div class="modal" style="max-width: 680px;">
      <div class="modal-header">
        <h3>Export: <span id="export-slug"></span></h3>
        <button type="button" class="close" data-close>&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-hint" style="margin-bottom:6px;">Download this app as a
          working git repository: code, history, config and a README that
          explains where it can run and how.</div>
        <div id="export-body" class="docs-body">
          <div class="members-empty">Loading the deploy guide...</div>
        </div>
        <div style="margin-top:12px; display:flex; justify-content:flex-end;">
          <button type="button" id="export-download" class="btn primary">Download zip</button>
        </div>
      </div>
    </div>
  </div>
```

- [ ] **Step 2: Add the card button.** At the card-render line (~1372), next to the Docs button ternary, add the same pattern:

```javascript
        const exportBtn = t.built_app_slug
          ? `<button type="button" class="members-btn export-btn" data-slug="${escapeHtml(t.built_app_slug)}">Export</button>`
          : "";
```

and include `${exportBtn}` in the button-row template right after `${docsBtn}`.
Then update the exclusion selector at line ~1397 to also exclude it:
`grid.querySelectorAll("button.members-btn:not(.history-btn):not(.docs-btn):not(.export-btn)")`
and add the wiring beside the docs one:

```javascript
      grid.querySelectorAll("button.export-btn").forEach((b) => {
        b.addEventListener("click", () => openExportModal(b.dataset.slug));
      });
```

- [ ] **Step 3: Add the JS** (beside `openDocsModal`, same section)

```javascript
    // ===== Export modal (deploy guide + bundle download) =====
    const exportModal = document.getElementById("export-modal");
    const exportSlugEl = document.getElementById("export-slug");
    const exportBody = document.getElementById("export-body");
    const exportDownload = document.getElementById("export-download");
    let exportCurrentSlug = null;

    function _closeExportModal() { exportModal.hidden = true; }
    exportModal.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", _closeExportModal));
    exportModal.addEventListener("click", (ev) => { if (ev.target === exportModal) _closeExportModal(); });
    document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !exportModal.hidden) _closeExportModal(); });

    async function openExportModal(slug) {
      if (!slug) return;
      exportCurrentSlug = slug;
      exportSlugEl.textContent = slug;
      exportBody.innerHTML = `<div class="members-empty">Loading the deploy guide...</div>`;
      exportModal.hidden = false;
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(slug)}/export/guide`, {
          headers: authHeaders(),
          credentials: "include",
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        exportBody.innerHTML = DOMPurify.sanitize(marked.parse(data.markdown || ""));
      } catch (e) {
        exportBody.innerHTML = `<div class="members-empty">Could not load the guide (${escapeHtml(String(e.message || e))}).</div>`;
      }
    }

    exportDownload.addEventListener("click", async () => {
      if (!exportCurrentSlug) return;
      exportDownload.disabled = true;
      exportDownload.textContent = "Preparing...";
      try {
        const r = await fetch(`/api/projects/${encodeURIComponent(exportCurrentSlug)}/export`, {
          headers: authHeaders(),
          credentials: "include",
        });
        if (!r.ok) {
          let detail = `HTTP ${r.status}`;
          try { detail = (await r.json()).detail || detail; } catch (_e) {}
          throw new Error(detail);
        }
        const blob = await r.blob();
        const cd = r.headers.get("Content-Disposition") || "";
        const m = cd.match(/filename="?([^";]+)"?/);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = m ? m[1] : `${exportCurrentSlug}-export.zip`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
      } catch (e) {
        exportBody.innerHTML = `<div class="members-empty">Export failed: ${escapeHtml(String(e.message || e))}</div>` + exportBody.innerHTML;
      } finally {
        exportDownload.disabled = false;
        exportDownload.textContent = "Download zip";
      }
    });
```

- [ ] **Step 4: Verify with Ralph's static-JS test** (parses every page's JS and pins unique ids — this is the dmModal-regression guard): `python -m pytest tests/test_static_page_js.py -q` → all pass.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/projects.html
git commit -m "feat(export): gallery Export button + deploy-guide modal + zip download"
```

---

### Task 7: Full suite, deploy, end-to-end, push

- [ ] **Step 1: Full local suite** — `cd mcp-servers/tasks && python -m pytest tests/ -q` → expect ~1113 passed; the ~131 `ERROR at setup` are the pre-existing DB tier (no local Postgres), count must not grow.

- [ ] **Step 2: Deploy** (orchestrator needs rsync, absent on this machine — manual per file, CRLF-normalize, rebuild):

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO"
for f in app_export.py routes_projects.py static/projects.html \
         tests/test_app_export_analyze.py tests/test_app_export_guide.py \
         tests/test_app_export_schema.py tests/test_app_export_bundle.py \
         tests/test_app_export_routes.py; do
  scp "mcp-servers/tasks/$f" "root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/$f"
done
ssh root@46.224.193.25 "cd /root/proxy-server \
  && sed -i 's/\r\$//' mcp-servers/tasks/app_export.py mcp-servers/tasks/routes_projects.py mcp-servers/tasks/static/projects.html mcp-servers/tasks/tests/test_app_export_*.py \
  && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

- [ ] **Step 3: In-container tests** — `ssh root@46.224.193.25 "docker exec tasks sh -lc 'cd /app && python -m pytest tests/test_app_export_analyze.py tests/test_app_export_guide.py tests/test_app_export_schema.py tests/test_app_export_bundle.py tests/test_app_export_routes.py -q'"` → all pass.

- [ ] **Step 4: E2E with real history (the real proof).** In the container, export `icecreamery` (has real commits), unzip, verify:

```bash
ssh root@46.224.193.25 "docker exec tasks sh -lc '
cd /tmp && rm -rf exproof && mkdir exproof && cd exproof
python -c \"
import asyncio, sys; sys.path.insert(0, chr(47)+chr(97)+chr(112)+chr(112))
import app_export
async def m():
    p, name = await app_export.export_app(\\\"icecreamery\\\", actor_email=\\\"e2e@test\\\", supabase_row=None)
    print(\\\"zip:\\\", name); import shutil; shutil.copy(p, \\\"./bundle.zip\\\")
asyncio.run(m())\"
python -m zipfile -e bundle.zip out/
cd out && git log --oneline | head -3 && ls README.md index.html
python -m http.server 8877 & sleep 1
python -c \"import urllib.request; r=urllib.request.urlopen(\\\"http://127.0.0.1:8877/index.html\\\"); print(\\\"HTTP\\\", r.status)\"
kill %1'"
```

Expected: the zip name carries a short sha, `git log` shows icecreamery's real commits plus the export commit, `HTTP 200`.

- [ ] **Step 5: E2E fallback path.** Create a throwaway no-history app on the box (`zz-probe-export`), export it via the API route this time (curl inside the container with `X-User-Email` admin headers, `-o bundle.zip -w '%{http_code}'` expect 200), unzip, confirm README carries the no-history note, then `DELETE .../app` and commit the removal if files were tracked. Also curl the guide endpoint → markdown present, and a 409 check is skipped (needs a live build; covered by the lock unit semantics).

- [ ] **Step 6: Health + gallery.** `curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz` → `{"status":"ok"}`; load the gallery headless (the probe2.py pattern) → no page errors (guards the modal JS).

- [ ] **Step 7: Push + record.**

```bash
git fetch fork && git rebase fork/main   # Ralph pushes often; never force-push
cd mcp-servers/tasks && python -m pytest tests/ -q -k "export" && cd ../..
git push fork main
SHA=$(git rev-parse HEAD)
ssh root@46.224.193.25 "cd /root/proxy-server && echo '{\"sha\":\"'$SHA'\",\"deployed_at\":\"'$(date -Iseconds)'\",\"deployed_by\":\"claude@app-export\"}' > .deploy-state"
```

- [ ] **Step 8: Update memory** — `project_app_ownership_export.md`: Part 2 shipped, note the chat-proxy caveat and that GitHub push is the agreed v2.

---

## Self-review notes (done at write time)

- Spec coverage: analyze/chat-proxy ✓ (T1), capability table + guide ✓ (T2), schema-as-fact incl. RLS-off warning ✓ (T3), subtree + fallback + runnable config + README + zip-with-.git + naming ✓ (T4), routes + lock-held-for-duration + errors-surface ✓ (T5), modal/button with unique ids ✓ (T6), e2e both paths + health ✓ (T7). Secrets-in-bytes test ✓ (T4). Monorepo-untouched test ✓ (T4).
- Type consistency: `AppProfile` positional order used in T2 tests matches T1 definition; `SupabaseInfo(url, anon_key, schema_runner, never_export)` consistent between T4 and T5; `export_app` returns `(Path, str)` everywhere.
- Known thin spot, accepted: the 409-while-live route branch has no unit test (needs the DB tier); the lock SQL mirrors `_create_and_spawn_enhance` verbatim and e2e covers the happy path.
