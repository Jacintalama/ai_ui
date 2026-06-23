# Web Video Studio URL-Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring "capture from website" to the web Video Studio at Discord parity — start a video from a URL in the create form, and add captured frames to an open video from the studio.

**Architecture:** Frontend-only changes to one file, `mcp-servers/tasks/static/video.html` (vanilla JS). Reuses the already-deployed backend endpoints `/draft`, `/{id}/capture-from-url`, `/{id}/queue`, `GET /{id}`. Adds a shared `captureFromUrl()` helper, a create-form "From website" entry, a studio capture control, and `collecting`-status handling (a Generate button) the web studio currently lacks.

**Tech Stack:** Vanilla JS + HTML in `video.html`. No JS unit harness — verification is a JS syntax check (`node --check` on the extracted app script), structural greps, then deploy + browser e2e.

All paths are in the `IO-integrate` worktree (`C:/Users/alama/Desktop/Lukas Work/IO-integrate`), branch `fix/video-thread-image-intake`.

---

## File Structure

Only `mcp-servers/tasks/static/video.html` changes. Within it:
- **JS helper** `captureFromUrl(jobId, url)` — POSTs the capture endpoint, maps HTTP status → user message, returns the JSON. Used by both entry points.
- **Studio composer** — a URL input + "Capture from website" button wired to `captureFromUrl` + `fetchJob` refresh.
- **`openExistingJob` + `renderCollecting`** — handle `status === "collecting"`: show a panel with the screenshot count + a Generate button (`POST /{id}/queue`).
- **Create form** — a "From website" input + button: `POST /draft` → `captureFromUrl` → `openExistingJob`.

## Verification approach (no JS unit harness)

After each code edit, syntax-check the app script. Save this helper script once at the repo root scratch path and reuse it:

`C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py`:
```python
import re, subprocess, sys, tempfile, pathlib
html = pathlib.Path(r"C:/Users/alama/Desktop/Lukas Work/IO-integrate/mcp-servers/tasks/static/video.html").read_text(encoding="utf-8")
blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
app = next((b for b in blocks if "const API" in b), max(blocks, key=len))
f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
f.write(app); f.close()
sys.exit(subprocess.run(["node", "--check", f.name]).returncode)
```
Run: `python C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py` → exit 0 = the app `<script>` parses.

---

## Task 1: Shared `captureFromUrl()` helper

**Files:**
- Modify: `mcp-servers/tasks/static/video.html` (insert before `// --- Add screenshots (paperclip) ---`, ~line 1206)

- [ ] **Step 1: Add the helper**

Insert immediately above the `// --- Add screenshots (paperclip) ---` comment:

```javascript
    // --- Capture screenshots from a live site URL (server-side headless browser).
    // Shared by the create-form "From website" entry and the studio capture button.
    // Throws Error (with .status) on failure; the message is user-facing. ---
    async function captureFromUrl(jobId, url) {
      const r = await fetch(API + "/" + encodeURIComponent(jobId) + "/capture-from-url", {
        method: "POST", headers: authHeaders(), credentials: "include",
        body: JSON.stringify({ url: url }),
      });
      if (!r.ok) {
        let msg;
        if (r.status === 400) msg = "That URL can't be captured.";
        else if (r.status === 502) msg = "Couldn't capture that site.";
        else if (r.status === 503) msg = "Site capture is disabled.";
        else if (r.status === 504) msg = "Capture timed out — try again.";
        else { const t = await r.text(); msg = "Capture failed: " + t.slice(0, 160); }
        const err = new Error(msg); err.status = r.status; throw err;
      }
      return r.json();
    }

```

- [ ] **Step 2: Syntax check**

Run: `python C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py`
Expected: exit 0 (no output / no parse error).

- [ ] **Step 3: Confirm it's defined**

Run: `grep -n "async function captureFromUrl" "mcp-servers/tasks/static/video.html"`
Expected: one match.

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/tasks/static/video.html
git commit -m "feat(web-video): captureFromUrl helper (shared)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Studio "Capture from website" control

**Files:**
- Modify: `mcp-servers/tasks/static/video.html` (composer HTML ~line 664; element refs ~line 722; handler near `addScreenshots`)

- [ ] **Step 1: Add the control to the composer**

