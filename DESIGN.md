---
name: IO Agents Workspace
description: The dark, conversation-first workspace where people talk to and look after their AI agents.
colors:
  periwinkle: "#7c8cff"
  periwinkle-deep: "#5d6cff"
  ink: "#0a0a0b"
  panel: "#111113"
  raised: "#17171a"
  hairline: "#24242a"
  edge: "#2e2e36"
  text: "#ededee"
  text-secondary: "#b8b8c0"
  muted: "#8b8b95"
  warn: "#fbbf24"
  danger: "#f87171"
  ok: "#4ade80"
typography:
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, Inter, Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.3
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, Inter, Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.35
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, Inter, Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  message:
    fontFamily: "-apple-system, BlinkMacSystemFont, Inter, Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  small:
    fontFamily: "-apple-system, BlinkMacSystemFont, Inter, Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, Inter, Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.4
  mono:
    fontFamily: "SFMono-Regular, ui-monospace, Menlo, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  sm: "6px"
  md: "8px"
  lg: "12px"
  full: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  xxl: "32px"
components:
  button-primary:
    backgroundColor: "{colors.periwinkle}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 14px"
    height: "36px"
  button-primary-hover:
    backgroundColor: "{colors.periwinkle-deep}"
  button-secondary:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 14px"
    height: "36px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
    height: "36px"
  conversation-row:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 10px"
    height: "48px"
  conversation-row-selected:
    backgroundColor: "{colors.raised}"
  composer:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.text}"
    typography: "{typography.message}"
    rounded: "{rounded.lg}"
    padding: "12px 14px"
  avatar:
    textColor: "#ffffff"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    size: "28px"
---

# Design System: IO Agents Workspace

Scope: `mcp-servers/tasks/static/agents.html` and `agent-chat.css`, the AI
agents page. Other IO pages (cron, projects, video, templates, graph) each
declare their own tokens today. This file is the reference they should
converge on; it does not yet describe them.

## 1. Overview

**Creative North Star: "The Quiet Switchboard"**

A switchboard connects you to the right person and then gets out of the way.
The workspace works the same way. A short list of agents sits on the left, the
conversation fills the middle, and an agent's details open on the right only
when asked for. Everything is dark, flat and quiet so that the words in the
thread are the brightest thing on the screen. Colour is rare and means
something: the accent marks what you can act on or what has focus, a state
colour marks something that needs you, and each agent owns one hue for its
avatar and nothing else.

This system rejects the neon dashboard. That means no robot mascots on the
main surface, no navy-and-cyan glow, no grid floors, no gradient avatars, no
raw model ids on the main surface, and no decoration competing with the
conversation (PRODUCT.md, Anti-references). It is dense the way Slack is
dense: rows are compact and readable, and nothing is a card unless it has to
be.

**Key Characteristics:**
- Three panes on wide screens, two on medium, one at a time on phones.
- Flat tonal layers: ink, then panel, then raised. No decorative shadows.
- One accent (periwinkle) for actions, focus and links only.
- One hue per agent, used only on its avatar.
- Plain-text labels. No icons as decoration, no emoji.
- Responsive by structure, not by fluid type.

## 2. Colors

A near-black neutral ramp with a single cool accent. Colour is rationed so
that it always carries meaning.

