"""Vercel deploy: pure file-collection helpers. No network/DB."""
import base64

import pytest

from routes_vercel import (is_deployable, collect_files, to_vercel_files,
                           MAX_TOTAL_BYTES)


def test_is_deployable_filters_junk():
    assert is_deployable("index.html") is True
    assert is_deployable("assets/app.js") is True
    assert is_deployable("node_modules/x/y.js") is False
    assert is_deployable(".git/config") is False
    assert is_deployable(".env") is False
    assert is_deployable("sub/.hidden/file") is False


def test_collect_files_walks_and_filters(tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("no")
    (tmp_path / ".env").write_text("SECRET=1")
    pairs = collect_files(str(tmp_path))
    rels = sorted(p for p, _ in pairs)
    assert rels == ["assets/app.js", "index.html"]


def test_collect_files_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        collect_files(str(tmp_path))


def test_collect_files_size_cap(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"x" * (MAX_TOTAL_BYTES + 1))
    with pytest.raises(ValueError):
        collect_files(str(tmp_path))


def test_collect_files_count_cap(tmp_path):
    for i in range(12):
        (tmp_path / f"f{i}.txt").write_text("x")
    with pytest.raises(ValueError):
        collect_files(str(tmp_path), max_files=10)


def test_to_vercel_files_base64_payload():
    out = to_vercel_files([("index.html", b"<h1>hi</h1>")])
    assert out == [{"file": "index.html",
                    "data": base64.b64encode(b"<h1>hi</h1>").decode("ascii"),
                    "encoding": "base64"}]


# --- OAuth state (CSRF) helpers ----------------------------------------------
from routes_vercel import new_oauth_state, pop_oauth_state, oauth_configured


def test_oauth_state_roundtrip_and_single_use():
    s = new_oauth_state("u@x.com")
    assert pop_oauth_state(s) == "u@x.com"
    assert pop_oauth_state(s) is None          # consumed exactly once


def test_oauth_state_expires():
    s = new_oauth_state("u@x.com", now=1000.0)
    assert pop_oauth_state(s, now=1000.0 + 1801) is None


def test_oauth_state_unknown_is_none():
    assert pop_oauth_state("nope") is None
    assert pop_oauth_state("") is None
    assert pop_oauth_state(None) is None


# --- stable live URL ----------------------------------------------------------
from routes_vercel import live_domain


def test_live_domain_prefers_shortest_vercel_alias():
    aliases = ["my-shop-abc123xyz-ralph.vercel.app", "my-shop.vercel.app"]
    assert live_domain(aliases, "my-shop-abc123xyz-ralph.vercel.app") == "my-shop.vercel.app"


def test_live_domain_ignores_git_branch_aliases():
    aliases = ["my-shop-git-main-ralph.vercel.app", "my-shop.vercel.app"]
    assert live_domain(aliases, "dep.vercel.app") == "my-shop.vercel.app"


def test_live_domain_falls_back_to_deployment_url():
    assert live_domain([], "my-shop-n9ktukufu.vercel.app") == "my-shop-n9ktukufu.vercel.app"
    assert live_domain(None, "my-shop-n9ktukufu.vercel.app") == "my-shop-n9ktukufu.vercel.app"


def test_live_domain_ignores_custom_domains():
    # Custom domains on the user's Vercel are theirs to manage; we promise the
    # stable *.vercel.app URL and fall back to the deployment URL otherwise.
    assert live_domain(["myshop.com"], "dep.vercel.app") == "dep.vercel.app"
    assert live_domain(["myshop.com", "my-shop.vercel.app"], "dep.vercel.app") == "my-shop.vercel.app"


def test_live_domain_skips_non_string_entries():
    assert live_domain([None, 42, "my-shop.vercel.app"], "dep.vercel.app") == "my-shop.vercel.app"
