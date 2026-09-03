"""Nothing here may reach a file outside the app it names.

Every check is against a REAL resolved path rather than the text of the
argument, because the two disagree exactly where it matters: a symlink
inside the app pointing out of it contains no "..", passes any string
check, and resolves somewhere else entirely.
"""
import os

import pytest

from app_code_access import (
    BINARY_SNIFF_BYTES,
    CodeAccessError,
    MAX_FILE_BYTES,
    MAX_SEARCH_MATCHES,
    app_dir,
    looks_binary,
    resolve_app_file,
)


def _app(tmp_path, slug="shop"):
    d = tmp_path / slug
    (d / "src").mkdir(parents=True)
    (d / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (d / "src" / "Checkout.tsx").write_text("export const x = 1;\n", encoding="utf-8")
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


def test_a_plain_file_resolves(tmp_path):
    _app(tmp_path)
    got = resolve_app_file("shop", "src/Checkout.tsx", apps_root=tmp_path)
    assert got == (tmp_path / "shop" / "src" / "Checkout.tsx").resolve()


def test_a_backslash_path_resolves_too(tmp_path):
    """The model may echo a Windows style path back at us."""
    _app(tmp_path)
    got = resolve_app_file("shop", "src\\\\Checkout.tsx", apps_root=tmp_path)
    assert got == (tmp_path / "shop" / "src" / "Checkout.tsx").resolve()


def test_traversal_is_refused(tmp_path):
    _app(tmp_path)
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    with pytest.raises(CodeAccessError):
        resolve_app_file("shop", "../secret.txt", apps_root=tmp_path)


def test_deep_traversal_is_refused(tmp_path):
    _app(tmp_path)
    with pytest.raises(CodeAccessError):
        resolve_app_file("shop", "src/../../../etc/passwd", apps_root=tmp_path)


def test_an_absolute_path_is_refused(tmp_path):
    _app(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("no", encoding="utf-8")
    with pytest.raises(CodeAccessError):
        resolve_app_file("shop", str(outside), apps_root=tmp_path)


def test_a_traversing_slug_is_refused(tmp_path):
    """The slug is an argument too, so it gets the same treatment."""
    _app(tmp_path)
    with pytest.raises(CodeAccessError):
        resolve_app_file("../..", "index.html", apps_root=tmp_path)


def test_a_symlink_out_of_the_app_is_refused(tmp_path):
    """The case a string check passes and a real check catches. If this
    test is ever deleted, delete the resolve() with it and admit the
    weaker guarantee."""
    if not _symlinks_work(tmp_path):
        pytest.skip("this platform will not create symlinks")
    app = _app(tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("no", encoding="utf-8")
    os.symlink(outside, app / "escape.txt")
    with pytest.raises(CodeAccessError):
        resolve_app_file("shop", "escape.txt", apps_root=tmp_path)


def test_a_dotfile_is_refused(tmp_path):
    app = _app(tmp_path)
    (app / ".env").write_text("SECRET=1", encoding="utf-8")
    with pytest.raises(CodeAccessError):
        resolve_app_file("shop", ".env", apps_root=tmp_path)


def test_a_denied_directory_is_refused(tmp_path):
    app = _app(tmp_path)
    (app / "node_modules").mkdir()
    (app / "node_modules" / "a.js").write_text("x", encoding="utf-8")
    with pytest.raises(CodeAccessError):
        resolve_app_file("shop", "node_modules/a.js", apps_root=tmp_path)


@pytest.mark.parametrize("name", ["server.pem", "server.key", "id_rsa", "id_rsa.pub"])
def test_a_credential_shaped_filename_is_refused(tmp_path, name):
    app = _app(tmp_path)
    (app / name).write_text("x", encoding="utf-8")
    with pytest.raises(CodeAccessError):
        resolve_app_file("shop", name, apps_root=tmp_path)


def test_a_missing_file_is_refused(tmp_path):
    _app(tmp_path)
    with pytest.raises(CodeAccessError):
        resolve_app_file("shop", "nope.txt", apps_root=tmp_path)


def test_a_directory_is_not_a_file(tmp_path):
    _app(tmp_path)
    with pytest.raises(CodeAccessError):
        resolve_app_file("shop", "src", apps_root=tmp_path)


def test_a_missing_app_is_refused(tmp_path):
    with pytest.raises(CodeAccessError):
        app_dir("nope", apps_root=tmp_path)


def test_binary_detection(tmp_path):
    assert looks_binary(b"hello\nworld") is False
    assert looks_binary(b"hello\x00world") is True
    # A null past the sniff window is not looked at, on purpose: reading
    # the whole of a large file to classify it defeats the point.
    assert looks_binary(b"a" * BINARY_SNIFF_BYTES + b"\x00") is False


def test_the_caps_are_the_values_the_spec_names():
    assert MAX_FILE_BYTES == 65536
    assert MAX_SEARCH_MATCHES == 50
    assert BINARY_SNIFF_BYTES == 8192
