# Simplify the Discord #video-generation step-by-step copy

**Date:** 2026-06-23
**Branch:** `fix/video-thread-image-intake`
**Status:** Approved + implemented (copy-only)

## Problem

Users reported the #video-generation step-by-step is messy and confusing. Root
causes found in the existing copy:
- The thread intro crammed 4 actions into one run-on sentence.
- Three competing ways to add screenshots (paste URL / drag / `/video add`) were
  surfaced at once.
- Ordering contradicted itself between surfaces (intro said "screenshots then
  title"; the saved-details message said "title then screenshots").
- Mixed terminology ("description" vs "Add title & description"; "Generate" vs
  "Generate video").
- The channel card was stale (only mentioned drag, not the link-capture path).

## Decision (locked with the user)

One canonical 4-step spine, reused verbatim on every surface; step 2 shows the
two screenshot options as EQUAL choices:

```
1. New video           -> opens your private thread
2. Add screenshots     -> paste your site link, or drag your own images in (up to 12)
3. Add a description   -> what the walkthrough should show
4. Generate video
   (style + voice optional, good defaults set)
```

Constraints: no emoji/icons (plain text only); identical ordering + terminology
everywhere; backend-accurate (a description and >=1 screenshot are required to
generate; title/style/voice optional with defaults); `/video add` not advertised.

The copy was drafted by a 4-candidate judge-panel workflow, synthesized, and
passed a strict critic (`ok: true, issues: []`).

## Final copy (implemented)

- **Channel card** (`build_video_embed`): "**Turn screenshots into a narrated
  walkthrough.**" + a monospace 4-step block + "Style and voice are optional".
- **Thread intro, no screenshots** (`_open_video_studio`): "You're in your
  private thread - step 1 done. Three steps to go:" then bold steps 2-4.
- **Thread intro, screenshots pre-added**: "Screenshots added: N/12. Two steps to
  go:" then bold steps 3-4 + "Want more screenshots? ...".
- **Confirmations** (`commands.py`), all pointing forward consistently:
  - add: "Added - {count}/12 screenshots. Next: add a description, then click **Generate video**."
  - capture (progress): "Capturing screenshots from {host} - this takes a few seconds."
  - capture (done): "Added {count}/12 screenshots from {host}. Next: add a description, then click **Generate video**."
  - details saved: "Description saved. Make sure you've added a screenshot - paste your site link, or drag your own images in (up to 12) - then click **Generate video**."
- **Buttons** (`build_studio_components`): `Paste your site link` · `Add description` · `Generate video`; capture modal title `Paste your site link`.

## Scope

Copy-only. No logic, endpoints, or flow mechanics changed. Files touched:
`webhook-handler/handlers/{video_panel,discord_commands,commands}.py` + two test
assertions updated to the new wording. Full webhook-handler suite green (943).

## Deploy

Bot-only: scp the three handler files, rebuild `webhook-handler`, verify Up +
gateway reconnect. Then PATCH the existing channel panel message (channel
`1517566375646728212`, msg `1517566377559461940`) to the new embed so the live
card updates (editing the bot's own message needs no Manage Messages). New
threads pick up the new intro automatically.
