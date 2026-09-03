# Agent Code Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an agent read the apps a person built, and change one only after that person approves a specific proposal.

**Architecture:** A pure module owns every path and size decision and touches no database, so the security properties are testable without a server. A thin internal-only router adds the membership checks and wires that module to a single-use proposal token. Applying a proposal queues a normal App Builder enhance, so the change inherits the regression baseline, the Playwright smoke, the commit sweep and the automatic rollback that already exist.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, asyncpg, pytest (`asyncio_mode = auto`), Open WebUI native tool (httpx + pydantic).

**Spec:** `docs/superpowers/specs/2026-09-03-agent-code-access-design.md`

## Global Constraints

- Files are capped at **64KB**, truncated with a clear marker. Search returns at most **50 matches**.
- A file is binary if there is a **null byte in the first 8KB**; binaries are refused, never printed.
- Denied: any path segment starting with `.`, any segment in `{".git", "node_modules", ".venv", "dist"}`, and any filename matching `*.pem`, `*.key`, or starting with `id_rsa`.
- Containment is by **resolved real path**, not by string inspection. Rejecting the substring `..` is not the mechanism and is not sufficient.
- Proposal tokens are **single use** and expire after **30 minutes**.
- The slug used when applying comes from the **stored proposal row**, never from the apply call.
- No delete of anything. No creating an app.
- Apps root is `Path(os.environ.get("CLAUDE_WORKSPACE", "/workspace/ai_ui")) / "apps"`, and every public function takes `apps_root: Path | None = None` so tests pass `tmp_path`. This mirrors `app_export.analyze_app`.
- Modules are imported by bare name (`import app_code_access`), matching every other module in `mcp-servers/tasks/`.
- **Never** use an em-dash or en-dash in code comments, docstrings, commit messages, or any user-facing string.
- **Never** add AI attribution to a commit message. No `Co-Authored-By` trailer.
- Commit with named paths only. Never `git add -A`: this repo carries a large untracked `apps/` tree.

---

### Task 1: Path safety core

The one task where a mistake is a security hole rather than a bug. Everything else builds on it.

**Files:**
- Create: `mcp-servers/tasks/app_code_access.py`
- Test: `mcp-servers/tasks/tests/test_app_code_access_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class CodeAccessError(Exception)` with a `.reason` string safe to show a user.
  - `MAX_FILE_BYTES = 65536`, `MAX_SEARCH_MATCHES = 50`, `BINARY_SNIFF_BYTES = 8192`
  - `DENIED_SEGMENTS: frozenset[str]`
  - `app_dir(slug: str, *, apps_root: Path | None = None) -> Path`
  - `resolve_app_file(slug: str, relative_path: str, *, apps_root: Path | None = None) -> Path`
  - `looks_binary(data: bytes) -> bool`

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_app_code_access_paths.py`:

```python
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_app_code_access_paths.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app_code_access'`.

- [ ] **Step 3: Write the module**

Create `mcp-servers/tasks/app_code_access.py`:

```python
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
        if part in DENIED_SEGMENTS:
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
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_app_code_access_paths.py -q`
Expected: all pass. On Windows without developer mode the symlink test reports as skipped, which is expected. It is the single most important test in this task, so it MUST be seen to run and pass on the server in Task 6 before this feature is considered done.

- [ ] **Step 5: Prove the containment test is load bearing**

Temporarily replace `if base not in candidate.parents:` with `if ".." in relative_path:` and re-run. The symlink and absolute-path tests must fail. Restore the real check afterwards. Do not commit the mutation.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/app_code_access.py mcp-servers/tasks/tests/test_app_code_access_paths.py
git commit -m "Reach a file inside one app, and never outside it"
```

---

### Task 2: Reading and searching

**Files:**
- Modify: `mcp-servers/tasks/app_code_access.py`
- Test: `mcp-servers/tasks/tests/test_app_code_access_read.py`

**Interfaces:**
- Consumes: `CodeAccessError`, `MAX_FILE_BYTES`, `MAX_SEARCH_MATCHES`, `DENIED_SEGMENTS`, `app_dir`, `resolve_app_file`, `looks_binary` from Task 1.
- Produces:
  - `read_file(slug: str, relative_path: str, *, apps_root: Path | None = None) -> str`
  - `search_files(slug: str, query: str, *, apps_root: Path | None = None) -> list[dict]` where each dict is `{"path": str, "line": int, "text": str}`
  - `list_files(slug: str, *, apps_root: Path | None = None) -> list[str]`
  - `TRUNCATION_MARKER: str`

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_app_code_access_read.py`:

```python
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
    (d / "index.html").write_text("<h1>Shop</h1>\n", encoding="utf-8")
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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_app_code_access_read.py -q`
Expected: `ImportError: cannot import name 'read_file' from 'app_code_access'`.

- [ ] **Step 3: Add the functions**

Append to `mcp-servers/tasks/app_code_access.py`:

```python
TRUNCATION_MARKER = "\n\n[This file was shortened to fit.]"


def _walkable_files(base: Path):
    """Every readable file under an app, denied folders and dotfiles
    pruned as we descend so we never even stat what is inside them."""
    for root, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs
                   if d not in DENIED_SEGMENTS and not d.startswith(".")]
        for name in names:
            if name.startswith("."):
                continue
            lowered = name.lower()
            if lowered.endswith(_DENIED_SUFFIXES) or lowered.startswith(_DENIED_PREFIXES):
                continue
            yield Path(root) / name


def _relative(base: Path, path: Path) -> str:
    """Forward slashes whatever the platform, because this string goes
    back to a model that will quote it at us in the next call."""
    return path.relative_to(base).as_posix()


def read_file(slug: str, relative_path: str, *,
              apps_root: Path | None = None) -> str:
    path = resolve_app_file(slug, relative_path, apps_root=apps_root)
    raw = path.read_bytes()
    if looks_binary(raw):
        raise CodeAccessError("that file is not text, so there is nothing to show")

    truncated = len(raw) > MAX_FILE_BYTES
    text = raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace")
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
            raw = path.read_bytes()
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
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_app_code_access_read.py tests/test_app_code_access_paths.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/app_code_access.py mcp-servers/tasks/tests/test_app_code_access_read.py
git commit -m "Read and search one app, within limits that fit a conversation"
```

---

### Task 3: The proposal table and its token

**Files:**
- Create: `mcp-servers/tasks/migrations/045_agent_proposals.sql`
- Create: `mcp-servers/tasks/code_proposals.py`
- Test: `mcp-servers/tasks/tests/test_code_proposals.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `PROPOSAL_TTL_SECONDS = 1800`
  - `async def create_proposal(user_email: str, slug: str, description: str) -> str` returning the token.
  - `async def consume_proposal(user_email: str, token: str) -> dict` returning `{"slug": str, "description": str}`, raising `ProposalError` when the token is unknown, another person's, already used, or expired. Marks the row used in the same statement that reads it.
  - `class ProposalError(Exception)` with `.reason`.

- [ ] **Step 1: Write the migration**

Create `mcp-servers/tasks/migrations/045_agent_proposals.sql`:

```sql
-- 045: a change an agent wants to make, waiting for the person to say yes.
--
-- The two-phase confirm this backs is enforced by this row, not by the
-- model: proposing writes here and changes nothing, and applying is the
-- only path that can start a build. A model that decides to skip the
-- confirmation cannot, because there is no other way in.
--
-- A table rather than process memory because the tasks service is not
-- guaranteed to be a single worker, and a proposal made on one worker and
-- confirmed on another must not silently vanish.
--
-- used_at is what makes a token single use. It is set by the same UPDATE
-- that reads the row, so two confirms racing cannot both win.
CREATE TABLE IF NOT EXISTS tasks.agent_proposals (
    token        TEXT PRIMARY KEY,
    user_email   TEXT        NOT NULL,
    slug         TEXT        NOT NULL,
    description  TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    used_at      TIMESTAMPTZ
);

-- Proposals are always looked up by token, and swept by age.
CREATE INDEX IF NOT EXISTS agent_proposals_created_idx
    ON tasks.agent_proposals (created_at);
```

- [ ] **Step 2: Write the failing tests**

Create `mcp-servers/tasks/tests/test_code_proposals.py`:

```python
"""A proposal is a promise that nothing has happened yet.

These use the db_session fixture, so they run in the container and error at
setup locally where there is no Postgres. That is expected: see CLAUDE.md.
"""
import pytest

from code_proposals import (
    PROPOSAL_TTL_SECONDS,
    ProposalError,
    consume_proposal,
    create_proposal,
)

OWNER = "proposals-test-owner@example.com"
STRANGER = "proposals-test-stranger@example.com"


def test_the_ttl_is_thirty_minutes():
    assert PROPOSAL_TTL_SECONDS == 1800


async def test_a_proposal_round_trips(db_session):
    token = await create_proposal(OWNER, "shop", "make the button blue")
    got = await consume_proposal(OWNER, token)
    assert got["slug"] == "shop"
    assert got["description"] == "make the button blue"


async def test_a_token_is_single_use(db_session):
    token = await create_proposal(OWNER, "shop", "make the button blue")
    await consume_proposal(OWNER, token)
    with pytest.raises(ProposalError):
        await consume_proposal(OWNER, token)


async def test_a_stranger_cannot_consume_it(db_session):
    token = await create_proposal(OWNER, "shop", "make the button blue")
    with pytest.raises(ProposalError):
        await consume_proposal(STRANGER, token)
    # And it is still there for its owner, so a stranger's attempt cannot
    # be used to burn somebody else's token.
    assert (await consume_proposal(OWNER, token))["slug"] == "shop"


async def test_an_unknown_token_is_refused(db_session):
    with pytest.raises(ProposalError):
        await consume_proposal(OWNER, "not-a-real-token")


async def test_an_empty_token_is_refused(db_session):
    with pytest.raises(ProposalError):
        await consume_proposal(OWNER, "")