Find (in the studio chat rail composer, ~line 664):
```html
        <input type="file" id="shot-input" accept="image/*" multiple hidden>
      </div>
    </aside>
```
Replace with:
```html
        <input type="file" id="shot-input" accept="image/*" multiple hidden>
        <div class="composer-row" style="margin-top:6px;">
          <input type="url" class="form-input" id="capture-url" placeholder="https://yoursite.com"
                 style="flex:1;" aria-label="Capture screenshots from a website URL">
          <button class="btn sm" type="button" id="capture-url-btn">Capture from website</button>
        </div>
      </div>
    </aside>
```

- [ ] **Step 2: Add element refs**

Find (~line 722):
```javascript
    const submitBtn = document.getElementById("submit-btn");
    const formError = document.getElementById("form-error");
```
Insert immediately after `const formError = ...`:
```javascript
    const captureUrlInput = document.getElementById("capture-url");
    const captureUrlBtn = document.getElementById("capture-url-btn");
    const createCaptureUrl = document.getElementById("create-capture-url");
    const createCaptureBtn = document.getElementById("create-capture-btn");
    const collectingPanel = document.getElementById("collecting-panel");
    const collectingCount = document.getElementById("collecting-count");
    const collectingGenerateBtn = document.getElementById("collecting-generate-btn");
```
(Refs for Tasks 3 & 4 are added here too so the refs live in one place; their elements are created in those tasks.)

- [ ] **Step 3: Wire the studio capture handler**

Insert immediately AFTER the `addScreenshots` function (after its closing `}` at ~line 1236):
```javascript
    // --- Capture from website (studio): add captured frames to the open job ---
    async function runStudioCapture() {
      const url = (captureUrlInput.value || "").trim();
      if (!url) { toast("Enter a site URL.", "warn"); return; }
      if (!currentJobId) { toast("Open or create a video first.", "warn"); return; }
      captureUrlBtn.disabled = true;
      const orig = captureUrlBtn.textContent;
      captureUrlBtn.textContent = "Capturing…";
      try {
        const res = await captureFromUrl(currentJobId, url);
        const n = res && res.count != null ? res.count : "the";
        toast("Added " + n + " screenshot(s) from the site.", "success", 4500);
        captureUrlInput.value = "";
        const data = await fetchJob(currentJobId);
        if (data.status === "collecting") renderCollecting(data);
      } catch (e) {
        toast(e.message || "Capture failed.", "error");
      } finally {
        captureUrlBtn.disabled = false;
        captureUrlBtn.textContent = orig;
      }
    }
    captureUrlBtn.addEventListener("click", runStudioCapture);

```

- [ ] **Step 4: Syntax check**

Run: `python C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py`
Expected: exit 0. (References `renderCollecting`, defined in Task 3 — `node --check` only parses, so a forward reference to a function defined later in the same script is fine.)

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/video.html
git commit -m "feat(web-video): studio Capture-from-website control

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `collecting`-status studio support (Generate button)

**Files:**
- Modify: `mcp-servers/tasks/static/video.html` (collecting panel HTML before `version-section` ~line 640; status branch in `openExistingJob` ~line 1277; new `renderCollecting` + queue handler; `resetToCreate` ~line 1308)

- [ ] **Step 1: Add the collecting panel HTML**

Find (~line 640):
```html
      <section class="card" data-show="studio" id="version-section" hidden>
        <div class="section-label">Versions</div>
        <div class="version-bar" id="version-bar"></div>
      </section>
```
Insert immediately BEFORE it:
```html
      <section class="card" data-show="studio" id="collecting-panel" hidden>
        <div class="section-label">Ready to generate</div>
        <div class="uploader-head">
          <span class="uploader-count" id="collecting-count">0 / 12 screenshots</span>
          <button class="btn primary" type="button" id="collecting-generate-btn">Generate video</button>
        </div>
        <span class="form-hint">Add more with the URL field or attach button in the chat, then Generate.</span>
      </section>
```

- [ ] **Step 2: Add the `collecting` branch to `openExistingJob`**

Find (~line 1277):
```javascript
      if (data.status === "done") {
        if (data.output_available) showVideo(null);
        else showPlaceholder("empty", "Render finished but no output is available.");
      } else if (data.status === "failed") {
```
Replace the `if (data.status === "done") {` line with a collecting branch first:
```javascript
      if (data.status === "collecting") {
        renderCollecting(data);
      } else if (data.status === "done") {
        if (data.output_available) showVideo(null);
        else showPlaceholder("empty", "Render finished but no output is available.");
      } else if (data.status === "failed") {
```

- [ ] **Step 3: Add `renderCollecting` + the Generate (queue) handler**

