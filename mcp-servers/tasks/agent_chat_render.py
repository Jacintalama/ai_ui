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


def _initial(name: str) -> str:
    return esc((name or "?").strip()[:1].upper())


def user_bubble(text: str) -> str:
    return f'<div class="am user"><div class="ab">{esc(text)}</div></div>'


def agent_bubble(name: str, content: str) -> str:
    """One agent's finished answer: its own row, its own name, its own avatar.

    This is the entire feature. Nothing is stacked into another agent's bubble,
    because the panel draws the bubbles itself.
    """
    return ('<div class="am agent">'
            f'<div class="aav">{_initial(name)}</div>'
            '<div class="abody">'
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
            f'<div class="aav">{_initial(name)}</div>'
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
    return ('<div class="aempty">Pick who is in the room, then ask. '
            'Each agent answers in its own message.</div>')


def chips(agents: list[dict], room: list[str]) -> str:
    """Who is available and who is in the room.

    Replaces itself (hx-swap outerHTML into #agent-room), so it carries its own
    id.
    """
    if not agents:
        return ('<div class="achips" id="agent-room">'
                '<span class="asidenote">You have no agents yet. '
                'Make one and it will show up here.</span></div>')
    out = []
    for a in agents:
        aid = esc(str(a.get("id") or ""))
        name = esc(str(a.get("name") or a.get("id") or ""))
        inroom = str(a.get("id")) in (room or [])
        cls = "chip in" if inroom else "chip"
        url = ("/tasks/agents/chat/room/remove" if inroom
               else "/tasks/agents/chat/room/add")
        out.append(f'<button class="{cls}" type="button" hx-post="{url}" '
                   f'hx-vals=\'{{"agent_id": "{aid}"}}\' '
                   'hx-target="#agent-room" hx-swap="outerHTML">'
                   f'{name}</button>')
    return f'<div class="achips" id="agent-room">{"".join(out)}</div>'


#: This fragment replaces itself, so it has to carry its own hx-get and
#: hx-trigger. Without them the first swap installs an element that is no
#: longer listening, and the list goes deaf for the rest of the page's life.
#: The Fusion sidebar had exactly that bug.
_CHATLIST_HX = ('id="agent-chatlist" hx-get="/tasks/agents/chat/chats" '
                'hx-trigger="load, agent-chats-changed from:body" '
                'hx-swap="outerHTML"')


def chat_list(chats: list[dict], active_id: str | None) -> str:
    if not chats:
        return (f'<p class="asidenote" {_CHATLIST_HX}>No saved conversations '
                'yet.</p>')
    rows = []
    for c in chats:
        cid = esc(str(c.get("id") or ""))
        title = esc(str(c.get("title") or "New chat"))
        active = " active" if str(c.get("id")) == active_id else ""
        rows.append(
            f'<div class="achatrow{active}">'
            f'<button class="achatopen" type="button" '
            f'hx-get="/tasks/agents/chat/chat/{cid}" '
            f'hx-target="#agent-thread" hx-swap="innerHTML" '
            f'title="{title}">{title}</button>'
            f'<button class="achatdel" type="button" '
            f'hx-delete="/tasks/agents/chat/chat/{cid}" '
            f'hx-target="#agent-chatlist" hx-swap="outerHTML" '
            f'hx-confirm="Delete this conversation?" '
            f'title="Delete">&times;</button>'
            '</div>')
    return f'<div class="achatlist" {_CHATLIST_HX}>{"".join(rows)}</div>'


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
                out.append(agent_bubble(name, content))
            awaiting = m.get("awaiting")
            if isinstance(awaiting, dict) and awaiting.get("calls"):
                out.append(approval_bubble(name,
                                           str(awaiting.get("ask_id") or ""),
                                           awaiting["calls"]))
    return "".join(out) if out else empty_thread()