async def test_an_expired_token_is_refused(db_session):
    token = await create_proposal(OWNER, "shop", "make the button blue")
    await db_session.execute(text(
        "UPDATE tasks.agent_proposals"
        " SET created_at = now() - interval '31 minutes'"
        " WHERE token = :t"), {"t": token})
    await db_session.commit()
    with pytest.raises(ProposalError):
        await consume_proposal(OWNER, token)


async def test_tokens_are_not_guessable(db_session):
    tokens = {await create_proposal(OWNER, "shop", "x") for _ in range(5)}
    assert len(tokens) == 5
    assert all(len(t) >= 32 for t in tokens)
```

Add `from sqlalchemy import text` to that file's imports.

- [ ] **Step 3: Run the tests and watch them fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_code_proposals.py -q`
Expected locally: `ModuleNotFoundError: No module named 'code_proposals'`. After the module exists, the `db_session` tests will show `ERROR at setup` locally, which is the pre-existing no-local-Postgres condition, not a failure of this task.

- [ ] **Step 4: Write the module**

Create `mcp-servers/tasks/code_proposals.py`:

```python
"""The token that stands between an agent's idea and a real build.

Proposing writes a row and changes nothing. Applying consumes the row, and
that consumption is the single-use guarantee: the UPDATE that marks the row
used is the same statement that reads it, so two confirms arriving at once
cannot both come away with a proposal.

The slug is read back out of the row rather than taken from the caller, so
a token cannot be pointed at a different app after the fact.
"""
import logging
import secrets

from sqlalchemy import text

from db import session

logger = logging.getLogger(__name__)

#: Long enough that a proposal is still valid while somebody reads it and
#: replies, short enough that an abandoned one cannot be applied tomorrow.
PROPOSAL_TTL_SECONDS = 1800


class ProposalError(Exception):
    """Refused. `reason` is written to be shown to the person asking."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def create_proposal(user_email: str, slug: str, description: str) -> str:
    token = secrets.token_urlsafe(24)
    async with session() as s:
        await s.execute(
            text("INSERT INTO tasks.agent_proposals"
                 " (token, user_email, slug, description)"
                 " VALUES (:token, :email, :slug, :description)"),
            {"token": token, "email": user_email, "slug": slug,
             "description": description},
        )
        await s.commit()
    return token


async def consume_proposal(user_email: str, token: str) -> dict:
    """Mark a proposal used and return what it asked for.

    Every refusal says the same thing. Telling the difference between "no
    such token" and "that is not yours" would let somebody map which
    tokens exist.
    """
    if not isinstance(token, str) or not token.strip():
        raise ProposalError("that approval code is not usable")

    async with session() as s:
        row = (await s.execute(
            text("UPDATE tasks.agent_proposals"
                 "   SET used_at = now()"
                 " WHERE token = :token"
                 "   AND user_email = :email"
                 "   AND used_at IS NULL"
                 "   AND created_at > now() - make_interval(secs => :ttl)"
                 " RETURNING slug, description"),
            {"token": token.strip(), "email": user_email,
             "ttl": PROPOSAL_TTL_SECONDS},
        )).first()
        await s.commit()

    if row is None:
        raise ProposalError("that approval code is not usable")
    return {"slug": row[0], "description": row[1]}
```

`from db import session` is correct and is what `routes_agent_turn.py:33` and `routes_projects.py:31` both use.

- [ ] **Step 5: Apply the migration and run the tests in the container**

```bash
scp mcp-servers/tasks/migrations/045_agent_proposals.sql root@46.224.193.25:/tmp/045.sql
ssh root@46.224.193.25 "docker exec -i postgres psql -U openwebui -d openwebui < /tmp/045.sql"
ssh root@46.224.193.25 "docker exec tasks sh -lc 'cd /app && python -m pytest tests/test_code_proposals.py -q'"
```
Expected: all pass in the container. The migration is idempotent, so running it twice is safe and worth doing once to prove it.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/migrations/045_agent_proposals.sql mcp-servers/tasks/code_proposals.py mcp-servers/tasks/tests/test_code_proposals.py
git commit -m "A change an agent wants to make, waiting for the person to say yes"
```

---

### Task 4: The internal HTTP surface

**Files:**
- Create: `mcp-servers/tasks/routes_code.py`
- Modify: `mcp-servers/tasks/main.py` (imports near line 11, `include_router` near line 131)
- Test: `mcp-servers/tasks/tests/test_routes_code.py`

**Interfaces:**
- Consumes: `app_code_access.{CodeAccessError, read_file, search_files, list_files}` (Tasks 1 and 2); `code_proposals.{ProposalError, create_proposal, consume_proposal}` (Task 3); `routes_gateway._require_internal`; `routes_projects._user_can_see_project`; `routes_aiuibuilder.{_validate_slug, _create_and_spawn_enhance}`; `db.session`.
- Produces: `router` with prefix `/code`, endpoints `GET /code/apps`, `GET /code/file`, `GET /code/search`, `POST /code/propose`, `POST /code/apply`.

**Note on an existing helper:** `_create_and_spawn_enhance(email, slug, prompt)` returns `(task_id, slug)` and already raises 404 when there is no app, 403 when the caller is not editor or owner, and 409 when an enhancement is in flight. Do not re-implement any of those checks. Let its exceptions propagate.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_routes_code.py`:

