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
    if base not in candidate.parents:
        raise CodeAccessError("that file is not inside this app")

    for part in candidate.relative_to(base).parts:
        if part.startswith("."):
            raise CodeAccessError("that file is hidden, so it is not read here")
        if part.lower() in DENIED_SEGMENTS:
            raise CodeAccessError("that folder is not read here")

    name = candidate.name.lower()
    if name.endswith(_DENIED_SUFFIXES) or name.startswith(_DENIED_PREFIXES):
        raise CodeAccessError("that file looks like a credential, so it is not read here")

    if not candidate.is_file():
        raise CodeAccessError("there is no file at that path in this app")
    return candidate


def looks_binary(data: bytes) -> bool:
    """A null byte in the first 8KB. Cheap, and wrong only for files that
    hide their first null past the window, which text files do not do."""
    return b"\x00" in data[:BINARY_SNIFF_BYTES]
