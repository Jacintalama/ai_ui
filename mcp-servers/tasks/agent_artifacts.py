"""What a main chat reply has to carry, whatever the model wrote (2026-11-09).

A tool that starts a build or a video ends its result with a line the page
reads and the person never sees, because markdown consumes it:

    [aiui-artifact]: #build/528f5422-5dea-4c5a-8638-8e919a01109b

The model was told to copy that line into its reply. Nothing checked, and a
reply that left it out left the chat blind: it said "Building it now" and
then never said anything else. So the service puts back what the model
dropped, the same way `_with_connect_links` does for a Connect button.

Pure, so it can be tested without a turn.
"""
import re

#: The whole line and only the whole line. The same three kinds and the same
#: id shape as AIUI_ARTIFACT in integrations-ui.js, which is what reads it.
LINE = re.compile(r"^\[aiui-artifact\]: #(?:app|build|video)/"
                  r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}[ \t]*$", re.MULTILINE)


def declared_this_turn(convo) -> list[str]:
    """Each artifact line in this turn's tool results, in order, once.

    Only after the last user message, or every later reply in the chat would
    declare an old build again. Only tool results, because what the person
    typed and what the model wrote are not declarations.
    """
    messages = [m for m in (convo or []) if isinstance(m, dict)]
    start = 0
    for i, message in enumerate(messages):
        if message.get("role") == "user":
            start = i + 1
    found: list[str] = []
    for message in messages[start:]:
        content = message.get("content")
        if message.get("role") != "tool" or not isinstance(content, str):
            continue
        for match in LINE.finditer(content):
            line = match.group(0).strip()
            if line not in found:
                found.append(line)
    return found


def carried(answer: str, convo) -> str:
    """The answer with any line it should carry and does not.

    After a blank line, because a link reference definition cannot interrupt
    a paragraph: joined straight on, markdown prints it to the person. An
    empty answer stays empty, because the callers show the notes instead.
    """
    if not (answer or "").strip():
        return answer
    missing = [line for line in declared_this_turn(convo) if line not in answer]
    if not missing:
        return answer
    return answer.rstrip() + "\n\n" + "\n".join(missing)