```python
"""The code endpoints, and the checks they must never skip.

Membership is the one that matters: the caller supplies a slug, so the
service has to decide whether that slug is theirs on every single call
rather than trusting an earlier answer.
"""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import routes_code

SECRET = "test-internal-secret"
OWNER = "code-routes-owner@example.com"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("INTERNAL_CALLBACK_SECRET", SECRET)
    monkeypatch.setattr(routes_code, "_apps_root_override", tmp_path, raising=False)

    app = FastAPI()
    app.include_router(routes_code.router)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://t")


def _app_on_disk(tmp_path, slug="shop"):
    d = tmp_path / slug
    d.mkdir(parents=True)
    (d / "index.html").write_text("<h1>Shop</h1>\n", encoding="utf-8")
    return d


async def test_the_secret_is_required(client):
    r = await client.get("/code/apps", params={"user_email": OWNER})
    assert r.status_code == 403


async def test_a_non_member_cannot_read_a_file(client, monkeypatch, tmp_path):
    _app_on_disk(tmp_path)

    async def _no(*_args, **_kwargs):
        return False
    monkeypatch.setattr(routes_code, "_can_see", _no)

    r = await client.get("/code/file",
                         params={"user_email": OWNER, "slug": "shop",
                                 "path": "index.html"},
                         headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 403


async def test_a_member_reads_their_own_file(client, monkeypatch, tmp_path):
    _app_on_disk(tmp_path)

    async def _yes(*_args, **_kwargs):
        return True
    monkeypatch.setattr(routes_code, "_can_see", _yes)

    r = await client.get("/code/file",
                         params={"user_email": OWNER, "slug": "shop",
                                 "path": "index.html"},
                         headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 200
    assert "Shop" in r.json()["text"]


async def test_a_refused_path_is_a_clean_400_not_a_stack_trace(client, monkeypatch, tmp_path):
    _app_on_disk(tmp_path)

    async def _yes(*_args, **_kwargs):
        return True
    monkeypatch.setattr(routes_code, "_can_see", _yes)

    r = await client.get("/code/file",
                         params={"user_email": OWNER, "slug": "shop",
                                 "path": "../secret.txt"},
                         headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 400
    assert "not inside this app" in r.json()["detail"]


async def test_apply_never_takes_the_slug_from_the_caller(client, monkeypatch):
    """The slug comes out of the stored proposal. A caller that sends one
    must not be able to steer the build with it."""
    seen = {}

    async def _consume(email, token):
        return {"slug": "from-the-proposal", "description": "make it blue"}

    async def _spawn(email, slug, prompt):
        seen["slug"] = slug
        seen["prompt"] = prompt
        return ("task-1", slug)

    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    r = await client.post("/code/apply",
                          json={"user_email": OWNER, "token": "t",
                                "slug": "attacker-supplied"},
                          headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 200
    assert seen["slug"] == "from-the-proposal"


async def test_apply_with_a_bad_token_starts_nothing(client, monkeypatch):
    from code_proposals import ProposalError

    async def _consume(email, token):
        raise ProposalError("that approval code is not usable")

    started = []

    async def _spawn(email, slug, prompt):
        started.append(slug)
        return ("task-1", slug)

    monkeypatch.setattr(routes_code, "consume_proposal", _consume)
    monkeypatch.setattr(routes_code, "_spawn_enhance", _spawn)

    r = await client.post("/code/apply",
                          json={"user_email": OWNER, "token": "nope"},
                          headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 400
    assert started == []


async def test_propose_checks_membership_before_writing_a_token(client, monkeypatch):
    async def _no(*_args, **_kwargs):
        return False
    written = []

    async def _create(email, slug, description):
        written.append(slug)
        return "token"

    monkeypatch.setattr(routes_code, "_can_see", _no)
    monkeypatch.setattr(routes_code, "create_proposal", _create)

    r = await client.post("/code/propose",
                          json={"user_email": OWNER, "slug": "shop",
                                "description": "make it blue"},
                          headers={"X-Internal-Secret": SECRET})
    assert r.status_code == 403
    assert written == []
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_code.py -q`
Expected: `ModuleNotFoundError: No module named 'routes_code'`.

- [ ] **Step 3: Write the router**

Create `mcp-servers/tasks/routes_code.py`:

```python
"""A person's own app code, over HTTP, for the assistant's tool.

Internal only and mounted once, like every other endpoint that acts for a
named user. The caller names a slug, so membership is decided here on every
call and never inferred from an earlier one.

Reading is safe on its own. Changing is not, so it is two calls: propose
writes a token and touches nothing, and apply consumes that token and hands
the work to the ordinary App Builder enhance, which already smoke tests the
result and rolls the app back if it broke.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

import app_code_access
from app_code_access import CodeAccessError
from code_proposals import ProposalError, consume_proposal, create_proposal
from db import session
from routes_gateway import _require_internal
from routes_projects import _user_can_see_project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/code")

#: Tests point this at a tmp_path. Production leaves it None so
#: app_code_access uses CLAUDE_WORKSPACE.
_apps_root_override: Path | None = None


async def _can_see(user_email: str, slug: str) -> bool:
    """Membership, per call. A seam so tests can drive the endpoints
    without a database."""
    async with session() as s:
        return await _user_can_see_project(s, slug, user_email)


async def _spawn_enhance(user_email: str, slug: str, prompt: str):
    """A seam over the builder, so a test can prove which slug was used
    without starting a real build. Imported lazily for the same reason
    _create_and_spawn_enhance imports its own dependencies lazily: the
    builder module pulls in the execution stack."""
    from routes_aiuibuilder import _create_and_spawn_enhance
    return await _create_and_spawn_enhance(user_email, slug, prompt)


async def _require_member(user_email: str, slug: str) -> None:
    if not await _can_see(user_email, slug):
        raise HTTPException(status_code=403, detail="That is not your app.")


class ProposeIn(BaseModel):
    user_email: str
    slug: str
    description: str


class ApplyIn(BaseModel):
    user_email: str
    token: str
    # Accepted and ignored on purpose: a caller may send it, and the slug
    # that gets built is always the one stored with the proposal.
    slug: str | None = None


@router.get("/apps")
async def list_apps(user_email: str,
                    x_internal_secret: str = Header(default="")) -> dict:
    """The apps this person can see, newest change first."""
    _require_internal(x_internal_secret)
    async with session() as s:
        rows = (await s.execute(
            text("SELECT DISTINCT slug FROM tasks.project_members"
                 " WHERE user_email = :email ORDER BY slug"),
            {"email": user_email},
        )).all()
    return {"apps": [r[0] for r in rows]}


@router.get("/file")
async def read_one_file(user_email: str, slug: str, path: str,
                        x_internal_secret: str = Header(default="")) -> dict:
    _require_internal(x_internal_secret)
    await _require_member(user_email, slug)
    try:
        text_out = app_code_access.read_file(
            slug, path, apps_root=_apps_root_override)
    except CodeAccessError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc
    return {"slug": slug, "path": path, "text": text_out}


@router.get("/search")
async def search_one_app(user_email: str, slug: str, query: str,
                         x_internal_secret: str = Header(default="")) -> dict:
    _require_internal(x_internal_secret)
    await _require_member(user_email, slug)
    try:
        hits = app_code_access.search_files(
            slug, query, apps_root=_apps_root_override)
    except CodeAccessError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc
    return {"slug": slug, "matches": hits}


@router.post("/propose")
async def propose(body: ProposeIn,
                  x_internal_secret: str = Header(default="")) -> dict:
    """Write down what would change. Nothing happens yet."""
    _require_internal(x_internal_secret)
    await _require_member(body.user_email, body.slug)
    if not body.description.strip():
        raise HTTPException(status_code=400,
                            detail="There was no change to propose.")
    token = await create_proposal(body.user_email, body.slug,
                                  body.description.strip())
    return {"token": token, "slug": body.slug,
            "description": body.description.strip()}


@router.post("/apply")
async def apply(body: ApplyIn,
                x_internal_secret: str = Header(default="")) -> dict:
    """Do the thing the person just approved, and nothing else."""
    _require_internal(x_internal_secret)
    try:
        proposal = await consume_proposal(body.user_email, body.token)
    except ProposalError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc

    # The slug is the proposal's, never the caller's. _create_and_spawn_enhance
    # does the editor-or-owner check, the per-slug lock and the 409, so those
    # are deliberately not repeated here.
    task_id, slug = await _spawn_enhance(
        body.user_email, proposal["slug"], proposal["description"])
    return {"task_id": task_id, "slug": slug,
            "description": proposal["description"]}
```

Add `from sqlalchemy import text` to the imports of that file.

- [ ] **Step 4: Mount it**

In `mcp-servers/tasks/main.py`, beside the existing internal routers:

```python
from routes_code import router as code_router
```

and next to line 131's `app.include_router(account_router)`:

```python
app.include_router(code_router)  # /code, internal only (X-Internal-Secret)
```

Mount it **once**. `routes_agent_turn` and `routes_account` are both mounted once and this must match: a second mount under `/api/tasks` would put an internal-only surface on a publicly routed prefix.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_routes_code.py -q`
Expected: all pass.

Then confirm the mount does not shadow anything:
```bash
cd mcp-servers/tasks && python -c "import main; print([r.path for r in main.app.routes if str(r.path).startswith('/code')])"
```
Expected: the five `/code/...` paths, each listed once.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/routes_code.py mcp-servers/tasks/main.py mcp-servers/tasks/tests/test_routes_code.py
git commit -m "Serve a person's own app code, and gate every change behind their yes"
```

