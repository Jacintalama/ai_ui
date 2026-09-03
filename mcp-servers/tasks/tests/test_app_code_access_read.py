"""Reading and searching one app, within limits.

The limits are not tidiness. A tool result goes into a chat conversation
and then into the next prompt, so an uncapped file read is a way to spend
somebody's context on a minified bundle.
"""
import pytest

from app_code_access import (
    MAX_FILE_BYTES,
    MAX_SEARCH_MATCHES,
    TRUNCATION_MARKER,
    CodeAccessError,
    list_files,
    read_file,
    search_files,
)


def _app(tmp_path, slug="shop"):
    d = tmp_path / slug
    (d / "src").mkdir(parents=True)
    (d / "index.html").write_text("<h1>Shop</h1>\n", encoding="utf-8", newline="")
    (d / "src" / "Checkout.tsx").write_text(
        "export function Checkout() {\n  return null;\n}\n", encoding="utf-8")
    return d


def test_reads_a_file(tmp_path):
    _app(tmp_path)
    assert read_file("shop", "index.html", apps_root=tmp_path) == "<h1>Shop</h1>\n"


def test_a_large_file_is_truncated_and_says_so(tmp_path):
    app = _app(tmp_path)
    (app / "big.txt").write_text("x" * (MAX_FILE_BYTES + 500), encoding="utf-8")
    got = read_file("shop", "big.txt", apps_root=tmp_path)
    assert TRUNCATION_MARKER in got
    assert len(got) < MAX_FILE_BYTES + len(TRUNCATION_MARKER) + 100


def test_a_binary_file_is_refused_not_printed(tmp_path):
    app = _app(tmp_path)
    (app / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")
    with pytest.raises(CodeAccessError):
        read_file("shop", "logo.png", apps_root=tmp_path)


def test_search_finds_the_line_and_says_where(tmp_path):
    _app(tmp_path)
    hits = search_files("shop", "Checkout", apps_root=tmp_path)
    assert hits
    first = hits[0]
    assert first["path"] == "src/Checkout.tsx"
    assert first["line"] == 1
    assert "Checkout" in first["text"]


def test_search_is_case_insensitive(tmp_path):
    _app(tmp_path)
    assert search_files("shop", "checkout", apps_root=tmp_path)


def test_search_skips_denied_folders(tmp_path):
    app = _app(tmp_path)
    (app / "node_modules").mkdir()
    (app / "node_modules" / "dep.js").write_text("Checkout\n", encoding="utf-8")
    for hit in search_files("shop", "Checkout", apps_root=tmp_path):
        assert "node_modules" not in hit["path"]


def test_search_skips_binaries(tmp_path):
    app = _app(tmp_path)
    (app / "blob.bin").write_bytes(b"Checkout\x00more")
    for hit in search_files("shop", "Checkout", apps_root=tmp_path):
        assert hit["path"] != "blob.bin"


def test_search_is_capped(tmp_path):
    app = _app(tmp_path)
    (app / "many.txt").write_text("needle\n" * (MAX_SEARCH_MATCHES + 40),
                                  encoding="utf-8")
    assert len(search_files("shop", "needle", apps_root=tmp_path)) == MAX_SEARCH_MATCHES


def test_search_with_an_empty_query_is_refused(tmp_path):
    _app(tmp_path)
    with pytest.raises(CodeAccessError):
        search_files("shop", "   ", apps_root=tmp_path)


def test_lists_files_relative_to_the_app(tmp_path):
    _app(tmp_path)
    got = list_files("shop", apps_root=tmp_path)
    assert "index.html" in got
    assert "src/Checkout.tsx" in got


def test_listing_skips_denied_folders_and_dotfiles(tmp_path):
    app = _app(tmp_path)
    (app / "node_modules").mkdir()
    (app / "node_modules" / "dep.js").write_text("x", encoding="utf-8")
    (app / ".env").write_text("SECRET=1", encoding="utf-8")
    got = list_files("shop", apps_root=tmp_path)
    assert not [p for p in got if "node_modules" in p]
    assert ".env" not in got


@pytest.mark.parametrize("name", ["Node_Modules", "DIST"])
def test_search_skips_denied_folders_whatever_their_case(tmp_path, name):
    """resolve_app_file folds case for the same rule. If the walker
    does not, a folder is unreadable by name and searchable in bulk,
    which is the worse of the two."""
    app = _app(tmp_path)
    (app / name).mkdir()
    (app / name / "dep.js").write_text("Checkout\n", encoding="utf-8")
    for hit in search_files("shop", "Checkout", apps_root=tmp_path):
        assert name not in hit["path"]


@pytest.mark.parametrize("name", ["Node_Modules", "DIST"])
def test_listing_skips_denied_folders_whatever_their_case(tmp_path, name):
    app = _app(tmp_path)
    (app / name).mkdir()
    (app / name / "dep.js").write_text("x", encoding="utf-8")
    assert not [p for p in list_files("shop", apps_root=tmp_path) if name in p]
