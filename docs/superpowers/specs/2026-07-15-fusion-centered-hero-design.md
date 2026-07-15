# Fusion Page: Centered Hero Layout

Date: 2026-07-15
Status: Approved (Ralph picked direction A from the mockup gallery). Frontend-only.

## Goal

Kill the empty gap on the Fusion page. When there is no conversation yet, center
the content as a hero (a heading, the model-picker card, and the composer stacked
in the vertical middle with a soft glow). Once the user sends a message, fall
back to the normal chat layout (thread scrolls and fills the space, the picker
and composer dock at the bottom).

## Scope

`mcp-servers/tasks/static/fusion.html` only. No backend, no route, no test
changes. The picker fragment (`_render_picker`), all endpoints, and the existing
JS behaviors (auth header, Enter-to-send, stream disable/enable, add-model modal,
autoscroll) are reused unchanged. The 46 existing tests stay green.

## Layout state machine

Two states, driven by a single `body.chat` class:
- **Hero** (default, no `.chat`): no messages yet.
- **Chat** (`body.chat`): at least one message in the thread.

The class is toggled in JS on `htmx:afterSwap` and on load:
`document.body.classList.toggle('chat', !!document.querySelector('#thread .msg'))`.
Sending a message swaps a `.msg` bubble into `#thread` -> class added. New chat
resets `#thread` to the empty placeholder -> class removed. This is more portable
than CSS `:has()` and hooks the afterSwap handler that already exists.

## DOM structure

```
<header> ... brand + New chat ... </header>
<main class="stage">
  <div class="hero-head">        <- visible only in hero state
    <h2>What should the panel answer?</h2>
    <p>Pick your models, ask once, get one combined answer.</p>
  </div>
  <div id="thread"> ... </div>    <- messages; hidden in hero state
  <div class="dock">
    <div id="picker" ...></div>   <- hx-get load, unchanged
    <form class="composer"> ... </form>
  </div>
</main>
```

`hero-head`, `#thread`, and `.dock` are siblings inside `.stage`. DOM order
(hero-head, thread, dock) works for both states because each state hides the
element it does not need.

## CSS behavior

- `.stage { flex: 1; display: flex; flex-direction: column; min-height: 0; width: 100%; }`
- **Hero** (`body:not(.chat)`): `.stage` centers its children
  (`justify-content: center; align-items: center; gap: 18px`) with a radial glow
  via `.stage::before`; `#thread` is `display: none`; `.hero-head` shows,
  centered; `.dock` is `width: min(600px, 100%)`.
- **Chat** (`body.chat`): `.hero-head` is `display: none`; `#thread` is
  `flex: 1; overflow-y: auto`; `.dock` is `width: 100%` (the picker and composer
  keep their own internal max-width centering).
- The picker card and composer are set to `width: 100%` so `.dock` controls their
  outer width per state; their max-width centering moves onto `.dock`/inner rules.
- Respect `prefers-reduced-motion`: any transition on the state change is
  optional and disabled under reduced motion (a simple fade is enough; no
  layout animation required).

## Copy

- Hero heading: "What should the panel answer?"
- Hero subheading: "Pick your models, ask once, get one combined answer."
  (The old centered "Pick your models below..." empty-thread text is removed;
  the hero-head replaces it.)

## Verify

- Load with no conversation: heading + picker card + composer are vertically
  centered with the glow; no big empty gap; the picker still loads via
  `hx-get="/tasks/fusion/picker"`.
- Send a message: layout switches to chat (thread scrolls, dock at bottom),
  heading hidden, streaming answer appears, Send re-enables on close.
- New chat: returns to the centered hero.
- Add-model modal, tabs, chips, judge dropdown all still work in both states.

## Out of scope

- Directions B (unified composer) and C (console) from the mockup gallery.
- Any backend/model/picker-logic change.