---

### Task 5: The tool, and its read classification

**Files:**
- Create: `open-webui-functions/code_tool.py`
- Modify: `mcp-servers/tasks/agent_tools.py` (`READ_METHODS`)
- Test: `mcp-servers/tasks/tests/test_code_tool.py`

**Interfaces:**
- Consumes: the five endpoints from Task 4.
- Produces: an Open WebUI tool with id `code` exposing `list_my_apps`, `read_app_file`, `search_my_app`, `propose_app_change`, `apply_app_change`.

**Why `agent_tools.py` changes:** `is_write_tool` treats any name containing a mutating verb as a write, and "change" is in `_WRITE_VERBS`. Verified against the real classifier: `propose_app_change` currently classifies as a **write**, which would stop a Read only agent from proposing and contradict the spec. `READ_METHODS` exists for exactly this ("pin the specific read method in READ_METHODS instead"). `apply_app_change` must stay a write.

- [ ] **Step 1: Write the failing tests**

Create `mcp-servers/tasks/tests/test_code_tool.py`:

```python
"""What the code tool is allowed to do without being asked twice.

The classifier decides what an unattended agent may run, so its answer for
these five names is a security decision, not a naming detail.
"""
import os
import re

from agent_tools import READ_METHODS, is_write_tool

TOOL = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                    "open-webui-functions", "code_tool.py")


def _source():
    with open(TOOL, encoding="utf-8") as fh:
        return fh.read()


def test_reading_is_never_a_write():
    for name in ("list_my_apps", "read_app_file", "search_my_app"):
        assert is_write_tool(name) is False, name


def test_proposing_is_not_a_write():
    """It writes a token row and changes nothing an app owner would
    notice. A Read only agent must be able to say what it would change."""
    assert is_write_tool("propose_app_change") is False
    assert "propose_app_change" in READ_METHODS


def test_applying_is_a_write():
    """The one call that can start a build. If this ever reads as a read,
    an unattended Read only agent could change a live app."""
    assert is_write_tool("apply_app_change") is True
    assert "apply_app_change" not in READ_METHODS


def test_the_tool_exposes_exactly_the_five_functions():
    source = _source()
    found = set(re.findall(r"async def (\w+)\(self", source))
    assert found == {"list_my_apps", "read_app_file", "search_my_app",
                     "propose_app_change", "apply_app_change"}


def test_the_tool_holds_no_routing_or_path_logic():
    """Every decision belongs to the service, so the same rules apply in
    Discord and Telegram. A path check here would be a second, divergent
    copy of the one in app_code_access."""
    source = _source()
    assert "resolve" not in source
    assert ".." not in source.replace("...", "")


def test_the_tool_never_deletes():
    source = _source().lower()
    for word in ("delete", "unlink", "rmtree", "remove"):
        assert word not in source, word


def test_apply_takes_only_a_token():
    """A slug argument here would invite the model to pick the app at
    confirm time, which is exactly what the stored proposal prevents."""
    source = _source()
    match = re.search(r"async def apply_app_change\(([^)]*)\)", source)
    assert match
    assert "slug" not in match.group(1)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_code_tool.py -q`
Expected: `test_proposing_is_not_a_write` fails (it classifies as a write today), and the file-reading tests fail with `FileNotFoundError`.

- [ ] **Step 3: Pin the read method**

In `mcp-servers/tasks/agent_tools.py`, inside `READ_METHODS`, add:

```python
    # Pinned against the verb rule rather than with it: "change" is a write
    # verb, and this call contains one while changing nothing. It records
    # what an agent WOULD do and hands back a code the person has to
    # approve. Refusing it for a read only agent would mean such an agent
    # could not even tell you what it would change.
    "propose_app_change",
```

Update the comment above `READ_METHODS` that currently claims "The verb rule already agrees with every one of these", since this entry is the first that overrides it:

```python
#: The native tools, pinned by name. The verb rule agrees with all of these
#: but propose_app_change, which is pinned deliberately against it; see the
#: note beside that entry. Written out so that renaming a method has to
#: break a test rather than silently change what an unattended agent may do.
```

- [ ] **Step 4: Write the tool**

Create `open-webui-functions/code_tool.py`:

