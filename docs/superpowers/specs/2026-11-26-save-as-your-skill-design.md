# "Save as your skill" after an automation works — design (2026-11-26)

## Intent

Lukas, call of 2026-11-25: "ask them what things they want to automate, do
it for them, and create skill out of it". Saving a person's own skill
exists (Skills tool: `write_skill` shows a draft and saves nothing,
`save_skill` saves exactly what was shown). Nothing offers it at the moment
a person has just set an automation up, so on live 1 skill has ever been
saved.

## Goals

- When the main chat has just **made** something that runs on its own, a
  **Save as your skill** button sits under the reply:
  - an n8n workflow was created, or switched on (`create_workflow`,
    `activate_workflow` on the person's own n8n), or
  - an Automation was made (`create_automation`).
- It shows whether the write ran at once or after the person said yes.
- A click sends one fixed message to the chat, and the existing skill flow
  does the rest: a draft is shown, nothing is saved until they say yes.

## Non-goals

- A new way to save skills. The draft and confirm steps stay as they are.
- The office or the Agents page panel. Main chat (Auto) only.
- Offering it after a schedule. A schedule is already a saved job.

## Anti-goals

- The button shows after a write that failed or was refused.
- A click saves anything without the person reading the draft first.
- The button sends text from the reply. The page only sends texts from its
  own fixed list, the way `#aiui-open:` only opens places on its own list.

## Approaches

- **A. Tell the model to offer it** (skill text, tool help). Cheapest, but it
  depends on the model remembering, and the model dropped the Connect link
  that way once (2026-11-04).
- **B. A button the service adds (chosen by the user).** The same reason the
  Connect buttons moved into code: it is there every time.

## How it works

1. `skill_offer.py`, new. A per-request list (a context variable) of things
   made in this turn. `agent_tools.execute_tool_call` tells it about each
   call that ran: it counts only a call that really succeeded:
   - n8n: the tool is `create_workflow` or `activate_workflow` (named on the
     call, or inside `call_tool`'s arguments) and the result reads
     `"ok": true`;
   - Automations: `create_automation` and the result starts "Made the
     automation".
2. `routes_agent_turn.chat` and `_chat_events` (the main chat, both routes)
   open the list before the turn. After it, if something was made and the
   last reply is not still waiting for a yes, the reply gets
   `[Save as your skill](#aiui-say:save-skill)` underneath, once, and is
   rendered again. Fails open: the reply as it was.
3. `integrations-ui.js`: `#aiui-say:<id>` becomes a button for ids on its
   own list. `save-skill` sends "Write a skill from what you just set up for
   me, and show it to me before saving." through `aiuiSendToChat` (only into
   an empty message box, as Connect-then-carry-on does). After it sends, the
   button reads "✓ Asked" and is disabled. The label is the list's, never
   the link's text. Only the button under the latest reply sends (checked
   when drawn and again at the click); an older one reads "Only works on the
   latest reply" and is disabled. A send that did not happen reads "Wait for
   the reply to finish or clear your message, then press again".
4. The message is `skill_offer.ASK` in the service (a test reads the page's
   copy and compares). When the last message is exactly that, the assistant
   runs with the `skills` tool added to whatever was picked, pinned for the
   "yes" that follows, even when Jev picks nothing.

## Checks

- Unit: what counts as made (ok, failed, refused, other tools, call_tool
  wrapping), the button added once, not on a held reply, fails open.
- Browser: the link becomes a button, sends the fixed text, unknown ids stay
  plain links.
- Live: make an Automation from the main chat on the test account, see the
  button, press it, see the draft; then delete the automation and the chat.

## Left to the builder

Exact wording of the button's message; where in `chat` the list is opened.
