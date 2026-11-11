"""GitHub branches and file writes, which both need a read first (2026-11-11).

The deferred half of #179. Those six tools were declarative because GitHub
takes an owner, a repository and a branch as plain strings. These two are
not, and the difference is the whole reason they were held back:

    create_branch   POST /git/refs needs the sha the new branch starts
                    from, and takes `ref` as the FULL ref, not the name
    write_file      PUT /contents/{path} takes the content base64 encoded,
                    and needs the existing blob's sha to UPDATE rather
                    than to create

Each of those is a guess if it is not read, and GitHub answers a guess with
a 422 or a 409 that tells the model nothing useful. So they are read, as
the person, from GitHub's own answers.

Three mistakes this exists to make impossible, all of them easy:

  - Sending the bare branch name as `ref`. GitHub wants "refs/heads/name"
    and answers 422 for the name alone.
  - Encoding content twice, which writes a file full of base64 text. That
    one LOOKS like it worked.
  - Reading a file's sha off the default branch and writing it to a feature
    branch, which is a 409. The read carries the same ref as the write.

Pure apart from `prepare`, which is handed a `get(path, params)` that reads
GitHub as the person and returns the parsed JSON or None.
"""
import base64
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

_HEADS = "refs/heads/"

#: The tools that need a read before the call. Everything else on this
#: provider is declarative and must not pay for a lookup it has no use for.
NEEDS_A_READ = ("create_branch", "write_file")


def full_ref(branch: Any) -> str:
    """"my-branch" -> "refs/heads/my-branch", idempotently.

    A model that has read GitHub's reference may well send the full ref
    already, and prefixing it twice is a 422 nobody could read back.
    """
    said = str(branch or "").strip()
    if said.startswith(_HEADS):
        return said
    return _HEADS + said.lstrip("/")


def encoded(text: Any, already: bool = False) -> str:
    """The content as GitHub's contents API wants it: base64 of UTF-8."""
    if already:
        return str(text or "")
    raw = str(text if text is not None else "")
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def sha_of(payload: Any) -> Optional[str]:
    """The blob sha from a GET /contents answer, or None.

    None covers both "the file is not there", which `get` reports as None
    after a 404 and is the ordinary new-file case, and "that path is a
    FOLDER", which GitHub answers with a LIST. Taking a sha off the list
    would send some other file's sha and update the wrong file.
    """
    if not isinstance(payload, dict):
        return None
    sha = payload.get("sha")
    return str(sha) if sha else None


Get = Callable[[str, Optional[Dict[str, Any]]], Awaitable[Any]]


async def prepare(
    tool_name: str, args: Dict[str, Any], get: Get,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """The arguments GitHub should receive, or a reason to send nothing.

    Reads nothing at all for the other GitHub tools, which is why the
    tool name is checked before anything else happens.
    """
    args = dict(args or {})
    if tool_name not in NEEDS_A_READ:
        return args, None

    owner = str(args.get("owner") or "")
    repo = str(args.get("repo") or "")
    where = "/repos/%s/%s" % (owner, repo)

    if tool_name == "create_branch":
        base = str(args.get("base") or "").strip()
        if not base:
            row = await get(where, None)
            base = str((row or {}).get("default_branch") or "") \
                if isinstance(row, dict) else ""
            if not base:
                return args, (
                    "Could not read %s/%s to find its default branch. Say "
                    "which branch to start from." % (owner, repo))
        ref = await get(where + "/git/ref/heads/" + base, None)
        sha = ((ref or {}).get("object") or {}).get("sha") \
            if isinstance(ref, dict) else None
        if not sha:
            return args, (
                "There is no branch called %r in %s/%s, so there is nothing "
                "to branch from." % (base, owner, repo))
        args["ref"] = full_ref(args.get("branch"))
        args["sha"] = str(sha)
        return args, None

    # write_file. A missing sha CREATES the file, which is correct, so a
    # failed read is not an error here: it is the new-file case.
    branch = str(args.get("branch") or "").strip()
    existing = await get(where + "/contents/" + str(args.get("path") or ""),
                         {"ref": branch} if branch else None)
    sha = sha_of(existing)
    if sha:
        args["sha"] = sha
    args["content"] = encoded(args.get("content"))
    return args, None
