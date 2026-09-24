"""What a build did, read back out of the transcript it already stored.

Every build writes its Claude Code stream-json into tasks.executions.log. As
of 2026-09-24 that is 281 transcripts, 20MB, back to 2026-04-28, and nothing
reads any of it. The last line is a `result` record carrying what the build
cost, why it stopped and which models answered; the body carries every file it
wrote.

Nobody knew builds had cost $79.92, or that $44.16 of it went on building junk
apps out of a request for a daily quote (see
scheduler._run_scheduled_task). The money was in these files the whole time.

Deterministic on purpose: a regex over a known shape, never a model. It is
cheaper, and it cannot invent a number that was never in the transcript. Five
months of output from a CLI that changes between releases means anything
unparseable has to read as absent rather than raise, so a caller asking about
a two-month-old build gets what survived rather than an exception.
"""
from __future__ import annotations

import re

#: The authoritative total for a build, and NOT the last costUSD in
#: modelUsage. Claude Code titles the session with Haiku and does the work
#: with Sonnet, so the last costUSD is the Sonnet share alone: across the 281
#: real transcripts that reads $75.30 against the true $79.92.
_COST = re.compile(r'"total_cost_usd":([0-9.]+)')

_TERMINAL = re.compile(r'"terminal_reason":"([a-z_]+)"')

#: Every model that billed for this build, in the order they appear.
#: Keyed off modelUsage rather than a field inside an entry: the fields there
#: are release-specific (inputTokens today) while the shape "name":{ is not,
#: and a model name is the only key in that object whose value is an object.
_MODEL_USAGE = re.compile(r'"modelUsage":\{')
_MODEL = re.compile(r'"([A-Za-z0-9][\w.:-]*)":\s*\{')

#: A ceiling on the brace scan below, not the bound itself. Only stops a
#: truncated transcript, whose modelUsage never closes, from walking 20MB.
_MODEL_USAGE_CHARS = 4000


def _model_usage_block(text: str) -> str:
    """The inside of "modelUsage":{...}, or "".

    Scanned to its closing brace rather than read as a fixed window. A window
    runs off the end of the object into whatever the result line carries
    next, which differs by Claude Code release: over the 281 real transcripts
    a 2000-character window reported `tool_input` as a model.
    """
    start = _MODEL_USAGE.search(text)
    if not start:
        return ""
    depth = 1
    for i, ch in enumerate(text[start.end():start.end() + _MODEL_USAGE_CHARS]):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start.end():start.end() + i]
    return ""

#: A Write or an Edit names its target in the same field. The path is the
#: build host's working directory, so only the part inside the app is kept.
_WROTE = re.compile(r'"name":"(?:Write|Edit)","input":\{"file_path":"([^"]+)"')

_IN_APP = re.compile(r"/apps/[^/]+/(.+)$")


def _relative(path: str) -> str:
    """The file as the owner would name it, or the whole path if it does not
    sit under apps/<slug>/. Backslashes never appear: the build host is
    Linux."""
    found = _IN_APP.search(path)
    return found.group(1) if found else path.rsplit("/", 1)[-1]


def facts_from(log) -> dict:
    """{cost_usd, terminal_reason, models, files} for one build transcript.

    Every value is absent rather than wrong when the transcript does not
    carry it: a killed build has no result record but did write files, and
    the caller wants those.
    """
    text = log if isinstance(log, str) else ""

    cost = _COST.search(text)
    stopped = _TERMINAL.search(text)

    # Ordered, de-duplicated. A build writes index.html, reads it back and
    # edits it again; naming it three times says nothing the first does not.
    files: list[str] = []
    for raw in _WROTE.findall(text):
        name = _relative(raw)
        if name and name not in files:
            files.append(name)

    models: list[str] = []
    for name in _MODEL.findall(_model_usage_block(text)):
        if name not in models:
            models.append(name)

    return {
        "cost_usd": float(cost.group(1)) if cost else None,
        "terminal_reason": stopped.group(1) if stopped else "",
        "models": models,
        "files": files,
    }
