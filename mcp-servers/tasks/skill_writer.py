"""Writing a skill for somebody who needs one (2026-11-03).

The second half of
docs/superpowers/specs/2026-09-09-agent-skill-writer-design.md. The first
half, user_skills.py, gave a person somewhere to keep their own skills.
This is what fills one in: they describe a job in a sentence and a model
writes the SKILL.md.

Everything here is a decision about the prompt or about reading the answer,
and all of it is pure, so it is tested without a model. The one network
call lives in the route.

**It saves nothing.** The endpoint returns a draft. Saving is a separate,
deliberate act, for the same reason making an agent shows the brief first:
a model that writes instructions which then go into every one of an agent's
turns must not be able to install them unseen.

Three things go in the prompt, and the design names why each one:

1. **The tools this person actually has**, by id and label. A skill that
   names Gmail for somebody who has not connected Gmail is the
   silent-failure case: it looks right, it saves, and the agent quietly
   cannot do the thing.
2. **The format, with the size ceiling as a number.** The public skills
   that could not be used here were mostly too large or written for an
   agent with a filesystem. Saying "under 4000 characters" produces a
   skill that fits; saying "be concise" does not.
3. **The house rules that made the shipped ones work**: steps then rules,
   one job per skill, never invent a fact, say when something could not be
   checked, answer and stop.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("skill_writer")

#: What the model is asked to stay under. Passed to the prompt as a number
#: and enforced again on save by user_skills, because a model asked for
#: 4000 characters will sometimes write 4300.
MAX_JOB_CHARS = 400

#: The frontmatter keys this platform reads. `allowed-tools` is a real field
#: in the Agent Skills format and carries what it says: the tools the skill
#: needs.
FRONT_KEYS = ("name", "description", "allowed-tools")

HOUSE_RULES = """House rules, which are what make the built-in skills work:
- One job per skill. A skill that does three things is three skills.
- Steps first, then rules. Numbered steps the agent follows in order, then
  any rules about what not to do.
- Never invent a fact. If something cannot be checked, say so in the answer
  rather than guessing.
