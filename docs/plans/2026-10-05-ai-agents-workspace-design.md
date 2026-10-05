# AI Agents page: chat-first workspace (design)

Date: 2026-10-05. Status: approved by the user the same day.
Brief: `PRODUCT.md`. Visual rules: `DESIGN.md` ("The Quiet Switchboard").

## Why

The user called the page confusing and asked for something professional,
built on evidence rather than guesses. An 8-agent read-only audit on
2026-10-05 measured the live page, the code and production usage.

**What the page does wrong:**
1. Impeccable critique: 17/40, the "major overhaul" band. Impeccable's
   checker (engine 0.1.9, on the build host) found 29 findings: 17
   low-contrast, 9 tiny-text, plus glow and a flat type scale.
2. The page has no primary job. At 1920x1080 the decorative Office card is
   614px tall and the conversation 200px. At 1366 the layout stacks the agent
   cards first and the composer goes off screen. The largest, brightest
   control is the cyan "Call a team meeting" (239x57); Send is 62x40.
3. In the Open WebUI shell, the pane starts at x=260 although the collapsed
   rail (`#sidebar`) is 42px wide. That leaves an empty column about 218px
   wide (`task-panel.js:1382` falls back to 260 because the walk only accepts
   ancestors 120px or wider).
4. On a 390px phone, `/ai-agents` never mounts. The shell's "app is up"
   check (`task-panel.js:1675`) looks for sidebar links, and Open WebUI
   renders none at that width: only a 390x47 `nav`. This was verified in the
   real DOM, and the page was still the plain chat home after 60 s.
5. Office links are `target=_top`, and only `a.who-chat, a.chat-with` are
   intercepted (`office.html:1528`). "Open the chat" and "The Brain"
   therefore load bare pages outside Open WebUI.
6. Two design systems share one screen: navy and cyan in the office, near
   black and periwinkle around it. Robot colours do not match the card
   colours (Ada is green on her card and purple as a robot). There are 8
   font sizes and 8 button styles, and `.btn` falls back to Arial.