```python
"""
title: Your Code
author: Ralph Benitez
version: 1.0.0
description: Lets an agent read the apps you built here, and change one after you approve exactly what it would do.
requirements: httpx
"""
# Holds no logic on purpose, the same as agents_tool.py and account_tool.py:
# the tasks service decides membership, which paths are readable, and
# whether an approval code is still good. Keeping those decisions in one
# place is what makes the web chat, Discord and Telegram behave the same,
# and it is what makes an agent's access level apply here too.
import os

import httpx
from pydantic import BaseModel, Field

#: How a refusal reads when the service declined. The service writes the
#: reason; this is only the wrapper around it.
REFUSED = "That was not allowed: "


class Tools:
    class Valves(BaseModel):
        tasks_url: str = Field(default=os.environ.get("TASKS_URL", "http://tasks:8210"))
        internal_secret: str = Field(
            default=os.environ.get("INTERNAL_CALLBACK_SECRET", ""))
        timeout_seconds: int = Field(default=60)

    def __init__(self):
        self.valves = self.Valves()

    async def _call(self, method: str, path: str, **kwargs) -> dict:
        url = self.valves.tasks_url.rstrip("/") + path
        headers = {"X-Internal-Secret": self.valves.internal_secret}
        async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as c:
            if method == "GET":
                r = await c.get(url, headers=headers, params=kwargs)
            else:
                r = await c.post(url, headers=headers, json=kwargs)
            if r.status_code >= 400:
                body = {}
                try:
                    body = r.json()
                except ValueError:
                    pass
                detail = body.get("detail") if isinstance(body, dict) else None
                raise RuntimeError(detail or ("the service returned "
                                              + str(r.status_code)))
            data = r.json()
            return data if isinstance(data, dict) else {}

    def _email(self, user) -> str:
        email = (user or {}).get("email") or ""
        if not email:
            raise RuntimeError("I could not tell whose account this is.")
        return email

    async def list_my_apps(self, __user__: dict = {}) -> str:
        """
        List the apps this person built on this platform. Call this first
        when they ask about "my site", "my app" or a page of theirs, so you
        know which slug to use for the other calls.
        """
        try:
            data = await self._call("GET", "/code/apps",
                                    user_email=self._email(__user__))
        except RuntimeError as exc:
            return REFUSED + str(exc)
        apps = data.get("apps") or []
        if not apps:
            return "This person has not built any apps here yet."
        return "Their apps: " + ", ".join(apps)

    async def read_app_file(self, slug: str, path: str,
                            __user__: dict = {}) -> str:
        """
        Read one file from one of this person's apps. `slug` is the app,
        `path` is relative to the app, for example "src/Checkout.tsx". Use
        search_my_app first if you do not already know the path.
        """
        try:
            data = await self._call("GET", "/code/file",
                                    user_email=self._email(__user__),
                                    slug=slug, path=path)
        except RuntimeError as exc:
            return REFUSED + str(exc)
        return slug + "/" + path + ":\n\n" + (data.get("text") or "")

    async def search_my_app(self, slug: str, query: str,
                            __user__: dict = {}) -> str:
        """
        Find where some text appears in one of this person's apps. Use this
        to locate a page or a component before reading it, rather than
        guessing a filename.
        """
        try:
            data = await self._call("GET", "/code/search",
                                    user_email=self._email(__user__),
                                    slug=slug, query=query)
        except RuntimeError as exc:
            return REFUSED + str(exc)
        matches = data.get("matches") or []
        if not matches:
            return "Nothing in " + slug + " matches that."
        lines = [m.get("path", "") + ":" + str(m.get("line", "")) + "  "
                 + (m.get("text") or "") for m in matches]
        return "Matches in " + slug + ":\n" + "\n".join(lines)

    async def propose_app_change(self, slug: str, description: str,
                                 __user__: dict = {}) -> str:
        """
        Describe a change you want to make to one of this person's apps.
        This changes NOTHING. It returns an approval code.

        Say plainly what you would change and which file, then show the
        person the approval code and ask them to confirm. Only call
        apply_app_change once they have said yes in their own words.
        """
        try:
            data = await self._call("POST", "/code/propose",
                                    user_email=self._email(__user__),
                                    slug=slug, description=description)
        except RuntimeError as exc:
            return REFUSED + str(exc)
        return ("Nothing has changed yet. Ask them to confirm this, then "
                "call apply_app_change with the code.\n"
                "App: " + slug + "\nChange: " + (data.get("description") or "")
                + "\nApproval code: " + (data.get("token") or ""))

    async def apply_app_change(self, token: str, __user__: dict = {}) -> str:
        """
        Carry out a change the person has just approved, using the approval
        code from propose_app_change. Only call this after they have
        actually agreed. The code works once.
        """
        try:
            data = await self._call("POST", "/code/apply",
                                    user_email=self._email(__user__),
                                    token=token)
        except RuntimeError as exc:
            return REFUSED + str(exc)
        return ("Started. " + (data.get("slug") or "The app")
                + " is being changed: " + (data.get("description") or "")
                + ". It is smoke tested afterwards and rolled back "
                  "automatically if it breaks.")
```

- [ ] **Step 5: Run the tests and watch them pass**

Run: `cd mcp-servers/tasks && python -m pytest tests/test_code_tool.py -q`
Expected: all pass.

Then run the classifier's own suite, since `READ_METHODS` changed:
`cd mcp-servers/tasks && python -m pytest tests/ -q -k "agent_tools or write_tool"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add open-webui-functions/code_tool.py mcp-servers/tasks/agent_tools.py mcp-servers/tasks/tests/test_code_tool.py
git commit -m "Give an agent your code to read, and an approval code before it changes anything"
```

---

### Task 6: Deploy and verify on the server

