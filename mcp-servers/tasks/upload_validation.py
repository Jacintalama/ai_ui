"""Pure validation helpers for the project-upload endpoint. No I/O.

Centralises the security model (path safety, allowlists, size caps) so
both unit tests and the route handler share the same rules. If a future
endpoint accepts a different kind of upload, copy-edit these constants
rather than wiring in a new ad-hoc validator.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# ── Hard limits (see plan §"Hard limits") ─────────────────────────────
MAX_FILE_BYTES = 5 * 1024 * 1024            # 5 MB
MAX_TOTAL_BYTES = 50 * 1024 * 1024          # 50 MB
MAX_FILES = 200
MAX_PATH_DEPTH = 8
MAX_PATH_LEN = 200

# ── File-type allowlist ───────────────────────────────────────────────
ALLOWED_EXTS = frozenset({
    # Web
    ".html", ".htm", ".css", ".js", ".mjs", ".json",
    ".svg", ".txt", ".md", ".xml", ".csv",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".avif",
    # Fonts
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    # Data
    ".sql",
})

# ── Always-skip components (silently dropped, not an error) ───────────
SKIP_DIR_NAMES = frozenset({
    ".git", ".svn", ".hg", "node_modules", "__pycache__",
    ".next", ".nuxt", "dist", "build", ".cache", ".idea", ".vscode",
})
SKIP_FILE_NAMES = frozenset({
    ".env", ".env.local", ".env.production", ".env.development",
    ".ds_store", "thumbs.db",
})

# ── Windows reserved names (rejected, not dropped — these are suspicious) ─
WIN_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


@dataclass(frozen=True)
class ValidatedFile:
    """A file that passed every check and is safe to write."""
    rel_path: str   # POSIX-style, relative, no leading slash
    size: int       # bytes
    ext: str        # lowercase including dot, e.g. ".html"


class UploadRejected(ValueError):
    """Raised when an upload (or any file in it) fails validation."""
    pass


def normalize_rel_path(raw: str) -> str | None:
    """Normalize a browser-supplied relative path. Returns None if the
    file should be silently SKIPPED (e.g. .git, node_modules).
    Raises UploadRejected for actively malicious paths."""
    if not raw or not isinstance(raw, str):
        raise UploadRejected("empty path")
    if "\x00" in raw:
        raise UploadRejected("null byte in path")
    if "\\" in raw:
        raise UploadRejected("backslash in path (use forward slashes)")
    if len(raw) > MAX_PATH_LEN:
        raise UploadRejected(f"path too long ({len(raw)} > {MAX_PATH_LEN})")

    # Strip leading slashes, collapse slashes, strip surrounding whitespace.
    cleaned = raw.strip().lstrip("/")
    if not cleaned:
        raise UploadRejected("empty path after cleaning")

    parts = cleaned.split("/")

    # Reject path traversal.
    for p in parts:
        if p in ("", ".", ".."):
            raise UploadRejected("path contains '.' or '..' or empty segment")
        # Reject Windows drive letters or absolute Windows paths.
        if len(p) >= 2 and p[1] == ":":
            raise UploadRejected("Windows drive letter in path")
        # Reject reserved Windows device names (case-insensitive, with or without ext).
        stem = p.split(".", 1)[0].upper()
        if stem in WIN_RESERVED:
            raise UploadRejected(f"reserved name in path: {p}")

    # Silent drops — directories or files we never want. Case-insensitive
    # so uploads from case-insensitive filesystems (macOS HFS+, Windows
    # NTFS) can't bypass the skip-list with alternate casing. Also check
    # SKIP_FILE_NAMES against directory segments so a path like
    # ".env/foo.html" is dropped (otherwise we'd silently mkdir ".env/").
    for p in parts[:-1]:  # all dir segments
        low = p.lower()
        if low in SKIP_DIR_NAMES or low in SKIP_FILE_NAMES:
            return None
    if parts[-1].lower() in SKIP_FILE_NAMES:
        return None

    # Depth check (number of directory separators in the relative path).
    if len(parts) - 1 > MAX_PATH_DEPTH:
        raise UploadRejected(f"path nested too deep ({len(parts)-1} > {MAX_PATH_DEPTH})")

    return "/".join(parts)


def validate_extension(rel_path: str) -> str:
    """Return the lowercase extension if allowed, else raise.
    The path must already be normalized."""
    _, ext = os.path.splitext(rel_path)
    ext = ext.lower()
    if ext not in ALLOWED_EXTS:
        raise UploadRejected(f"disallowed file type: {ext or '<none>'}")
    return ext


def validate_one(raw_path: str, size: int) -> ValidatedFile | None:
    """Check one file. Returns None if it should be silently skipped,
    a ValidatedFile if it should be written, or raises UploadRejected."""
    if size < 0:
        raise UploadRejected("negative size")
    if size > MAX_FILE_BYTES:
        raise UploadRejected(
            f"file too large ({size} > {MAX_FILE_BYTES} bytes)"
        )
    rel = normalize_rel_path(raw_path)
    if rel is None:
        return None
    ext = validate_extension(rel)
    return ValidatedFile(rel_path=rel, size=size, ext=ext)


def validate_batch(raw_files: list[tuple[str, int]]) -> list[ValidatedFile]:
    """Run every file through validate_one, then enforce batch caps
    (file count and total size). Skipped files don't count toward caps.
    raw_files is a list of (raw_path, size) tuples."""
    accepted: list[ValidatedFile] = []
    total = 0
    for raw_path, size in raw_files:
        v = validate_one(raw_path, size)
        if v is None:
            continue
        accepted.append(v)
        total += v.size
        if len(accepted) > MAX_FILES:
            raise UploadRejected(
                f"too many files ({len(accepted)} > {MAX_FILES})"
            )
        if total > MAX_TOTAL_BYTES:
            raise UploadRejected(
                f"total size too large ({total} > {MAX_TOTAL_BYTES} bytes)"
            )
    if not accepted:
        raise UploadRejected("no usable files (everything was filtered out)")
    return accepted


def safe_join(base_dir: str, rel_path: str) -> str:
    """Join base_dir with a normalized rel_path and return an absolute
    path that is GUARANTEED to be inside base_dir (realpath-checked).
    Raises UploadRejected if the realpath escapes base_dir."""
    base_real = os.path.realpath(base_dir)
    target_real = os.path.realpath(os.path.join(base_real, rel_path))
    # Must be base_real itself or strictly under it.
    if target_real != base_real and not target_real.startswith(base_real + os.sep):
        raise UploadRejected("path escapes destination directory")
    return target_real