### Primary
- **Switchboard Periwinkle** (#7c8cff): the primary button (Send, Save agent),
  the focus ring, links, and the "Working" status word. It contrasts 6.65:1
  on ink and 6.01:1 on raised. Text on it is ink (#0a0a0b, 6.65:1), never
  white (2.98:1 fails).
- **Pressed Periwinkle** (#5d6cff): hover and pressed state of the primary
  button only.

### Neutral
- **Ink** (#0a0a0b): the conversation surface, the page's base layer.
- **Panel** (#111113): the second neutral layer, used by the conversation
  list and the details panel.
- **Raised** (#17171a): the composer field, the selected conversation row,
  hover rows and secondary buttons.
- **Hairline** (#24242a): 1px dividers between panes and sections.
- **Edge** (#2e2e36): borders of inputs and secondary buttons.
- **Text** (#ededee): primary text, 16.9:1 on ink.
- **Secondary Text** (#b8b8c0): roles, subtitles and metadata, 9.1:1 or
  better.
- **Muted** (#8b8b95): placeholders, timestamps and hints. It contrasts at
  least 5.30:1 on every surface. It replaces #74747e, which failed at 3.87:1.

### State
- **Needs You Amber** (#fbbf24): an agent waiting for an answer or approval.
  Always paired with the words "Needs you".
- **Failed Red** (#f87171): a failed run, and destructive actions (Delete,
  Clear conversation). Always paired with a word.
- **Done Green** (#4ade80): success confirmations only, such as a saved
  toast. "Ready" is the resting state and shows no colour.

### Agent identity
Each agent's hue comes from the existing hash of its name (the same hash the
card and the chat bubble already share). It is drawn as a solid
`hsl(hue 45% 32%)` avatar square with a white initial. The worst case is
4.77:1 at hue 60, so every hue passes. The hue appears on the avatar and
nowhere else: no tinted borders, no tinted cards, no gradients.

### Named Rules
**The Rationed Accent Rule.** Periwinkle covers 10% or less of any screen. If
two periwinkle things compete, one of them is wrong.

**The One Hue Per Agent Rule.** An agent is the same colour in the list, in
the thread, in the details panel and in the Agent Office. A second palette
for the same agent is a bug.

## 3. Typography

**Body Font:** the system UI stack (-apple-system, Inter, Segoe UI, Roboto,
system-ui). No webfont is loaded.
**Label/Mono Font:** the system monospace stack, only for technical ids shown
in the details panel.

**Character:** one quiet sans in three weights (400, 500, 600). Hierarchy
comes from size steps and weight, never from a second display family. Buttons
inherit the family; the old Arial fallback on buttons is a bug.

### Hierarchy
- **Title** (600, 20px, 1.3): the phone screen title and dialog titles.
- **Headline** (600, 16px, 1.35): the conversation title ("Mia",
  "Everyone") and section heads in the details panel.
- **Message** (400, 16px, 1.55): message text in the thread, capped at 68ch,
  inside a centred column at most 760px wide.
- **Body** (400, 14px, 1.5): conversation row names, buttons, form fields and
  details text.
- **Small** (400, 13px, 1.45): roles, subtitles and hints.
- **Label** (500, 12px, 1.4): timestamps, counts and status words. 12px is
  the floor; nothing is smaller.

### Named Rules
**The Five Sizes Rule.** Only 12, 13, 14, 16 and 20px exist. Half-pixel sizes
(11.5, 12.5, 13.5) and 10 or 11px text are prohibited.

## 4. Elevation

Flat by default. Depth comes from the tonal ladder (ink, panel, raised) and
1px hairlines, not from shadows. Only content floating above other content
(menus, dialogs and the details sheet on medium screens) gets a shadow, and
then a tight one.

### Shadow Vocabulary
- **Float** (`box-shadow: 0 4px 8px rgba(0, 0, 0, 0.45)`): menus, dialogs and
  the details sheet. It sits on a 1px Edge border, so its blur never goes
  above 8px.
- **Scrim** (`background: rgba(0, 0, 0, 0.6)`): behind a dialog or a phone
  sheet.

### Named Rules
**The No Glow Rule.** Coloured shadows, glows and halos are prohibited. If
something glows, it is decoration.

## 5. Components

### Buttons
- **Shape:** gently rounded (8px), 36px tall on desktop and 44px under 700px.
- **Primary:** periwinkle fill with ink text (Send, Save agent, New agent).
  At most one per region.
- **Secondary:** raised fill, 1px Edge border, text colour (Details, Cancel,
  Edit agent).
- **Ghost:** no fill, secondary text, raised fill on hover (Clear, Close).
- **Danger:** ghost shape with Failed Red text (Delete agent, the confirming
  Clear conversation button).
- **Focus:** a 2px periwinkle ring with a 2px offset on every button,
  through `:focus-visible`. Never `outline: none` without a replacement.

### Conversation list (signature component)
- **Rows:** 48px tall, with an avatar (28px), the name (Body, 500) and the
  role on one line (Small, Secondary Text, ellipsis).
- **Everyone row:** first in the list, titled "Everyone", with the agents'
  names as its second line.
- **States:** default has no fill; hover is raised; selected is raised with
  the name in Text weight 600. The selected row never gets a coloured side
  stripe.
- **Status:** only "Working", "Needs you" and "Failed" appear, as a Label
  word on the right. "Ready" shows nothing.
- **Footer links:** Agent Office, Knowledge graph and Connections, as quiet
  Body links at the bottom of the list.

### Thread
- **Agent message:** avatar, name (Body 600) and time (Label, Muted), with
  the text below in Message style. No bubble.
- **Own message:** right-aligned with a raised fill and an 12px radius,
  capped at 68ch.
- **System line:** centred Small text in Muted, for example "Dev asked Mia",
  drawn only from a recorded handoff.
- **Working:** "Mia is working" in Label, with a reduced-motion-safe pulse
  on the word only.

### Composer
- **Style:** a raised field with a 12px radius and a 1px Edge border, pinned
  to the bottom of the conversation pane, with Send beside it.
- **Placeholder:** "Message Mia" or "Message everyone", in Muted.
- **Focus:** the border turns periwinkle and gains a 2px periwinkle ring. A
  focused composer must look different from an idle one.

### Details panel
- **Layout:** 320px wide on the Panel layer, separated by a hairline. It is
  collapsible, and its open or closed state is remembered.
- **Sections:** About (role, status sentence), Instructions (clamped, with a
  "Show all" disclosure), Skills, Tools, Model (friendly name in Body, id in
  Mono and Muted), Memory, then Edit agent and Delete agent.
- **Headings:** section heads use Label style in Secondary Text, sentence
  case, never tracked uppercase.

### Inputs and dialogs
- **Inputs:** raised fill, 1px Edge border, 8px radius, 36px tall. Focus uses
  the periwinkle border and ring. Search inputs follow the same rule; no
  unstyled browser boxes.
- **Dialogs:** role="dialog", aria-modal and a labelled title. Focus moves
  inside on open and returns to the trigger on close. Escape closes them.
  Panel fill, a 1px Edge border, a 12px radius and the Float shadow.

## 6. Do's and Don'ts

### Do:
- **Do** give the conversation the full height of the window, with the
  composer always on screen.
- **Do** use one hue per agent, as a solid `hsl(hue 45% 32%)` avatar with a
  white initial, everywhere the agent appears.
- **Do** say who will hear a message before it is sent ("Only Mia hears this
  conversation", "Mia, Ada and Dev hear this").
- **Do** keep text at 12px or above, and muted text at #8b8b95 or brighter.
- **Do** show a 2px periwinkle focus ring on every interactive element.
- **Do** make every target 24px or larger, and 44px under 700px.

### Don't:
- **Don't** put robot mascots or character art on the main surface.
- **Don't** use neon dashboards: navy-and-cyan glow, grid floors, glowing
  accents.
- **Don't** use gradient avatars, gradient text or gradients as decoration.
- **Don't** show raw model ids or internal words ("channel", "PASS", "routed
  to", "CLEAN 94%") on the main surface.
- **Don't** add decoration that competes with the conversation, and don't
  use emoji or icons as decoration. Labels are plain text.
- **Don't** offer several ways to do the same thing that behave differently.
- **Don't** use `border-left` or `border-right` over 1px as a coloured
  accent, or tracked uppercase eyebrow labels.
- **Don't** pair a 1px border with a shadow blurred more than 8px.
