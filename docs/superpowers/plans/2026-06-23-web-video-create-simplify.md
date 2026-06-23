# Granny-Simple Web Video Create Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the web video create page to one obvious path — a website link + (optional) description + one "Make my video" button — with everything else under "More options", and never require a manually-uploaded screenshot.

**Architecture:** Front-end only in `mcp-servers/tasks/static/video.html`. Restructure the create-state markup (primary fields + a `<details>` "More options" wrapping the existing controls, all ids preserved) and unify the two old buttons/handlers into one `makeVideo()` that branches URL-capture vs manual-upload. No backend / studio-view change.

**Tech Stack:** Vanilla JS + HTML. No JS unit harness — verify via `node --check` of the app script + a headless-Chromium boot smoke.

All paths in the `IO-integrate` worktree, branch `fix/video-thread-image-intake`.

## Verification helper (reused)

`python C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py` → "SYNTAX OK" / exit 0 (extracts the app `<script>` and runs `node --check`).

---

## Task 1: Restructure the create-form markup

**Files:** Modify `mcp-servers/tasks/static/video.html` (the create form, ~lines 539-603)

- [ ] **Step 1: Replace the card subtitle**

Find (line ~540):
```html
        <div class="card-sub">Name your video, upload 1 to 12 screenshots, describe the narrated slideshow you want.</div>
```
Replace with:
```html
        <div class="card-sub">Paste your website link and we make a narrated video. That's it.</div>
```

- [ ] **Step 2: Replace the whole form body**

Find the entire block from `<form id="video-form" autocomplete="off">` (line ~541) through its closing `</form>` (line ~603) and replace with:

```html
        <form id="video-form" autocomplete="off">
          <div class="field">
            <label class="form-label" for="create-capture-url">Your website link</label>
            <input type="url" class="form-input" id="create-capture-url"
                   placeholder="https://yoursite.com">
            <span class="form-hint">We grab the screenshots for you — no upload needed.</span>
          </div>

          <div class="field">
            <label class="form-label" for="prompt">What should it say? <span style="opacity:.6">(optional)</span></label>
            <textarea class="form-textarea" id="prompt" name="prompt" maxlength="2000"
              placeholder="e.g. walk through my portfolio and highlight the projects"></textarea>
          </div>

          <div class="error box" id="form-error" hidden></div>

          <div class="field" style="margin-top: 4px;">
            <button class="btn primary" type="submit" id="submit-btn">Make my video</button>
          </div>

          <details class="more-options" style="margin-top:14px;">
            <summary style="cursor:pointer; color: var(--text-2); font-size: 13px;">More options</summary>

            <div class="field" style="margin-top:12px;">
              <label class="form-label" for="title">Title <span style="opacity:.6">(optional)</span></label>
              <input class="form-input" id="title" name="title" maxlength="200"
                     placeholder="Auto from your site if left blank">
            </div>

            <div class="field">
              <label class="form-label">Upload your own images instead</label>
              <div class="uploader-head">
                <button class="btn sm" type="button" id="add-shots-btn">+ Add screenshots</button>
                <span class="uploader-count" id="shot-count">0 / 12</span>
              </div>
              <input id="files" name="files" type="file" accept="image/*" multiple hidden>
              <span class="form-hint">Optional — up to 12 images. Used only if you don't give a website link.</span>
              <div class="shot-grid" id="shot-grid"></div>
              <div class="shot-empty" id="shot-empty">No images added.</div>
              <div class="error" id="shot-error" hidden></div>
            </div>

            <div class="field">
              <label class="form-label" for="style">Style</label>
              <select class="form-input" id="style" name="style">
                <option value="clean_product_demo" selected>Clean product demo (recommended)</option>
                <option value="cinematic">Cinematic</option>
                <option value="snappy_social">Snappy social</option>
              </select>
            </div>

            <div class="field">
              <label class="form-label">Voice</label>
              <div class="voice-list" id="voice-list" role="radiogroup" aria-label="Narration voice">
                <div class="voice-loading">Loading voices...</div>
              </div>
            </div>
          </details>
        </form>
```

(Every id is preserved: `create-capture-url`, `prompt`, `form-error`, `submit-btn`, `title`, `add-shots-btn`, `shot-count`, `files`, `shot-grid`, `shot-empty`, `shot-error`, `style`, `voice-list`. Removed: the separate `create-capture-btn` button and the `required` attributes — `makeVideo()` validates instead.)

- [ ] **Step 3: Simplify "How it works"**

