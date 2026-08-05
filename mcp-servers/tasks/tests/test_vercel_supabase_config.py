"""An app with a database must not deploy to Vercel broken.

IO's own hosting injects `window.SUPABASE_URL` and `window.SUPABASE_ANON_KEY`
into index.html at REQUEST time (main.py::_supabase_inject_for), so those values
are deliberately not in the app's files. The Vercel deploy shipped the files
verbatim, so a database-backed app loaded on Vercel with both globals undefined
— it looks deployed and is dead on arrival.

That is the same shape as the export bug fixed on 2026-07-27: anything that
takes an app OUT of IO has to supply what IO was injecting. Export learned this;
deploy did not.

Injection is keyed on the project HAVING a link, not on scanning the app's code
for Supabase usage. A marker scan would fail open — an app using Supabase in a
way the markers miss would deploy broken again, silently, which is the bug being
fixed. An unused global is harmless; a missing one is not.
"""
import base64

from routes_vercel import (
    SupabaseDeployConfig, config_js_bytes, inject_supabase_config,
)

CFG = SupabaseDeployConfig(url="https://abc123.supabase.co", anon_key="anon-xyz")

INDEX = b"<!doctype html><html><head><title>Shop</title></head><body>hi</body></html>"


def _files(*extra):
    return [("index.html", INDEX), *extra]


def _named(pairs, name):
    return next((data for rel, data in pairs if rel == name), None)


# ---------------------------------------------------------------------------
# The bug itself.
# ---------------------------------------------------------------------------

def test_config_file_is_added_when_the_project_has_a_database():
    out = inject_supabase_config(_files(), CFG)
    cfg = _named(out, "aiui-config.js")
    assert cfg is not None, "deployed without the config the app needs"
    assert b"https://abc123.supabase.co" in cfg
    assert b"anon-xyz" in cfg


def test_index_html_loads_the_config():
    out = inject_supabase_config(_files(), CFG)
    idx = _named(out, "index.html").decode()
    assert 'src="./aiui-config.js"' in idx, (
        "config file shipped but nothing loads it")


def test_the_script_tag_goes_before_the_app_runs():
    """Loaded after the app's own scripts, the globals arrive too late."""
    out = inject_supabase_config(_files(), CFG)
    idx = _named(out, "index.html").decode().lower()
    assert idx.index("aiui-config.js") < idx.index("</head>")


def test_the_globals_match_what_io_hosting_and_export_use():
    """Three places now supply these; a fourth spelling would silently break
    apps that work on IO."""
    cfg = config_js_bytes(CFG, "shop").decode()
    assert "window.SUPABASE_URL" in cfg
    assert "window.SUPABASE_ANON_KEY" in cfg


# ---------------------------------------------------------------------------
# Nothing changes for apps without a database.
# ---------------------------------------------------------------------------

def test_no_database_means_the_payload_is_untouched():
    before = _files(("app.js", b"console.log(1)"))
    out = inject_supabase_config(before, None)
    assert out == before, "altered a deploy that needed nothing"


def test_no_config_file_appears_when_there_is_no_database():
    out = inject_supabase_config(_files(), None)
    assert _named(out, "aiui-config.js") is None


# ---------------------------------------------------------------------------
# Secrets: only the two public values may leave the platform.
# ---------------------------------------------------------------------------

def test_the_database_uri_is_never_shipped():
    """The db_uri gives full admin access. Export refuses to include it and so
    must this; the anon key is public by design, the connection string is not."""
    cfg = SupabaseDeployConfig(
        url="https://abc123.supabase.co", anon_key="anon-xyz")
    blob = b"".join(d for _, d in inject_supabase_config(_files(), cfg))
    assert b"postgresql://" not in blob
    assert b"service_role" not in blob


def test_the_config_dataclass_has_no_place_to_put_a_secret():
    """Structural: a field that could hold the db_uri or an OAuth token would
    eventually be filled in by someone."""
    assert set(SupabaseDeployConfig.__dataclass_fields__) == {"url", "anon_key"}


# ---------------------------------------------------------------------------
# Idempotence and odd inputs.
# ---------------------------------------------------------------------------

