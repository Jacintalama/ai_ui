# Product

## Register

product

## Users

IO is a private AI workspace used by a small team: 9 accounts, of which 2 to 4
are active in a given month (production database, 2026-10-05).

The AI agents page belongs to people who keep 3 to 7 named agents (for example
Mia, Ada and Dev) and talk to them every day, mostly from a desktop browser.
They message one agent at a time far more often than all of them at once: 81%
of the owner's messages went to a single agent. They also reach the same
agents from Discord, Slack and schedules. They know Slack well and expect its
conventions: a list of conversations, one open thread, details on demand.

## Product Purpose

IO lets a person build web apps with an AI builder (App Builder) and keep a
small staff of AI agents. Each agent has its own instructions, tools, skills
and memory, and answers in chat, in team channels and on schedules.

The agents page is where you talk to those agents and look after them.
Success means three things:
- you pick an agent, or everyone, ask, and read the answer without hunting;
- you can tell at a glance what each agent is for and whether it needs you;
- you can change an agent without being surprised by what the change does.

## Brand Personality

Calm, precise, trustworthy. The voice is a capable colleague: short plain
sentences that state consequences ("Acts without asking. Sends email, deletes
things."). It is never playful at the expense of clarity, and it never claims
something happened unless a record says it did.

## Anti-references

- Robot mascots and character art as the main surface.
- Neon dashboards: navy-and-cyan glow, grid floors, glowing accents.
- Gradient avatars, and gradients used as decoration anywhere.
- Raw model ids and internal words on the main surface ("channel", "PASS",
  "routed to", "CLEAN 94%").
- Decoration that competes with the conversation. Emoji or icons used as
  decoration; labels are plain text.
- Several ways to do the same thing that behave differently.

## Design Principles

1. The conversation is the product. It gets the most space, the clearest
   controls and the first keyboard stop.
2. Show what happened, never imply it. Status, runs and handoffs come from
   records, not from what an agent says.
3. One identity per agent: one name and one colour, everywhere it appears.
4. Familiar over clever. Use Slack's patterns, standard dialogs, Escape to
   close and a visible focus ring, rather than inventing affordances.
5. Plain words with consequences. Every setting says what it does and where
   it applies.

## Accessibility & Inclusion

- WCAG 2.2 AA. Text contrast is at least 4.5:1, or 3:1 for large text, and
  focus is always visible.
- Targets are at least 24px, or 44px on touch screens.
- Every action can be reached by keyboard, and Escape closes the top-most
  dialog.
- prefers-reduced-motion is honoured. Colour never carries meaning on its own:
  a status always has a word.