7. The thread shows stored "PASS" and "Auto (Smart): routed to..." text as
   agent messages. The composer has no focus style (`outline: none`,
   `agent-chat.css:256`). Muted text (#74747e) is 3.87 to 4.08:1.
8. A new agent defaults to the first of 133 model options, "Webhook
   Automation" (`agents.html:2349-2358` sets a value only when editing).

**How it is used** (production DB, Caddy and Loki logs, read-only):
- 3 of 9 users own agents, and 2 used them in the last 7 days.
- About 70 runs a week. Every run a person starts is a chat turn.
- 81% of the owner's messages go to a single agent.
- "Call a team meeting": 6 prefills in 11 days. The Brain: 7 opens.
- Templates gallery: 0 loads. Connections through `user_connections`: 0.
- 25,553 activity polls in 11 days, against 17 messages sent.

## Decision

Option 2 of 3, the chat-first workspace, scored 30/40 by an adversarial judge.
"Restructure in place" scored 26 and "directory plus detail" 23.

The user confirmed on 2026-10-05 that the Office may leave the main surface.
On 2026-09-25 Ralph had made it inline, quoting "the owner". It stays reachable
from the page and keeps its own Agent Office pane. The page should feel like
Slack.

## Layout

| Pane width | Layout |
|---|---|
| 1181px and wider | Three panes: conversation list (232px) / conversation (flex) / details (320px, collapsible, remembered) |
| 700 to 1180px | List plus conversation; details opens as a sheet from the right over the conversation |
| under 700px | One pane at a time: list, then conversation ("Agents" goes back), then details ("Done") |

- Pane widths are measured on the agents page, not the window: the shell
  pane is narrower than the window.
- The window never scrolls at 1181px and above. The composer is always on
  screen at every size.

## Components

1. **Conversation list.**
   - "Everyone" comes first, with the agents' names as its second line.
   - Then one 48px row per agent: a solid one-hue avatar with a white
     initial, the name, and the role on one line.
   - Status words appear only for Working, Needs you and Failed; Ready is
     silent.
   - Search sits on top, with "New agent" (primary) beside the title.
   - Footer links: Agent Office, Knowledge graph, Connections.
   - Selecting a row calls the existing `window.aiuiTalkTo(id, name)`.
     Private threads are already separate saved rows, so no backend change
     is needed.
2. **Conversation header.**
   - Title: "Everyone" or the agent's name.
   - Subtitle: who hears the message ("Mia, Ada and Dev hear this. Each
     answers only if it has something to add.", or "Receptionist. Only Mia
     hears this conversation.").
   - Actions: Details (aria-expanded, remembered) and Clear (ghost).
3. **Thread.**
   - Messages sit in a centred column at most 760px wide, with text capped
     at 68ch.
   - Agent messages are not bubbles; the user's own message is a raised
     bubble on the right.
   - The thread stays pinned to the newest message while the reader is at
     the bottom (ResizeObserver).
4. **Composer.** Pinned to the bottom, with the placeholder "Message Mia" or
   "Message everyone". It has a real focus style: a periwinkle border and a
   2px ring.
5. **Details panel.** It replaces the agent cards, using today's `card()`
   data. In order:
   - role and a status sentence ("Ready. Last answered 3d ago");
   - instructions, clamped, with "Show all";
   - skills and tools;
   - model, with the friendly name and the id in small monospace;
   - memory ("Nothing remembered yet." or the notes, with Forget);
   - Edit agent and Delete agent.

   With Everyone selected it shows "About this conversation" instead: up to
   5 recent activity rows, worded plainly, and an "Open Agent Office" link.
6. **Agent Office on demand.**
   - The footer link swaps the conversation area for the office iframe
     (built lazily, the same `/tasks/office?embed=1` with the existing
     `aiui-office-*` bridge) and shows a "Back to conversation" button.
   - A robot's Chat still opens that agent's conversation in place.
   - No office iframe is built until it is opened.
7. **Knowledge graph.** Opens the shell's Graph pane through a new
   `aiui:open-pane` postMessage that task-panel.js handles for known nav
   paths. It never navigates the top window.
8. **Agent form.**
   - New agents default to the server's `AGENT_DEFAULT_MODEL`, exposed on
     the existing tools response.
   - Chat models are grouped as Recommended first. Non-chat models are
     left out by an explicit id list, never a name pattern
     (`test_agents_page.py:1361` records that a pattern dropped Auto
     (Smart)).
   - The search input is styled.
   - The dialog gets role=dialog, aria-modal and Escape to close.

## Removed from the main surface

- The Office dock, its grip and "Show the office".
- The floor-bar "Call a team meeting" and "Open the chat".
- Card "Chat with X" buttons and "Back to everyone".
- The "Memory: 0 notes Show" line on every card.
- The model chip on every card.

Typing "everyone answer:" in the room still starts a meeting (server
behaviour unchanged).

## Server-side changes (small)

1. Hide stored PASS and routing-footer messages when the thread is drawn
   (`agent_chat_render.thread`), using the existing `agent_routing.is_pass`
   and `ROUTE_FOOTER`.
2. Add `default_model` (from `AGENT_DEFAULT_MODEL`) to the tools response the
   form already loads.
3. Stop the 5 s activity poll while the agents pane is hidden in the shell.
   The shell keeps closed panes alive (`task-panel.js:1385-1389`), so
   `document.hidden` alone is not enough; also check
   `window.frameElement`'s visibility.

## Shell changes (`task-panel.js`)

1. **Pane edge.** Use the right edge of the collapsed `#sidebar` rail
   (left-anchored, 30 to 120px wide, taller than 400px) when no wide sidebar
   qualifies. Use edge 0 when there is no rail (phones).
2. **Phone mount.** Count an authenticated Open WebUI shell as "app is up"
   even without sidebar links. The signed-out guard must still hold: never
   open over `/auth`.
3. **`aiui:open-pane`.** A same-origin message listener that opens a known
   nav entry by its path.

Fixtures come from the real Open WebUI v0.11.4 DOM, saved on 2026-10-05:
`desk_collapsed.html` (42px `#sidebar`) and `phone_home.html` (no sidebar,
47px `nav`). They are not invented.

## Office page (`office.html`, Ralph's file, small)

- When hosted, also intercept the floor-bar links, skill links and Edit
  agent, so nothing loads a bare page.
- Hide "Open the chat" when embedded.
- Robots use the agent's name hue, so each agent has one colour everywhere.
- Restore the `.dot` state colours deleted in 6e3dda3c4.
- Replace the 3px cyan side stripe with a 1px border.
- Add a prefers-reduced-motion guard for its 5 infinite animations.

## Phases

1. **Phase 0, shipped on its own.**
   - Shell pane edge and phone mount.
   - Office links stay in the shell.
   - Contrast token, focus rings, Escape and dialog roles.
   - Model default and filtering.
   - PASS filter.
   - Button font.
2. **Phase 1.** The three-pane workspace, the details panel, the office on
   demand, and the graph via `aiui:open-pane`.
3. **Phase 2 (later).**
   - "Asked Dev" on sent messages (needs the chosen speakers saved).
   - "Dev asked Mia" lines from `tasks.agent_step`.
   - "Next scheduled" in details.
   - Activity over SSE instead of polling.

## Constraints kept

- The htmx contract: `hx-post="/tasks/agents/chat/send"`, the thread GET and
  the hidden `agent` field restored after reset.
- Never auto-send. `?ask=` and office links only prefill.
- `esc()` on all interpolated data, DOMPurify on markdown, and origin checks
  on every message listener.
- No em or en dashes in agents.html, unique ids, and inline JS that parses.
- No emoji or decorative icons in the UI.
- Never deploy local `templates.py`. Never touch `.env`.

## Testing

1. **Every pinned test that changes meaning** (about 300 browser tests in
   total; the layout and office-inline ones are the ones affected) is
   rewritten red-first: it fails against today's page, then passes.
2. **New browser tests:**
   - composer on screen at 1920x994, 1366x768, 768x1024 and 390x844;
   - the window does not scroll at 1181px and above;
   - list selection switches the thread and the placeholder;
   - details toggle is remembered;
   - Escape closes the top-most dialog;
   - focus ring visible on the composer;
   - Tab reaches the composer early;
   - no office iframe until it is opened;
   - PASS messages hidden;
   - default model;
   - pane edge against both real-DOM fixtures.
3. **Before any claim of done:**
   - real-browser screenshots at all four sizes, before and after;
   - Impeccable's checker on the changed files;
   - contrast measured;
   - served bytes over HTTPS matched to the repo.

## Risks

1. Ralph owns most of these files, so tell him before Phase 1 lands. Fetch
   and rebase on `fork/main` right before deploy, and run
   `git branch -r --contains` on the deploy SHA.
2. The real Open WebUI DOM may change on the next image bump. The edge and
   phone checks key on `#sidebar` and the shell `nav`, and fall back safely.
3. tasks bakes `/app/static` into its image. Copy the files to the host,
   rebuild, then check host, container and HTTPS bytes.