Insert immediately AFTER the `openExistingJob` function (after its closing `}` at ~line 1288):
```javascript
    // --- Collecting state: a draft with screenshots but not yet queued. Show the
    // count + a Generate button (POST /queue) instead of polling. ---
    function renderCollecting(data) {
      stopPolling();
      const shots = Number(
        data.screenshot_count != null ? data.screenshot_count
          : Array.isArray(data.screenshots) ? data.screenshots.length : 0
      ) || 0;
      collectingCount.textContent = shots + " / " + MAX_FILES + " screenshots";
      collectingGenerateBtn.disabled = shots < 1;
      collectingGenerateBtn.textContent = "Generate video";
      collectingPanel.hidden = false;
      showPlaceholder("empty", shots > 0
        ? "Screenshots captured. Hit Generate when ready."
        : "Add at least one screenshot (paste a URL or attach), then Generate.");
    }

    async function runCollectingGenerate() {
      if (!currentJobId) return;
      collectingGenerateBtn.disabled = true;
      collectingGenerateBtn.textContent = "Starting…";
      try {
        const r = await fetch(API + "/" + encodeURIComponent(currentJobId) + "/queue", {
          method: "POST", headers: authHeaders(), credentials: "include",
        });
        if (!r.ok) {
          const t = await r.text();
          toast("Couldn't start: " + t.slice(0, 160), "error");
          collectingGenerateBtn.disabled = false;
          collectingGenerateBtn.textContent = "Generate video";
          return;
        }
        collectingPanel.hidden = true;
        setPill("queued");
        showPlaceholder("rendering", humanStatus("queued"));
        startPolling(currentJobId, { mode: "initial" });
      } catch (e) {
        toast("Couldn't start: " + (e.message || String(e)), "error");
        collectingGenerateBtn.disabled = false;
        collectingGenerateBtn.textContent = "Generate video";
      }
    }
    collectingGenerateBtn.addEventListener("click", runCollectingGenerate);

```

- [ ] **Step 4: Hide the panel on reset**

Find in `resetToCreate` (~line 1308):
```javascript
      sceneSection.hidden = true; sceneStrip.innerHTML = "";
      versionSection.hidden = true; versionBar.innerHTML = "";
```
Insert immediately after those two lines:
```javascript
      if (collectingPanel) collectingPanel.hidden = true;
      if (captureUrlInput) captureUrlInput.value = "";
      if (createCaptureUrl) createCaptureUrl.value = "";
```

- [ ] **Step 5: Syntax check**

Run: `python C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add mcp-servers/tasks/static/video.html
git commit -m "feat(web-video): collecting-state studio panel + Generate (queue)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Create-form "From website" entry

**Files:**
- Modify: `mcp-servers/tasks/static/video.html` (create-form HTML after the Screenshots field ~line 578; handler near the form submit ~line 1646)

- [ ] **Step 1: Add the "From website" section to the create form**

Find (~line 578, the close of the Screenshots `<div class="field">`):
```html
            <div class="shot-empty" id="shot-empty">No screenshots yet. Click "Add screenshots" to begin.</div>
            <div class="error" id="shot-error" hidden></div>
          </div>
```
Insert immediately AFTER that closing `</div>`:
```html
          <div class="field">
            <label class="form-label" for="create-capture-url">Or capture from a website</label>
            <div class="uploader-head">
              <input type="url" class="form-input" id="create-capture-url"
                     placeholder="https://yoursite.com" style="flex:1;">
              <button class="btn sm" type="button" id="create-capture-btn">Capture from website</button>
            </div>
            <span class="form-hint">Enter your site URL and we grab the screenshots for you (needs a title + prompt). Opens the studio — no manual upload.</span>
          </div>
```

- [ ] **Step 2: Wire the create-form capture handler**

Insert immediately AFTER the `form.addEventListener("submit", ...)` block closes (after its `});` at ~line 1646):
```javascript
    // --- Create from a website URL: draft -> capture -> open studio (collecting) ---
    createCaptureBtn.addEventListener("click", async () => {
      clearFormError();
      const title = titleInput.value.trim();
      const prompt = promptInput.value.trim();
      const url = (createCaptureUrl.value || "").trim();
      if (!title) return showFormError("A title is required.");
      if (!prompt) return showFormError("A prompt is required.");
      if (!url) return showFormError("Enter a website URL to capture.");
      createCaptureBtn.disabled = true;
      const orig = createCaptureBtn.textContent;
      createCaptureBtn.textContent = "Capturing…";
      try {
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
        history.pushState({}, "", "?job=" + encodeURIComponent(draft.id));
        openExistingJob(draft.id);
      } catch (e) {
        showFormError(e.message || "Capture failed.");
      } finally {
        createCaptureBtn.disabled = false;
        createCaptureBtn.textContent = orig;
      }
    });