Wiring inside a function body is not caught by an import or a unit test, and this pipeline has been bitten by exactly that twice. Nothing in this task is optional.

**Files:** none changed. This task produces evidence.

- [ ] **Step 1: Deploy tasks**

```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```
If `rsync` is unavailable (Git Bash on Windows), fall back to one `scp` per changed file, rebuild `tasks`, and update `.deploy-state` by hand. `.deploy-state` is JSON (`{"sha": ..., "deployed_at": ..., "deployed_by": ...}`); writing a bare SHA breaks the next deploy.

Note the SSH link to this host has been intermittently dropping connections. Wrap each `ssh` in a retry, and prefer one `scp` of a gzipped file over many chunked `ssh` appends.

- [ ] **Step 2: Confirm the endpoints exist and are not public**

```bash
ssh root@46.224.193.25 "curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8210/code/apps?user_email=x"
```
Expected: `403` without the secret.

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://ai-ui.coolestdomain.win/code/apps
```
Expected: NOT 200. The router is mounted once and internally only, so this must not be routed publicly.

- [ ] **Step 3: Install the tool, grant it, attach it**

```bash
# on the server, with a short-lived token, from the tasks container
python scripts/insert_owui_tool.py code code_tool.py "Your Code" \
    "Read the apps you built, and change one after you approve it."
python scripts/grant_tools_public.py code
TOOL_IDS=code python3 scripts/enable_gmail_tool_on_models.py
```
Expected from the first: `functions offered to the model: ['list_my_apps', 'read_app_file', 'search_my_app', 'propose_app_change', 'apply_app_change']`. An empty list means the tool is installed and invisible, which is a failure.

- [ ] **Step 4: Prove the read path against a real app**

Run the tool body directly in the open-webui container, the way `run_tool.py` already does for the agents tool, as a real user with a real app:

```bash
docker exec open-webui python /tmp/run_tool.py /tmp/code_tool.py list_my_apps <email>
docker exec open-webui python /tmp/run_tool.py /tmp/code_tool.py search_my_app <email> <slug> "button"
```
Expected: real slugs, real matches with file and line.

- [ ] **Step 5: Prove the refusals against the real filesystem**

```bash
docker exec open-webui python /tmp/run_tool.py /tmp/code_tool.py read_app_file <email> <slug> "../../etc/passwd"
docker exec open-webui python /tmp/run_tool.py /tmp/code_tool.py read_app_file <email> <slug> ".env"
```
Expected: a refusal sentence both times, and no file content. A test with `tmp_path` cannot prove this against the real workspace layout, which is why it is repeated here.

- [ ] **Step 6: Prove the two-phase confirm end to end**

Propose a small visible change to a throwaway app, confirm the approval code comes back, then apply it and watch the enhance run. Then apply the same code a second time.

Expected: the second apply is refused, and `docker exec tasks psql` shows one task row for that slug, not two.

- [ ] **Step 7: Browser smoke**

In a chat on gpt-5, hard reload first (the frontend only picks up newly installed tools on a fresh load, and the count beside the tools icon is the tell). Ask about a real app, and confirm the model reads a file and answers from it. Then ask for a change and confirm nothing happens until you say yes.

- [ ] **Step 8: Record the state**

Stamp `.deploy-state`, and note in `MEMORY.md` what was deployed and what was verified in the browser rather than only over HTTP.

---

## Self-Review

**Spec coverage.** Read surface: Tasks 1, 2, 4. Membership on every call: Task 4. Path containment by resolved real path, including the symlink case: Task 1. Denied filenames and folders: Task 1. Size, match and binary caps: Tasks 1 and 2. Two-phase token, single use, 30 minute TTL, slug from the stored proposal: Tasks 3 and 4. Apply routes through `_create_and_spawn_enhance` and inherits the guards: Task 4. Read only can propose and cannot apply: Task 5. No delete, no create: Task 5 asserts the absence. Deploy and browser verification: Task 6.

**One thing the spec asserted that the code contradicted.** The spec says a Read only agent can propose. `is_write_tool("propose_app_change")` returns `True` today because "change" is a write verb, so without Task 5's `READ_METHODS` pin the spec's promise would have been quietly false. Verified against the real classifier before writing this plan, not assumed.

**A limitation worth stating.** A Read only agent can propose but cannot apply its own proposal. The person applies it, which in the web chat means the outer model calls `apply_app_change` after they say yes. That is coherent, because the outer model acting on an explicit confirmation is the person acting, while the agent ceiling exists for unattended runs. It is worth saying out loud rather than discovering.

**Placeholder scan.** No TBD, no "handle errors appropriately", every code step carries the code.

**Type consistency.** `CodeAccessError.reason` is used by Task 4. `ProposalError.reason` likewise. `consume_proposal` returns `{"slug", "description"}` and Task 4 reads exactly those keys. `_create_and_spawn_enhance(email, slug, prompt)` returns `(task_id, slug)` and Task 4 unpacks two values. `search_files` returns `{"path", "line", "text"}` and both Task 4 and the tool read those three.
