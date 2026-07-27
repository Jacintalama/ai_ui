"""Take Your App With You: export bundle + deploy guide.

Spec: docs/superpowers/specs/2026-07-27-app-export-bundle-design.md
User-initiated, so errors SURFACE (unlike the fail-open build sweeps); only the
optional enrichments (history, schema) degrade to README notes."""
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
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
        "Create a new public repository on github.com (GitHub Pages on a free "
        "account requires a public repo) and push this folder to it "
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
            "- This app uses Supabase. It needs your project URL and anon key in "
            "`aiui-config.js` to work; the bundle's README explains exactly what to set.")
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
        "-- Constraints and indexes beyond RLS are not included.\n"
        "-- Known limit: array and enum column types may not re-execute verbatim.\n\n"
    )
    if not cols:
        return header + "-- no tables found in schema public\n"

    by_table: dict[str, list[dict]] = {}
    for c in cols:
        by_table.setdefault(c["table_name"], []).append(c)
    rls = {r["relname"]: bool(r["relrowsecurity"]) for r in await run_sql(_Q_RLS)}
    non_tables = sorted(set(by_table) - set(rls))
    by_table = {t: c for t, c in by_table.items() if t in rls}
    policies: dict[str, list[dict]] = {}
    for p in await run_sql(_Q_POLICIES):
        policies.setdefault(p["tablename"], []).append(p)

    out = [header]
    if non_tables:
        out.append(
            "-- Skipped (not ordinary tables, e.g. views): "
            + ", ".join(f'"{t}"' for t in non_tables) + "\n\n")
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
            # Note: the SQL keyword phrase is deliberately never spelled out
            # verbatim here (we say "enable RLS", not "ENABLE ROW LEVEL
            # SECURITY") so this suggestion can never be mistaken for, or
            # accidentally match a check for, a live ALTER statement — RLS
            # state above is reported as fact; this is only a suggestion.
            out.append(
                f'-- WARNING: RLS is NOT enabled on "{table}". With the anon key '
                "public by design, this table is readable by anyone.\n"
                f'-- To fix: ALTER TABLE "{table}" ... then enable RLS and add '
                "a policy.\n")
        out.append("\n")
    return "".join(out)


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
        # A crashed prior export can leave this branch behind, and `subtree
        # split -b` onto a stale tip dies when it is not an ancestor (real on
        # this box: the server tree gets off-pipeline commits). Best-effort
        # delete so a leak can never wedge the slug. Concurrency: subtree
        # split touches neither the index nor the worktree (pure rev-list +
        # commit-tree + one update-ref on this branch), and the export route
        # holds the per-slug build lock, so same-slug races cannot happen and
        # cross-slug splits use different branches.
        await _run_git("branch", "-D", branch)
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
            rc_del, out_del = await _run_git("branch", "-D", branch)
            if rc_del != 0:
                logger.warning("export: temp branch %s not deleted: %s",
                               branch, out_del[:200])
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
    try:
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
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
