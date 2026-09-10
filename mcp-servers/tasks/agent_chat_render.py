"""HTML fragments for the agent chat panel.

Every function here returns ONE line with no newline in it. Several of these
fragments travel as SSE `data:`, where a newline is a field separator, so a
multi-line fragment arrives cut into pieces.

Server-rendered rather than assembled in the browser, following the Fusion
page: the panel then has no client-side model of the conversation that can
drift from the server's.
"""
import html


def esc(s: str) -> str:
    return html.escape(s or "")


def _initials(name: str) -> str:
    """The same two letters the agent's card shows.

    Ported from `initials` in static/agents.html rather than invented, so a
    person recognises the same mark in the panel that they picked from the
    cards. A one-letter mark here and a two-letter mark there read as two
    different agents.
    """
    parts = [p for p in str(name or "").strip().split() if p]
    if not parts:
        return "AI"
    if len(parts) == 1:
        return esc(parts[0][:2].upper())
    return esc((parts[0][0] + parts[-1][0]).upper())


def _hue(name: str) -> int:
    """Ported from `avatarHue` in static/agents.html, character for character.

    Every avatar being the same colour made two agents tell apart only by
    their letters. This must stay identical to the page's version or Ada is
    green on her card and some other colour two inches to the right.
    """
    h = 0
    for ch in str(name or ""):
        h = (h * 31 + ord(ch)) % 360
    return h


def _avatar(name: str) -> str:
    h = _hue(name)
    return (f'<div class="aav" style="background:linear-gradient(150deg,'
            f'hsl({h} 58% 46%),hsl({(h + 26) % 360} 58% 34%))">'
            f'{_initials(name)}</div>')


def user_bubble(text: str) -> str:
    return f'<div class="am user"><div class="ab">{esc(text)}</div></div>'


#: Where a message typed mid-round has to land.
#:
#: The composer appends to the thread, and the running round's answers append
#: inside the live area, which is itself a child of the thread. So a queued
#: bubble appended the ordinary way lands BELOW every answer, including the
#: answer to itself: you would read your own question underneath its reply.
#:
#: Out of band, into the live area, puts it in the order it was said. The two
#: halves of this selector live in two other files, so tests check both: the
#: class comes from stream_block, the id from agents.html.
QUEUED_TARGET = "#agent-thread .alive"


def queued_bubble(text: str) -> str:
    """A message typed while the agents were still answering the last one."""
    return (f'<div class="am user" hx-swap-oob="beforeend:{QUEUED_TARGET}">'
            f'<div class="ab">{esc(text)}</div></div>')


#: How much of the question a reply quotes. Enough to recognise, not enough
#: to reprint: a paragraph you typed would otherwise reappear above every
#: answer to it, twice over when two agents both reply.
QUOTE_CHARS = 90