Find (line ~615):
```html
        <ol class="how-steps">
          <li><b>Name</b> your video.</li>
          <li>Pick a <b>style</b> and a <b>voice</b> (press play to hear each).</li>
          <li><b>Add screenshots</b> in the order you want narrated.</li>
          <li><b>Describe</b> the walkthrough you want.</li>
          <li>Hit <b>Generate</b> and we render a narrated video.</li>
        </ol>
```
Replace with:
```html
        <ol class="how-steps">
          <li><b>Paste your website link.</b></li>
          <li>Optionally say <b>what it should cover</b>.</li>
          <li>Hit <b>Make my video</b> — we capture the site and render it.</li>
        </ol>
```

- [ ] **Step 4: Syntax check (HTML edits don't touch JS, but the script must still extract)**

Run: `python C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py`
Expected: SYNTAX OK (the JS is unchanged yet; this guards the extraction). It is OK that the page is temporarily broken at runtime — the `createCaptureBtn` handler still references a now-removed element; Task 2 fixes that before any commit.

- [ ] **Step 5: (no commit yet — Task 2 must land in the same commit so boot never breaks)**

---

## Task 2: Unify the handlers into `makeVideo()`

**Files:** Modify `mcp-servers/tasks/static/video.html` (element ref ~line 751; the two handlers ~lines 1722-1807)

- [ ] **Step 1: Remove the dead `createCaptureBtn` element ref**

Find (line ~751):
```javascript
    const createCaptureUrl = document.getElementById("create-capture-url");
    const createCaptureBtn = document.getElementById("create-capture-btn");
```
Replace with (the button no longer exists; keep the URL field ref):
```javascript
    const createCaptureUrl = document.getElementById("create-capture-url");
```

- [ ] **Step 2: Replace BOTH handlers (the `/upload` submit + the create-capture click) with `uploadAndOpen()` + `makeVideo()`**

Find the entire block from `form.addEventListener("submit", async (e) => {` (line ~1722) through the end of the `createCaptureBtn.addEventListener(...)` block's closing `});` (line ~1807) and replace with:

```javascript
    // Manual path: upload the staged images and open the studio.
    async function uploadAndOpen(title, prompt) {
      const fd = new FormData();
      fd.append("title", title);
      fd.append("prompt", prompt);
      fd.append("style", styleSelect ? styleSelect.value : "clean_product_demo");
      fd.append("voice", selectedVoice || defaultVoiceId);
      stopVoicePreview();
      for (const s of shots) fd.append("files", s.file, s.file.name);
      const resp = await fetch(API + "/upload", {
        method: "POST", headers: multipartAuthHeaders(), credentials: "include", body: fd,
      });
      if (resp.status !== 201) {
        const txt = await resp.text();
        throw new Error("Upload failed (" + resp.status + "): " + txt.slice(0, 300));
      }
      const data = await resp.json();
      clearShots();
      history.pushState({}, "", "?job=" + encodeURIComponent(data.id));
      openExistingJob(data.id);
    }

    // One button does it all: a website link (capture + render) OR your own images.
    async function makeVideo() {
      clearFormError();
      const url = (createCaptureUrl.value || "").trim();
      const rawPrompt = promptInput.value.trim();
      let host = "";
      if (url) {
        try { host = new URL(url).hostname.replace(/^www\./, ""); }
        catch (e) { return showFormError("That doesn't look like a valid link (try https://yoursite.com)."); }
      }
      const title = titleInput.value.trim() || host || "Untitled video";
      submitBtn.disabled = true;
      const orig = submitBtn.textContent;
      submitBtn.textContent = "Making your video…";
      try {
        if (url) {
          const prompt = rawPrompt || ("A short walkthrough of " + host + ".");
          const draftResp = await fetch(API + "/draft", {
            method: "POST", headers: authHeaders(), credentials: "include",
            body: JSON.stringify({
              title: title, prompt: prompt,
              style: styleSelect ? styleSelect.value : "clean_product_demo",
              voice: selectedVoice || defaultVoiceId,
            }),
          });
          if (!draftResp.ok) {
            const t = await draftResp.text();
            throw new Error("Couldn't start: " + t.slice(0, 160));
          }
          const draft = await draftResp.json();
          await captureFromUrl(draft.id, url);
          const q = await fetch(API + "/" + encodeURIComponent(draft.id) + "/queue", {
            method: "POST", headers: authHeaders(), credentials: "include",
          });
          if (!q.ok) {
            const t = await q.text();
            throw new Error("Couldn't start the video: " + t.slice(0, 160));
          }
          history.pushState({}, "", "?job=" + encodeURIComponent(draft.id));
          openExistingJob(draft.id);
        } else if (shots.length) {
          if (shots.length > MAX_FILES) throw new Error("You can add at most " + MAX_FILES + " images.");
          if (shotsTotalBytes() > MAX_TOTAL_BYTES) throw new Error("Total size is over 50 MB.");
          const prompt = rawPrompt || "A short walkthrough.";
          await uploadAndOpen(title, prompt);
        } else {
          showFormError("Add your website link above (or upload images under More options).");
        }
      } catch (e) {
        showFormError(e.message || "Couldn't make the video.");
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = orig;
      }
    }

    form.addEventListener("submit", (e) => { e.preventDefault(); makeVideo(); });
```

- [ ] **Step 3: Syntax check**

Run: `python C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py`
Expected: SYNTAX OK.

- [ ] **Step 4: Confirm no dead references remain**

Run: `cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate" && grep -n "create-capture-btn\|createCaptureBtn" mcp-servers/tasks/static/video.html`
Expected: NO matches (the button + its ref/handler are fully gone).

- [ ] **Step 5: Commit (HTML + JS together — page boots cleanly)**

```bash
git add mcp-servers/tasks/static/video.html
git commit -m "feat(web-video): granny-simple create page — one link, one button, optional screenshots

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Browser smoke + deploy

**Files:** none (verification + deploy)

- [ ] **Step 1: Update the local boot smoke**

Overwrite `C:/Users/alama/AppData/Local/Temp/claude/.../scratchpad/smoke_web.py` assertions (or write a fresh `smoke_create.py`) to load `video.html` (served locally) and assert, with ZERO uncaught pageerrors:
```python
# create state visible on boot:
assert await pg.query_selector("#create-capture-url")     # primary link field
assert await pg.query_selector("#submit-btn")             # the one button
btn_text = (await pg.inner_text("#submit-btn")).strip()
assert "make my video" in btn_text.lower()
# advanced controls live inside a collapsed <details>:
det = await pg.query_selector("details.more-options")
assert det is not None
assert await pg.query_selector("details.more-options #style")
assert await pg.query_selector("details.more-options #title")
# the old separate capture button is gone:
assert await pg.query_selector("#create-capture-btn") is None
# empty submit (no url, no images) shows the form error:
await pg.click("#submit-btn")
await pg.wait_for_timeout(150)
assert await pg.is_visible("#form-error")
```

- [ ] **Step 2: Run the smoke**

Run (from `mcp-servers/tasks` so playwright imports):
`python <scratchpad>/smoke_create.py`
Expected: all asserts pass; "PAGE ERRORS (uncaught JS): NONE"; "SMOKE PASS".

- [ ] **Step 3: CRLF drift-check `video.html` vs last-deployed baseline**

Run:
```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
git show HEAD~1:mcp-servers/tasks/static/video.html | tr -d '\r' | sha256sum | cut -c1-16
ssh root@46.224.193.25 "tr -d '\r' < /root/proxy-server/mcp-servers/tasks/static/video.html | sha256sum | cut -c1-16"
```
Expected: hashes MATCH (server = last-deployed video.html). If not, reconcile before overwriting.

- [ ] **Step 4: Deploy**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
scp mcp-servers/tasks/static/video.html root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/video.html
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks 2>&1 | tail -5"
```
(Run the build backgrounded if it exceeds the tool timeout, as before.)

- [ ] **Step 5: Verify live**

```bash
ssh root@46.224.193.25 "curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz && echo && curl -fsS 'https://ai-ui.coolestdomain.win/video-generator?new=1' | grep -oE 'Make my video|more-options|create-capture-url' | sort -u"
```
Expected: healthz ok; the served page shows "Make my video" + "more-options" + "create-capture-url".

- [ ] **Step 6: Push branch + fast-forward main**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
gh auth switch -u Jacintalama
git push fork fix/video-thread-image-intake
git push fork HEAD:main
```

---

## Self-Review (filled by author)

- **Spec coverage:** primary one-button path + auto-defaults (T2 `makeVideo`); optional screenshots / URL-is-enough (T2 URL branch, no manual requirement); More-options collapse of style/voice/title/upload (T1 `<details>`); ids preserved (T1); copy (T1 card-sub + how-steps); verify+deploy (T3). All spec sections covered. ✓
- **Placeholders:** none — every step has concrete markup/code/commands. ✓
- **Name consistency:** `makeVideo`, `uploadAndOpen`, ids `create-capture-url`/`submit-btn`/`title`/`style`/`voice-list`, `details.more-options` used identically across HTML (T1), JS (T2), and smoke (T3). The removed `createCaptureBtn` is deleted in both its ref and handler (T2 S1+S2) and asserted gone (T2 S4). ✓
