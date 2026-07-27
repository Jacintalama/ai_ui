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