def _quote(text) -> str:
    """The message an answer is answering, shown above it.

    Empty when there is nothing to quote, which is the ordinary case: one
    question, one answer, and nothing above it to confuse it with. A quote
    there only repeats the line directly above.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    one_line = " ".join(text.split())
    if len(one_line) > QUOTE_CHARS:
        one_line = one_line[:QUOTE_CHARS].rstrip() + "…"
    return f'<div class="aquote">{esc(one_line)}</div>'


def agent_bubble(name: str, content: str, replying_to=None) -> str:
    """One agent's finished answer: its own row, its own name, its own avatar.

    This is the entire feature. Nothing is stacked into another agent's bubble,
    because the panel draws the bubbles itself.

    `replying_to` is the message being answered, and it is passed only when
    more than one of the person's messages is on screen unanswered. Nobody has
    to press anything to see it, which is the whole point: in an ordinary chat
    app you long-press a message to reply to it, and here the answer says what
    it belongs to by itself.
    """
    return ('<div class="am agent">'
            f'{_avatar(name)}'
            '<div class="abody">'
            f'{_quote(replying_to)}'
            f'<div class="awho">{esc(name)}</div>'
            f'<div class="atext md">{esc(content)}</div>'
            '</div></div>')


def approval_bubble(name: str, ask_id: str, calls: list[dict]) -> str:
    """An agent that stopped to ask permission.

    Identified by the question, not by the agent. One agent can be waiting on
    two answers at once, and two bubbles carrying the same id would have htmx
    resolve both Yes buttons to the first of them, so answering the second
    question would swap the first one away.

    Handed only the calls, never the whole pending payload: that also carries
    the held conversation and the owner's email, and neither belongs in a
    browser.
    """
    items = []
    for call in calls or []:
        fn = call.get("function") if isinstance(call, dict) else None
        fn = fn if isinstance(fn, dict) else {}
        name_txt = esc(str(fn.get("name") or ""))
        args_txt = esc(str(fn.get("arguments") or ""))
        items.append(f'<li><code>{name_txt}</code> '
                     f'<span class="aargs">{args_txt}</span></li>')
    aid = esc(ask_id)
    return (f'<div class="am agent awaiting" id="await-{aid}">'
            f'{_avatar(name)}'
            '<div class="abody">'
            f'<div class="awho">{esc(name)}</div>'
            f'<div class="atext">{esc(name)} wants to run:</div>'
            f'<ul class="acalls">{"".join(items)}</ul>'
            '<div class="aactions">'
            '<button class="btn primary" type="button" '
            'hx-post="/tasks/agents/chat/approve" '
            f'hx-vals=\'{{"ask_id": "{aid}", "approved": "yes"}}\' '
            f'hx-target="#await-{aid}" hx-swap="outerHTML">Yes</button>'
            '<button class="btn" type="button" '
            'hx-post="/tasks/agents/chat/approve" '
            f'hx-vals=\'{{"ask_id": "{aid}", "approved": "no"}}\' '
            f'hx-target="#await-{aid}" hx-swap="outerHTML">No</button>'
            '</div></div></div>')


def working(name: str) -> str:
    """Which agent is running right now.

    A round of three agents that each use tools can hold the stream open for
    minutes. Without this line a slow round is indistinguishable from a broken
    one.
    """
    return f'<div class="aworking">{esc(name)} is working...</div>'


def note(text: str) -> str:
    """A system line in the thread: a skipped agent, a refusal, a hint."""
    return f'<div class="am note">{esc(text)}</div>'


def stream_block() -> str:
    """The element that opens the SSE connection for one round.

    One connection with two swap targets: finished bubbles append to the live
    thread, and the working line replaces itself. `sse-close` stops the browser
    reconnecting, which would otherwise re-run a round that has already been
    paid for.
    """
    return ('<div class="astream" hx-ext="sse" '
            'sse-connect="/tasks/agents/chat/stream" sse-close="close">'
            '<div class="alive" sse-swap="message" hx-swap="beforeend"></div>'
            '<div class="awork" sse-swap="working" hx-swap="innerHTML"></div>'
            '</div>')


def empty_thread() -> str:
    return ('<div class="aempty">Ask anything. Every agent hears it, and '
            'the ones with something to say answer. Name one and only they '
            'reply.</div>')


def thread(messages: list[dict]) -> str:
    """A saved conversation replayed.

    Roles other than user, assistant and note are the round bookkeeping (see
    routes_agent_chat) and render as nothing. Notes ARE drawn, because a round
    stores them on purpose: a skipped agent said out loud while the round ran
    and then gone on reload leaves a conversation that no longer makes sense.
    """
    out = []
    for m in messages or []:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "user":
            out.append(user_bubble(content))
        elif role == "note":
            if content:
                out.append(note(content))
        elif role == "assistant":
            name = str(m.get("agent_name") or "Agent")
            if content:
                # The stored decision, not a fresh one. After a reload the
                # messages are in order and nothing looks ambiguous any more,
                # so recomputing would silently drop a quote that was on
                # screen a moment ago.
                out.append(agent_bubble(name, content,
                                        m.get("replying_to")))
            awaiting = m.get("awaiting")
            if isinstance(awaiting, dict) and awaiting.get("calls"):
                out.append(approval_bubble(name,
                                           str(awaiting.get("ask_id") or ""),
                                           awaiting["calls"]))
    return "".join(out) if out else empty_thread()