- Answer and stop. No "let me know if you'd like", no offers of more work.
- Write for an agent that has a few REST tools and no filesystem. It cannot
  read files, run commands or browse. Everything it needs must be in the
  instructions or reachable through a tool listed above."""


#: How a per-user app tool is labelled, so the model can tell it from the
#: shared connector that carries the same vendor's name.
OWN_ACCOUNT = "%s, your own account"


def with_connected_apps(tools: dict, apps: dict) -> dict:
    """`tools` with the proxy umbrella expanded into the apps this person
    actually connected, so a drafted skill can NAME one.

    `routes_agents.tools_for_email` lists every connected app as a single
    entry, `server:mcp-proxy (Your connected apps)`. That is right where it
    came from, the agent form, where it is one checkbox meaning "all my
    apps". It is wrong here, because a skill is PROSE and has to name the
    tool it uses.

    Measured 2026-11-11, on the writer's first real use: asked for a skill
    whose whole job was writing a Trello card, by somebody with Trello
    connected, it picked gmail, calendar, documents, gdrive, remember and
    the umbrella. No Trello id was on the list to pick, so its answer was
    correct for what it was shown. The same shape as #177 one layer up.

    The umbrella is KEPT. An agent still needs it ticked to reach any of
    these, so a skill naming `my-trello` without it would name a tool the
    agent cannot actually be given.

    Returns a NEW dict. Hand the result to BOTH `prompt_for` and
    `user_skills.tool_warning`: expanding it for the prompt alone would
    produce a skill that warns about the very tool it was told to use.
    """
    out = dict(tools or {})
    for app_id, label in sorted((apps or {}).items()):
        pid = str(app_id or "").strip()
        if not pid:
            continue
        key = "my-" + pid
        if key in out:
            continue
        said = str(label or "").strip() or pid
        out[key] = OWN_ACCOUNT % said
    return out


def prompt_for(job: str, tools: dict, max_body_chars: int) -> list:
    """The messages that ask for one SKILL.md.

    `tools` is id -> label, exactly as the connections page has it, so the
    model names tools that exist for THIS person rather than tools that
    exist in general.
    """
    job = " ".join(str(job or "").split())[:MAX_JOB_CHARS]
    if tools:
        have = "\n".join("- %s (%s)" % (tid, label)
                         for tid, label in sorted(tools.items()))
        tool_line = ("The tools this person has connected, by id:\n" + have +
                     "\n\nList in allowed-tools only ids from that list. If "
                     "the job needs something they have not connected, write "
                     "the skill without it and say in the instructions what "
                     "cannot be done yet.")
    else:
        tool_line = ("This person has connected no tools, so allowed-tools "
                     "is empty and the instructions must not depend on one.")

    return [
        {"role": "system",
         "content":
             "You write one SKILL.md for an AI agent on this platform.\n\n"
             "Answer with the file and nothing else. No preamble, no code "
             "fence, no explanation after it.\n\n"
             "The shape:\n"
             "---\n"
             "name: a-short-hyphenated-name\n"
             "description: what it is for AND when to use it, one sentence\n"
             "allowed-tools: [tool-id, tool-id]\n"
             "---\n"
             "The instructions.\n\n"
             "The instructions must be under %d characters, because the "
             "whole file is pasted into the agent's prompt on every single "
             "message.\n\n%s\n\n%s"
             % (max_body_chars, tool_line, HOUSE_RULES)},
        {"role": "user",
         "content": "Write a skill for this job: " + job},
    ]


def _strip_fence(text: str) -> str:
    """A model told not to use a code fence sometimes uses one anyway.

    Stripping it is not being permissive about the format, it is refusing to
    fail on the one deviation that costs nothing to accept and is otherwise
    a perfectly good skill thrown away.
    """
    out = str(text or "").strip()
    if out.startswith("```"):
        out = re.sub(r"^```[a-zA-Z]*\n?", "", out)
        out = re.sub(r"\n?```\s*$", "", out)
    return out.strip()


def _tools_from(value: str) -> list:
    """`allowed-tools` as a list, however it was written.

    The format's own examples use a YAML list; models write
    `[a, b]`, `a, b` and `- a` on separate lines. All three mean the same
    thing and none is worth refusing a draft over.
    """
    raw = str(value or "").strip().strip("[]")
    parts = re.split(r"[,\n]", raw)
    out = []
    for part in parts:
        tool = part.strip().strip("-").strip().strip("'\"")
        if tool and tool not in out:
            out.append(tool)
    return out


def _list_below(lines: list, start: int) -> str:
    """The `- item` lines under a key that had no value on its own line."""
    found = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("-"):
            break
        found.append(stripped.lstrip("-").strip())
    return ", ".join(found)


def parse_draft(text: str) -> dict:
    """A model's answer as {name, description, tools, body}.

    Never raises. A draft that cannot be read is an empty draft, which the
    route reports as "try saying it differently"; an exception here would be
    a 500 for a model having a bad day.

    The frontmatter is read with a small parser rather than YAML on purpose:
    this is one model's answer in a known shape, and handing arbitrary text
    to a YAML loader to extract three keys is a larger surface than the job
    needs.
    """
    out = {"name": "", "description": "", "tools": [], "body": ""}
    raw = _strip_fence(text)
    if not raw:
        return out

    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            front, body = parts[1], parts[2]
            lines = front.splitlines()
            for i, line in enumerate(lines):
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key = key.strip().lower()
                if key not in FRONT_KEYS:
                    continue
                value = value.strip().strip("'\"")
                if key == "allowed-tools":
                    # A YAML list is as likely to arrive written DOWN the
                    # page as across it:
                    #
                    #     allowed-tools:
                    #       - gmail
                    #       - trello
                    #
                    # so an empty value is not an empty list, it is a list
                    # on the lines that follow.
                    if not value:
                        value = _list_below(lines, i)
                    out["tools"] = _tools_from(value)
                elif key == "name":
                    out["name"] = value
                else:
                    out["description"] = value
    out["body"] = body.strip()
    return out


def draft_problem(draft: dict) -> str:
    """Why this draft is not worth showing, or "".

    Deliberately thinner than user_skills.problem_with. A draft is allowed
    to be wrong, because the person reads it and can edit it; what it may
    not be is EMPTY, because there is nothing there to read or correct.
    """
    if not (draft.get("body") or "").strip():
        return ("I could not write that one. Try saying the job in a "
                "sentence, like: chase unpaid invoices every Monday.")
    if not (draft.get("name") or "").strip():
        return ("I wrote the instructions but not a usable name for them. "
                "Try saying the job in a sentence.")
    return ""