def test_running_twice_does_not_duplicate_the_tag():
    once = inject_supabase_config(_files(), CFG)
    twice = inject_supabase_config(once, CFG)
    idx = _named(twice, "index.html").decode()
    assert idx.count("aiui-config.js") == 1


def test_an_app_that_already_ships_its_own_config_is_left_alone():
    """Some apps were exported and re-imported with a config already in place;
    overwriting it would swap the user's own project for ours."""
    own = b"window.SUPABASE_URL = 'https://theirs.supabase.co';"
    out = inject_supabase_config(_files(("aiui-config.js", own)), CFG)
    assert _named(out, "aiui-config.js") == own


def test_index_with_no_head_still_gets_the_config():
    out = inject_supabase_config([("index.html", b"<body>bare</body>")], CFG)
    idx = _named(out, "index.html").decode()
    assert "aiui-config.js" in idx
    assert idx.index("aiui-config.js") < idx.index("<body>")


def test_an_app_with_no_index_html_still_gets_the_config_file():
    """A pure API or a nested entry point: ship the config rather than skip it.
    Silently doing nothing is how this bug existed in the first place."""
    out = inject_supabase_config([("app.js", b"x")], CFG)
    assert _named(out, "aiui-config.js") is not None


def test_uppercase_head_tag_is_handled():
    out = inject_supabase_config(
        [("index.html", b"<HTML><HEAD></HEAD><BODY>x</BODY></HTML>")], CFG)
    idx = _named(out, "index.html").decode().lower()
    assert idx.index("aiui-config.js") < idx.index("</head>")


def test_undecodable_index_is_left_alone_rather_than_corrupted():
    """Binary or a broken encoding must not become a mangled index.html."""
    weird = b"\xff\xfe\x00binary"
    out = inject_supabase_config([("index.html", weird)], CFG)
    assert _named(out, "index.html") == weird
    assert _named(out, "aiui-config.js") is not None


def test_the_payload_stays_base64_encodable():
    """The caller feeds this straight into to_vercel_files."""
    for _, data in inject_supabase_config(_files(), CFG):
        base64.b64encode(data)


# ---------------------------------------------------------------------------
# The wiring. A correct helper nobody calls is the exact failure this repo
# keeps repeating (the git-commit sweep, the model ranker caught in review).
# ---------------------------------------------------------------------------

import ast
import inspect
import textwrap

import routes_vercel


def _called_names(func) -> set:
    src = textwrap.dedent(inspect.getsource(func))
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            t = node.func
            while isinstance(t, ast.Attribute):
                names.add(t.attr)
                t = t.value
            if isinstance(t, ast.Name):
                names.add(t.id)
    return names


def test_the_deploy_route_actually_calls_the_injector():
    called = _called_names(routes_vercel.deploy_app)
    assert "inject_supabase_config" in called, (
        "the injector exists but the deploy path does not use it")
    assert "_supabase_deploy_config" in called, (
        "nothing looks up the project's database link")


def test_the_injector_runs_before_the_payload_is_encoded():
    """to_vercel_files base64-encodes; injecting after it would be a no-op on
    already-encoded entries."""
    src = inspect.getsource(routes_vercel.deploy_app)
    assert src.index("inject_supabase_config") < src.index("json=payload")


def test_the_deploy_route_no_longer_encodes_raw_collect_files():
    """Guards the old code path from creeping back."""
    src = inspect.getsource(routes_vercel.deploy_app)
    assert "to_vercel_files(collect_files(" not in src.replace(" ", "")


def _attrs_read(func) -> set:
    """Attribute names the function actually reads, via AST.

    Source text would be fooled by this module's own docstrings, which
    legitimately mention db_uri to explain why it is excluded — the exact
    false positive a source-grep test hit in review.
    """
    src = textwrap.dedent(inspect.getsource(func))
    return {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}


def test_the_lookup_never_reads_a_secret_field():
    """The connection string and OAuth token must not leave the platform: this
    payload is uploaded to a third party and served to every visitor."""
    read = _attrs_read(routes_vercel._supabase_deploy_config)
    for secret in ("db_uri_encrypted", "oauth_access_token_encrypted",
                   "oauth_refresh_token_encrypted", "service_role_key"):
        assert secret not in read, f"reads {secret}, which must stay internal"
    assert "anon_key_encrypted" in read, "should read exactly the public key"
