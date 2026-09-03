"""Reading and searching one app, within limits.

The limits are not tidiness. A tool result goes into a chat conversation
and then into the next prompt, so an uncapped file read is a way to spend
somebody's context on a minified bundle.
"""
import os
import pathlib

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


def _symlinks_work(tmp_path):
    """Windows refuses symlinks without developer mode or admin rights."""
    target = tmp_path / "_probe_target"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "_probe_link"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError):
        return False
    link.unlink()
    return True


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


def test_search_does_not_follow_a_symlink_out_of_the_app(tmp_path):
    """os.walk will not descend a symlinked directory, but a symlinked
    FILE is yielded like any other and the OS follows it on read. This
    is the case that leaks, and the reported path is the innocent
    in-app name, so nothing in the result would show it."""
    if not _symlinks_work(tmp_path):
        pytest.skip("this platform will not create symlinks")
    app = _app(tmp_path)
    outside = tmp_path / "secrets.env"
    outside.write_text("DATABASE_URL=postgres://real\n", encoding="utf-8")
    os.symlink(outside, app / "notes.txt")
    assert search_files("shop", "DATABASE_URL", apps_root=tmp_path) == []


def test_listing_does_not_include_a_symlink_out_of_the_app(tmp_path):
    if not _symlinks_work(tmp_path):
        pytest.skip("this platform will not create symlinks")
    app = _app(tmp_path)
    outside = tmp_path / "secrets.env"
    outside.write_text("x", encoding="utf-8")
    os.symlink(outside, app / "notes.txt")
    assert "notes.txt" not in list_files("shop", apps_root=tmp_path)


@pytest.mark.parametrize("name", ["dist", "node_modules"])
def test_a_bare_file_named_like_a_denied_folder_is_not_searchable(tmp_path, name):
    """read_file refuses this because it checks every segment including
    the filename. The walker must agree, or content the direct read
    denies is retrievable in bulk."""
    app = _app(tmp_path)
    (app / "src" / name).write_text("password=hunter2\n", encoding="utf-8")
    assert search_files("shop", "hunter2", apps_root=tmp_path) == []
    assert not [p for p in list_files("shop", apps_root=tmp_path) if p.endswith(name)]


@pytest.mark.parametrize("name", ["server.pem", "server.key", "id_rsa"])
def test_a_credential_file_is_not_searchable_or_listed(tmp_path, name):
    """The same rule resolve_app_file enforces, now enforced once and
    tested on the path that walks rather than only the one that reads."""
    app = _app(tmp_path)
    (app / name).write_text("BEGIN PRIVATE KEY\n", encoding="utf-8")
    assert search_files("shop", "PRIVATE KEY", apps_root=tmp_path) == []
    assert name not in list_files("shop", apps_root=tmp_path)


def test_a_huge_file_is_never_slurped_into_memory(tmp_path, monkeypatch):
    """The cap has to bound what is READ, not only what is returned.
    read_bytes on a large vendored file would sit in a 3.8GB box in
    full before anything truncated it."""
    app = _app(tmp_path)
    (app / "huge.txt").write_text("x" * (MAX_FILE_BYTES * 4), encoding="utf-8")

    def _forbidden(self):
        raise AssertionError("the whole file was read; use a bounded read")

    monkeypatch.setattr(pathlib.Path, "read_bytes", _forbidden)
    assert read_file("shop", "huge.txt", apps_root=tmp_path).endswith(
        TRUNCATION_MARKER)
    assert search_files("shop", "xxxx", apps_root=tmp_path)


def test_a_file_that_vanishes_is_a_clean_refusal(tmp_path, monkeypatch):
    """The App Builder agent can be editing an app while a chat reads
    it, so the file really can go between the resolve and the read."""
    app = _app(tmp_path)
    target = app / "index.html"

    real_open = pathlib.Path.open

    def _vanish(self, *args, **kwargs):
        if self.name == "index.html":
            raise FileNotFoundError(2, "gone")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", _vanish)
    with pytest.raises(CodeAccessError):
        read_file("shop", "index.html", apps_root=tmp_path)