```

- [ ] **Step 3: Confirm the `/draft` response carries `id`**

Run: `grep -n "\"id\"" "mcp-servers/tasks/routes_video.py" | head` and confirm the `/draft` endpoint (`create_draft`/`draft`) returns a body containing the job `id` (the Discord client reads `draft["id"]`, so it does). If the key differs, adjust `draft.id` accordingly.
Expected: the draft route returns the new job's `id`.

- [ ] **Step 4: Syntax check**

Run: `python C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/static/video.html
git commit -m "feat(web-video): create-form Capture-from-website (draft -> capture -> studio)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Verify + deploy + e2e

**Files:** none (verification + deploy)

- [ ] **Step 1: Final syntax + structural check**

Run:
```bash
python C:/Users/alama/AppData/Local/Temp/claude/check_video_js.py
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate" && grep -nE "id=\"(create-capture-url|create-capture-btn|capture-url|capture-url-btn|collecting-panel|collecting-generate-btn)\"" mcp-servers/tasks/static/video.html
```
Expected: syntax exit 0; all six element ids present exactly once.

- [ ] **Step 2: CRLF-normalized drift check before overwrite**

Run:
```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
git show a29539e35:mcp-servers/tasks/static/video.html | tr -d '\r' | sha256sum | cut -c1-16
ssh root@46.224.193.25 "tr -d '\r' < /root/proxy-server/mcp-servers/tasks/static/video.html | sha256sum | cut -c1-16"
```
Expected: the two hashes MATCH (server's `video.html` is the unmodified baseline). If they differ, there is VPS drift — stop and reconcile before overwriting (do not clobber server-only edits).

- [ ] **Step 3: Deploy (gated on user approval — outward-facing)**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
scp mcp-servers/tasks/static/video.html root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/video.html
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks 2>&1 | tail -5"
```
(`video.html` is baked into the image via `COPY . .`, so a rebuild is required for the change to take effect.)

- [ ] **Step 4: Post-deploy hash verify**

Run:
```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-integrate"
tr -d '\r' < mcp-servers/tasks/static/video.html | sha256sum | cut -c1-16
ssh root@46.224.193.25 "tr -d '\r' < /root/proxy-server/mcp-servers/tasks/static/video.html | sha256sum | cut -c1-16"
ssh root@46.224.193.25 "curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz"
```
Expected: hashes match; healthz `{"status":"ok"}`.

- [ ] **Step 5: Browser e2e (playwright-skill, or manual)**

Use the playwright-skill to load the deployed Video Studio (logged-in session) and run:
1. Create form: fill Title + Prompt, enter a real URL in "Or capture from a website", click **Capture from website** → studio opens, **collecting panel** shows a screenshot count > 0.
2. Click **Generate video** → panel hides, status pill leaves collecting (render starts).
3. On a fresh collecting job, use the studio **Capture from website** field → count increases.
4. Bad URL (`http://localhost`) in either field → a toast/form-error rejection, no crash.

If a logged-in Playwright session is impractical, do steps 1–4 as a manual pass and record the result.

- [ ] **Step 6: Update memory**

Append the web-capture milestone to `C:/Users/alama/.claude/projects/C--Users-alama-Desktop-Lukas-Work-IO/memory/project_discord_video_channel.md`.

---

## Self-Review (filled by author)

- **Spec coverage:** create-form entry (T4), studio button (T2), collecting+Generate studio support (T3), shared `captureFromUrl` (T1), error→toast/form-error mapping (T1 helper + handlers), deploy + e2e (T5). All spec sections covered. ✓
- **Placeholders:** none — every step has concrete code/commands. The only "confirm" step (T4S3) verifies an existing backend response shape, not unwritten code. ✓
- **Name consistency:** `captureFromUrl`, `runStudioCapture`, `renderCollecting`, `runCollectingGenerate`, and ids `capture-url`/`capture-url-btn`/`create-capture-url`/`create-capture-btn`/`collecting-panel`/`collecting-count`/`collecting-generate-btn` are used identically across HTML, refs (T2S2), and handlers. ✓
- **No-harness honesty:** there is no JS unit test; verification is `node --check` (syntax) + structural greps + browser e2e. Stated up front. ✓
