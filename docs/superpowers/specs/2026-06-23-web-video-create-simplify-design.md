# Granny-simple web video create page (+ optional screenshots)

**Date:** 2026-06-23
**Branch:** `fix/video-thread-image-intake`
**Status:** Approved design
**Surface:** `mcp-servers/tasks/static/video.html` (the create state), served at
`/video-generator` (host Caddy route) and `/tasks/static/video.html`.

## Problem

The create page overwhelms a beginner: it shows Title, Style, Voice (6 sample
players), a screenshot uploader, a URL field, AND a prompt — plus TWO competing
buttons ("Capture from website" vs "Generate video"), where "Generate video"
demands a manually-uploaded image. Users hit "needs a screenshot" even after
giving a URL, because the URL path and the manual-submit path are separate.

Goals: make it so simple "a granny could understand" — one obvious path — and
stop requiring a manually-uploaded screenshot (#4): giving a website link is
enough.

## Design

Collapse the create state to one primary path:

```
Make a video

Your website link
[ https://yoursite.com                    ]
We grab the screenshots for you.

What should it say?  (optional)
[ e.g. walk through my portfolio          ]

[        Make my video        ]

> More options   (upload your own images, style, voice, title)
```

### Behavior — one button, "Make my video"
`makeVideo()` unifies the two old buttons/paths:
1. Read `url` (the website link), `prompt` (description), and the advanced
   fields (title/style/voice/manual images).
2. **URL given (primary path):** title defaults to the URL host if blank; prompt
   defaults to `A short walkthrough of <host>.` if blank. Then
   `POST /draft` -> `POST /{id}/capture-from-url` -> `POST /{id}/queue` ->
   `openExistingJob(id)` (shows render progress). One click = video.
3. **No URL but manual images staged (under More options):** the existing
   `/upload` flow (prompt defaults to "A short walkthrough." if blank).
4. **Neither:** form error "Add your website link (or upload images under More
   options)."

Button shows a "Capturing... / Making your video..." busy state; errors surface
via the existing `showFormError`/`toast` (capture 400/502/503/504 mapped as in
`captureFromUrl`).

### Optional screenshots (#4)
The primary path never requires a manual upload — the link provides screenshots
(backend `/queue` still needs >=1, satisfied by capture). Manual upload remains
available under "More options" for users who prefer their own images. Truly
screenshot-free (animation-only) video is out of scope here — it belongs to the
later animated-generation project (#5).

### Layout
- Primary, always-visible: the website-link field, the optional description, and
  the single **Make my video** button.
- A `<details>` "More options" (collapsed) wraps the EXISTING controls unchanged
  in behavior: the screenshot uploader (`#add-shots-btn`/`#shot-grid`/`#files`),
  style select (`#style`), voice picker (`#voice-list`), title (`#title`).
- All existing element ids are preserved so the rest of the page's JS is
  untouched; only the create-state markup is reorganized and the submit wiring is
  unified into `makeVideo()`.

## Architecture (front-end only)

- New `makeVideo()` async function: validates, defaults title/prompt, branches
  URL vs manual, chains the existing helpers (`captureFromUrl`, `fetchJob`,
  `openExistingJob`) + a `/queue` call, drives the busy state.
- The current form-submit handler's `/upload` logic is extracted into
  `uploadAndOpen()` and called from `makeVideo()`'s manual branch (DRY; no
  behavior change to the manual path).
- `<form>` submit and the **Make my video** button both call `makeVideo()` (Enter
  still works).
- No backend change. No change to the studio/refine view or the `collecting`
  Generate button (still used by the Discord-style flow and "More options").

## Error handling

- Capture failure -> toast (the existing status->message map), button re-enabled,
  no draft left rendering.
- `/queue` failure (e.g. capture returned 0 frames) -> toast, stay put.
- Daily limit (429) / disabled (503) -> the message from the endpoint.

## Testing

- No JS unit harness (single HTML file). Verify with: per-edit `node --check` of
  the extracted app script; a local headless-Chromium boot smoke (serve the
  static dir, load `video.html`, assert: the primary link field + "Make my video"
  button render; "More options" is a collapsed `<details>`; clicking Make-my-video
  with no URL and no images shows the form error; ZERO uncaught JS errors).
- Manual/Playwright pass on the deployed page after deploy.

## Deploy

Front-end only: CRLF drift-check `video.html` vs the last-deployed baseline, scp
it, rebuild `tasks` (the file is COPYed into the image), confirm the served page
carries the new primary controls + healthz ok.

## Out of scope (YAGNI)

- Screenshot-free / animation-only generation (-> the #5 animated-generation
  project).
- Any backend or studio-view change.
- Auto-generating without a description on the manual path beyond a simple
  default string.
