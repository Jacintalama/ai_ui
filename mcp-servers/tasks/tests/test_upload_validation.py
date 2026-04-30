"""Unit tests for upload_validation. Pure functions, no fixtures needed."""
import pytest

from upload_validation import (
    MAX_FILES, MAX_FILE_BYTES, MAX_PATH_DEPTH, MAX_TOTAL_BYTES,
    UploadRejected, normalize_rel_path, validate_batch, validate_extension,
    validate_one, safe_join,
)


# ── normalize_rel_path ────────────────────────────────────────────────

def test_normalize_simple_path():
    assert normalize_rel_path("index.html") == "index.html"

def test_normalize_nested_path():
    assert normalize_rel_path("src/components/Card.js") == "src/components/Card.js"

def test_normalize_strips_leading_slash():
    assert normalize_rel_path("/index.html") == "index.html"

def test_normalize_rejects_dotdot():
    with pytest.raises(UploadRejected, match="\\.\\."):
        normalize_rel_path("../etc/passwd")

def test_normalize_rejects_dotdot_nested():
    # match= ensures we're rejecting because of '..' specifically, not
    # because depth-cap fires first on a deeply-nested adversarial path.
    with pytest.raises(UploadRejected, match="\\.\\."):
        normalize_rel_path("src/../../../etc/passwd")

def test_normalize_rejects_null_byte():
    with pytest.raises(UploadRejected, match="null"):
        normalize_rel_path("foo\x00.html")

def test_normalize_rejects_backslash():
    with pytest.raises(UploadRejected, match="backslash"):
        normalize_rel_path("src\\bad.js")

def test_normalize_rejects_windows_drive_letter():
    with pytest.raises(UploadRejected, match="drive letter"):
        normalize_rel_path("C:/Windows/system32/cmd.exe")

def test_normalize_rejects_windows_reserved_name():
    with pytest.raises(UploadRejected, match="reserved"):
        normalize_rel_path("CON.html")

def test_normalize_skips_git_dir():
    assert normalize_rel_path(".git/config") is None

def test_normalize_skips_node_modules():
    assert normalize_rel_path("node_modules/foo/index.js") is None

def test_normalize_skips_env_file():
    assert normalize_rel_path(".env") is None

def test_normalize_skips_node_modules_uppercase():
    # Case-insensitive skip-list (macOS/Windows filesystems).
    assert normalize_rel_path("Node_Modules/foo/index.js") is None

def test_normalize_skips_env_dir():
    # .env as a directory name should be silently dropped, not mkdir'd.
    assert normalize_rel_path(".env/foo.html") is None

def test_normalize_rejects_too_deep():
    deep = "a/" * (MAX_PATH_DEPTH + 1) + "x.html"
    with pytest.raises(UploadRejected, match="too deep"):
        normalize_rel_path(deep)

def test_normalize_rejects_too_long():
    long = "a" * 250 + ".html"
    with pytest.raises(UploadRejected, match="too long"):
        normalize_rel_path(long)


# ── validate_extension ────────────────────────────────────────────────

def test_extension_allows_html():
    assert validate_extension("foo.html") == ".html"

def test_extension_allows_uppercase():
    # extension check is case-insensitive
    assert validate_extension("foo.HTML") == ".html"

def test_extension_rejects_exe():
    with pytest.raises(UploadRejected, match="disallowed"):
        validate_extension("malware.exe")

def test_extension_rejects_no_extension():
    with pytest.raises(UploadRejected, match="disallowed"):
        validate_extension("README")


# ── validate_one ──────────────────────────────────────────────────────

def test_validate_one_happy_path():
    v = validate_one("index.html", 1024)
    assert v is not None
    assert v.rel_path == "index.html"
    assert v.ext == ".html"
    assert v.size == 1024

def test_validate_one_skipped_returns_none():
    assert validate_one(".git/HEAD", 100) is None

def test_validate_one_rejects_oversize():
    with pytest.raises(UploadRejected, match="too large"):
        validate_one("big.html", MAX_FILE_BYTES + 1)


# ── validate_batch ────────────────────────────────────────────────────

def test_batch_rejects_when_total_size_exceeds():
    files = [(f"file{i}.html", MAX_FILE_BYTES) for i in range(20)]  # 100 MB total
    with pytest.raises(UploadRejected, match="total size"):
        validate_batch(files)

def test_batch_rejects_when_too_many_files():
    files = [(f"f{i}.html", 1) for i in range(MAX_FILES + 1)]
    with pytest.raises(UploadRejected, match="too many"):
        validate_batch(files)

def test_batch_skipped_files_dont_count_toward_caps():
    # 199 real + 50 skipped → still under cap
    files = [(f"f{i}.html", 1) for i in range(MAX_FILES - 1)]
    files += [(f".git/x{i}", 1) for i in range(50)]
    accepted = validate_batch(files)
    assert len(accepted) == MAX_FILES - 1

def test_batch_rejects_empty():
    with pytest.raises(UploadRejected, match="no usable"):
        validate_batch([(".git/HEAD", 10), ("node_modules/x.js", 10)])


# ── safe_join ─────────────────────────────────────────────────────────

def test_safe_join_happy(tmp_path):
    base = str(tmp_path / "apps" / "myapp")
    target = safe_join(base, "src/main.js")
    assert target.startswith(str(tmp_path))
    assert target.endswith("src/main.js") or target.endswith("src\\main.js")

def test_safe_join_blocks_escape(tmp_path):
    base = str(tmp_path / "apps" / "myapp")
    # Even if normalize_rel_path would catch this earlier, defense-in-depth:
    with pytest.raises(UploadRejected):
        safe_join(base, "../../../etc/passwd")
