# Needed, then pick one: the chat's app recommendations

Date: 2026-11-24. Size: a small change. Approach chosen: A (the service
lays it out).

## Why

Standup 2026-11-23, on "I want people to fill the form from my website to be
saved into Airtable automatically": Airtable is required because the person
named it; the part that does the work automatically can be n8n, Zapier or
the platform's own Automations, and the person chooses. The answer should
show that difference.

## What it does today (checked live 2026-11-24, that exact message)

- Four identical buttons in one row: Connect Airtable, Connect n8n,
  Connect Zapier, Set up in AI Agents.
- The answer (build-a-workflow skill) treats n8n as the only way: "Your n8n
  is not connected yet, so I cannot build this right now".
- Under it, the service adds "Recommended: Zapier, so IO can ..." and the
  Automations how-line, so it reads as two recommendations, not one choice.

## Goals

- The app the person named reads as **needed**, with its own button.
- n8n, Zapier and Automations read as **pick one**, with their buttons
  together on their own line.
- The model gives the case for each of the three and lets them choose; it
  does not pick one or say "I cannot build this" before they chose n8n.

## Non-goals

- No change to what Jev scores or to the cut-offs.
- No change to the page script: a link becomes a button where it stands
  (`integrations-ui.js`, `wireAiuiConnectLink`), so a second line of buttons
  is just a second line.
- A timer job is unchanged: n8n and Zapier are already dropped for it.

## Anti-goals

- Telling somebody who already connected n8n or Zapier to go and pick again.
  Today a connected member settles the group and no rival is offered; that
  stays.

## Approaches

- **A. The service lays it out (chosen).** `with_buttons` writes the needed
  line and the pick-one line; `brief` tells the model the same structure.
  The same every time, whatever the model writes.
- B. Only change the brief. Smaller, but the model has ignored our brief
  before (CLAUDE.md, "The answer never narrates the button"), so it would
  be right some of the time.

## The design

1. `plan()`: when the automation group is in the plan and none of its
   members is connected, Automations joins the choice even if Jev did not
   pick it, marked as part of the choice. (My call: Lukas said "one of the
   three". Automations starts from a web address or an email, which covers
   any job where something arrives.)
2. `with_buttons()`, only when a choice is shown:
   - An app outside the group that is not connected:
     `You need Airtable, because you asked for it.` when the message named
     it, else today's `Recommended: Airtable, so IO can ...` line; then its
     button on that same line.
   - Then one line: `To do it automatically, pick one: n8n, Zapier or
     Automations.` and the three buttons on the next line.
   - The "Recommended: Zapier" line and the Automations how-line (which says
     "webhook") are not added for members of the choice. Limit lines
     (`n8n cannot yet ...`) stay as today.
   - With no choice in the plan, the output is exactly what it is today.
3. `brief()`: when a choice is shown, say which apps are needed and that
   the automatic part is a choice of three, give the case for each in a
   sentence, let them choose, and do not say it cannot be done because one
   of them is not connected.
4. `build-a-workflow` SKILL.md: if they are being offered a choice between
   n8n and other ways, let them choose first; the "n8n is not connected"
   line applies once they choose n8n.

## Checks

- Unit tests for each point above, plus: no choice in the plan gives
  today's output byte for byte; a connected n8n gives no pick-one line.
- Update `test_ios_own_automations_sit_beside_n8n_and_zapier` (it pins all
  buttons on the last line).
- Live: the same message in the live chat after deploy, screenshot.

## Left to the builder

Exact helper names; where the "is part of the choice" mark lives in the
plan dict.
