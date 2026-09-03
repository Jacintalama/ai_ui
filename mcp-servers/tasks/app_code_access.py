"""Reaching a file inside one app, and never outside it.

Pure on purpose: no database, no HTTP, no request context. The rules about
which path is allowed are the whole security surface of the code tool, and
keeping them here means they can be tested exhaustively against a tmp_path
rather than against a running server.

Containment is decided by resolving the path and asking whether the result
sits under the resolved app directory. Inspecting the argument for ".."
instead would pass a symlink that lives inside the app and points out of
it, which is the case an attacker would actually use.
"""
import os
from pathlib import Path

#: Same default as app_export and app_runner, so all three agree on where
#: apps live when nothing overrides it.
_APPS_ROOT = Path(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")) / "apps"

MAX_FILE_BYTES = 65536
MAX_SEARCH_MATCHES = 50
BINARY_SNIFF_BYTES = 8192

#: Directory names never worth reading and sometimes worth hiding. ".git"
#: would expose the whole monorepo's history through one app's directory.
DENIED_SEGMENTS = frozenset({".git", "node_modules", ".venv", "dist"})

#: Filename shapes that are credentials often enough to refuse by pattern.
_DENIED_SUFFIXES = (".pem", ".key")
_DENIED_PREFIXES = ("id_rsa",)


class CodeAccessError(Exception):
    """Refused. `reason` is written to be shown to the person asking."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _root(apps_root: Path | None) -> Path:
    return Path(apps_root) if apps_root is not None else _APPS_ROOT


def app_dir(slug: str, *, apps_root: Path | None = None) -> Path:
    """The resolved directory of one app, or raise.

    The slug is an argument like any other, so it is contained the same
    way: "../.." as a slug must not become the apps root's parent.
    """
    if not isinstance(slug, str) or not slug.strip():
        raise CodeAccessError("no app was named")

    # A slug is one path segment. Allowing a separator here would let the
    # slug carry segments that the deny loop in resolve_app_file never
    # sees, because they are already part of the base by the time it
    # runs: "shop/node_modules" would read a dependency tree, and
    # "shop/.git" would read the whole monorepo's history.
    if "/" in slug or "\\" in slug:
        raise CodeAccessError("that is not an app on this platform")
    if slug.startswith("."):
        raise CodeAccessError("that is not an app on this platform")

    root = _root(apps_root).resolve()
    candidate = (root / slug).resolve()
    if candidate != root and root not in candidate.parents:
        raise CodeAccessError("that is not an app on this platform")
    if candidate == root:
        raise CodeAccessError("that is not an app on this platform")
    if not candidate.is_dir():
        raise CodeAccessError("there is no app by that name")
    return candidate


def _assert_readable(base: Path, candidate: Path) -> None:
    """The one place that decides whether an already resolved path may
    be read. Both the direct read and the directory walk go through
    here, because a deny list written twice drifts apart, and the copy
    without a test is the one that lets something through."""
    if base not in candidate.parents:
        raise CodeAccessError("that file is not inside this app")

    for part in candidate.relative_to(base).parts:
        if part.startswith("."):
            raise CodeAccessError("that file is hidden, so it is not read here")
        if part.lower() in DENIED_SEGMENTS:
            raise CodeAccessError("that folder is not read here")

    name = candidate.name.lower()
    if name.endswith(_DENIED_SUFFIXES) or name.startswith(_DENIED_PREFIXES):
        raise CodeAccessError(
            "that file looks like a credential, so it is not read here")


def resolve_app_file(slug: str, relative_path: str, *,
                     apps_root: Path | None = None) -> Path:
    """One readable file inside that app, or raise."""
    base = app_dir(slug, apps_root=apps_root)

    if not isinstance(relative_path, str) or not relative_path.strip():
        raise CodeAccessError("no file was named")

    # A model may echo a Windows style path back. Normalising the
    # separator is a convenience, never a security step: containment is
    # still decided by resolve() below.
    cleaned = relative_path.replace("\\", "/").strip().lstrip("/")

    candidate = (base / cleaned).resolve()
    _assert_readable(base, candidate)

    if not candidate.is_file():
        raise CodeAccessError("there is no file at that path in this app")
    return candidate


def looks_binary(data: bytes) -> bool:
    """A null byte in the first 8KB. Cheap, and wrong only for files that
    hide their first null past the window, which text files do not do."""
    return b"\x00" in data[:BINARY_SNIFF_BYTES]


TRUNCATION_MARKER = "\n\n[This file was shortened to fit.]"


def _walkable_files(base: Path):
    """Every readable file under an app, denied folders pruned as we
    descend so we never even stat what is inside them.

    Each candidate is resolved and checked through the same
    _assert_readable that gates a direct read, because os.walk yields a
    symlinked FILE like any other path and the OS follows it on read;
    only a symlinked DIRECTORY is something os.walk itself refuses to
    descend into."""
    for root, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs
                   if d.lower() not in DENIED_SEGMENTS and not d.startswith(".")]
        for name in names:
            candidate = (Path(root) / name).resolve()
            try:
                _assert_readable(base, candidate)
            except CodeAccessError:
                continue
            yield candidate


def _relative(base: Path, path: Path) -> str:
    """Forward slashes whatever the platform, because this string goes
    back to a model that will quote it at us in the next call."""
    return path.relative_to(base).as_posix()


def read_file(slug: str, relative_path: str, *,
              apps_root: Path | None = None) -> str:
    path = resolve_app_file(slug, relative_path, apps_root=apps_root)
    try:
        with path.open("rb") as fh:
            raw = fh.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise CodeAccessError("that file could not be read")
    if looks_binary(raw):
        raise CodeAccessError("that file is not text, so there is nothing to show")

    truncated = len(raw) > MAX_FILE_BYTES
    raw = raw[:MAX_FILE_BYTES]
    text = raw.decode("utf-8", errors="replace")
    return text + TRUNCATION_MARKER if truncated else text


def search_files(slug: str, query: str, *,
                 apps_root: Path | None = None) -> list[dict]:
    base = app_dir(slug, apps_root=apps_root)
    if not isinstance(query, str) or not query.strip():
        raise CodeAccessError("there was nothing to search for")
    needle = query.strip().lower()

    hits: list[dict] = []
    for path in _walkable_files(base):
        try:
            with path.open("rb") as fh:
                raw = fh.read(MAX_FILE_BYTES + 1)
        except OSError:
            continue
        if looks_binary(raw):
            continue
        text = raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                hits.append({"path": _relative(base, path),
                             "line": number,
                             "text": line.strip()[:300]})
                if len(hits) >= MAX_SEARCH_MATCHES:
                    return hits
    return hits


def list_files(slug: str, *, apps_root: Path | None = None) -> list[str]:
    base = app_dir(slug, apps_root=apps_root)
    return sorted(_relative(base, p) for p in _walkable_files(base))
