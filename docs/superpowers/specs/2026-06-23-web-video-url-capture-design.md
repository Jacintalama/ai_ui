# "Capture from website" in the web Video Studio

**Date:** 2026-06-23
**Branch:** `fix/video-thread-image-intake` (IO-integrate worktree)
**Status:** Approved design
**Depends on:** the URL auto-capture backend already shipped + deployed
(`2026-06-23-video-url-auto-capture-design.md`).

## Problem

URL auto-capture (drive headless Chromium to screenshot a live site) is live in
Discord but not on the website. The web Video Studio (`mcp-servers/tasks/static/
video.html`) still only does manual screenshot upload. Bring the same capability
to the web UI, at parity with Discord.

The capture backend is shared and already deployed — `POST /api/video-jobs/{id}/
capture-from-url`. No backend changes are required.

## Constraints discovered

- `video.html` is a single ~1751-line vanilla-JS file (no framework, no JS test
  harness). Verification is by browser automation + manual pass, not unit tests.
- The web "create" path differs from Discord's: the form stages screenshots
  client-side and `POST /upload` creates an **already-queued** job that renders
  immediately. The web studio has **no `collecting`-status handling and no
  Generate/queue affordance** — `openExistingJob` assumes a rendering job and
  polls. Capture needs an existing job id, so a URL-only start requires the
  Discord-style draft → collecting → Generate flow, which the web lacks today.

## User experience (decided: BOTH entry points)

### 1. Create form — "From website"
A new section in the *Generate a video* form: a URL text input + a **Capture from
website** button, beside the manual screenshot uploader. The manual uploader +
**Generate video** submit path is unchanged; this is a parallel way to start.

### 2. Studio — "Capture from website" button
Next to the existing attach (paperclip) control on the job page, a **Capture from
website** button (inline URL input) that adds captured frames to the current job.

## Architecture (frontend only, all in `video.html`)

### A. Create-form capture → draft → studio
`Capture from website` (create form) handler:
1. Read title, prompt, style, voice from the form; read the URL.
2. Validate: title non-empty, prompt non-empty, URL non-empty → else `showFormError`.
3. `POST /api/video-jobs/draft` `{title, prompt, style, voice}` → `{id}`.
4. `POST /api/video-jobs/{id}/capture-from-url` `{url}` (button shows "Capturing…").
5. On success: `history.pushState ?job=<id>` + `openExistingJob(id)`.
6. Errors → `toast(...)`: 400 "That URL can't be captured", 502 "Couldn't capture
   that site", 503 "Site capture is disabled", 504 "Capture timed out — try again",
   other → generic. Re-enable the button in all cases.

### B. Studio support for `collecting` jobs
Extend `openExistingJob`: when `data.status === "collecting"`:
- Do **not** start polling.
- Show the captured screenshot count and a prominent **Generate video** button.
- The button → `POST /api/video-jobs/{id}/queue`; on success switch to the normal
  rendering path (`setPill`, `showPlaceholder("rendering", ...)`, `startPolling`).
- `queue` errors (e.g. 400 "Add a description first" / "add a screenshot first")
  → toast; stay in collecting so the user can fix it.

A small `renderCollecting(data)` helper owns this view so `openExistingJob` stays
readable.

### C. Studio "Capture from website" button
Mirror the existing `addScreenshots` paperclip:
- An inline URL input + button near `attach-btn`.
- `POST /api/video-jobs/{currentJobId}/capture-from-url` `{url}` → on success,
  toast the count and re-fetch the job (`fetchJob`) to refresh the collecting
  count / scenes. Same error→toast mapping as A.
- Available whenever a job is open (most useful in `collecting`, where it adds to
  the draft before Generate; manual + captured frames combine here).

### Shared helper
`captureFromUrl(jobId, url)` — one async function used by both B-button and the
create-form path (after it has the draft id): POSTs the endpoint, returns the
JSON, throws on non-2xx with the status so callers map to the right toast.

## Data flow

```
Create form "From website":
  /draft -> {id}  ->  /{id}/capture-from-url -> openExistingJob(id) [collecting]
                                                   -> Generate -> /{id}/queue -> render

Studio "Capture from website":
  /{currentJobId}/capture-from-url -> re-fetch /{id} -> refresh count
```

## Error handling

All failures surface via the existing `toast()` (studio) or `showFormError()`
(create form). HTTP status → message map is centralized in `captureFromUrl`'s
callers. No silent failures; buttons always re-enable.

## Testing

- **No JS unit harness** for this file. Verify with the **playwright-skill**
  against the running Video Studio (locally served or the deployed page):
  1. Create-form: fill title + description, enter a real URL, click Capture →
     studio opens in collecting with screenshot count > 0.
  2. Click Generate → status leaves collecting (render starts).
  3. Studio button: on a collecting job, capture again → count increases.
  4. Bad URL (`http://localhost`) → toast rejection, no crash.
- Manual pass after deploy as the final confirmation.
- Backend is already covered by the shipped capture tests; this change is UI glue.

## Deploy

Frontend-only: `scp mcp-servers/tasks/static/video.html` to the server, then
`docker compose -f docker-compose.unified.yml up -d --build tasks` (or, since it
is a static asset, confirm whether the file is COPYed into the image — it is, via
`COPY . .`, so a rebuild is needed). Verify by loading the Video Studio and
running the capture flow. CRLF-normalized drift-check `video.html` against the
server before overwriting.

## Out of scope (YAGNI)

- Mixing manual-staged + captured frames in the create form pre-submit (combine in
  the studio instead).
- Any backend change (endpoints already exist and are deployed).
- A jobless "capture preview" endpoint (the draft flow covers the create path).
