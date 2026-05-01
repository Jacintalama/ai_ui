# App Builder UI: Files-as-tab + Lovable-style chat composer

**Status:** approved 2026-05-01
**Scope:** `mcp-servers/tasks/static/preview.html`, `mcp-servers/tasks/routes_tasks.py`, `mcp-servers/tasks/claude_executor.py`
**Approach:** #3 (images-only multimodal — text-file context deferred)

## Goals

1. Move the **Files** sidebar into the tab strip (alongside Code, Supabase, Preview, Structure, Logs, History).
2. Replace the segmented `Chat | Build` toggle with a Lovable-style `Build ▾` dropdown (`Build` / `Plan`).
3. Add a `+` button to the chat composer that opens a popover with an **Attach** action; accept image paste and drag-drop too.
4. Make image attachments reach the AI as real vision input.
5. Remove the em-dash from the browser tab title.

## Non-goals

- Text-file attachments (.txt/.md/.json/.csv) — deferred (Approach 3 cut).
- Per-task chat history browser / sessions UI — out of scope (user explicitly cut).
- Janitor / disk-pruning for `.attachments/` — follow-up PR.
- Drag-to-reorder tabs.

---

## 1. Image-forwarding strategy (the load-bearing decision)

The agent runs as a `claude` CLI subprocess (`claude_executor.py:716`, `run_claude_subprocess`) — the prompt is a single text string. There is no Anthropic-SDK call site we can inject `messages: [{type:"image"}]` into.

The Claude Code CLI agent has a built-in **`Read` tool** that natively ingests image files (PNG/JPG/WebP/GIF) as vision input. So we exploit that:

1. Browser uploads images via multipart `POST /api/tasks/{task}/enhance`.
2. Server stores them at `apps/<slug>/.attachments/<task_id>/<safe_filename>`.
3. `build_enhance_prompt(...)` is extended with an `attachments: list[str] | None` arg. When non-empty, append:
   ```
   ## Attached images
   The user attached these images. Read them with your Read tool before
   responding — the user is referencing them in the request:
   - .attachments/<task_id>/<file1>
   - .attachments/<task_id>/<file2>
   ```
4. Agent's working dir is `apps/<slug>/`, so the relative paths resolve. Agent calls Read → vision input.
5. **Zero change to `run_claude_subprocess` or any SDK call site.**

Trade-off: text files are not forwarded in this round. Same pattern works when we want them — write to `.attachments/`, list paths, let `Read` open them.

---

## 2. Files-tab refactor

### DOM (`preview.html`)

- **Remove:** `<aside class="sidebar-files" id="sb-files">…</aside>` block (~lines 2114–2129) and its sibling `<div class="resizer" data-resize="files">` (~line 2131).
- **Add:** `<button class="tab" data-tab="files">` between Code and Supabase (~line 2140). Same icon currently used in the aside.
- **Add:** `<div class="panel" id="panel-files">` inside `.panels`, after `panel-code`. Body re-uses the existing `#file-search` input + `#file-tree` container — IDs preserved so `loadFileTree()` / `renderFileTree()` / search-filter handler keep working unchanged.

### Behaviour

- Tab order: **Code · Files · Supabase · Preview · Structure · Logs · History**.
- Tree-row click handler appends one line: `switchTab('code')` after `loadCode(path)`.
- Default landing tab stays **Code**.
- `/` shortcut: if active tab isn't Files, switch to Files first, then focus `#file-search`.

### CSS / JS clean-up

- Drop `.sidebar-files`, `.sb-head`, `.sb-title` rules (keep ones that target `#file-tree` and rows — they apply inside the new panel).
- Drop `--sb-files-w` CSS var, `LS_FILES_WIDTH` localStorage key, and the resizer JS for `data-resize="files"` (the block ~line 2994).
- Right-side `data-resize="enhance"` resizer stays.

Net: ~80 LOC removed, ~40 added.

---

## 3. Build / Plan dropdown

### DOM

Replace the existing `.mode-toggle` (lines ~2668–2672) with:

```html
<div class="mode-dropdown" id="mode-dropdown">
  <button class="mode-button" id="mode-button" type="button"
          aria-haspopup="menu" aria-expanded="false">
    <span class="mode-label" id="mode-label">Build</span>
    <svg class="caret" ...><polyline points="6 9 12 15 18 9"/></svg>
  </button>
  <div class="mode-menu" id="mode-menu" role="menu" hidden>
    <button role="menuitem" data-mode="build" class="active">
      <span class="title">Build</span>
      <span class="sub">Make changes directly</span>
    </button>
    <button role="menuitem" data-mode="chat">
      <span class="title">Plan</span>
      <span class="sub">Discuss before building</span>
    </button>
    <div class="menu-foot">Toggle with <kbd>Alt</kbd><kbd>P</kbd></div>
  </div>
</div>
```

### Naming convention

Internal `data-mode` values stay `"build"` and `"chat"` so existing branches on `currentMode` are unaffected. User-facing label for `chat` is **Plan**.

### JS

- `#mode-button` click toggles `#mode-menu` visibility + `aria-expanded`.
- Outside-click + Esc close (one document-level listener, removed when closed).
- `[role="menuitem"]` click sets `currentMode`, updates `#mode-label`, updates `.active`, closes menu.
- New global `Alt+P` keydown toggles modes; same dead-zone rule as existing `?` / `R` / `S` shortcuts (ignored when focus is in an input).
- `setMode(mode)` body unchanged — still flips placeholder, examples, send-button styling.

### CSS

- `.mode-button` matches other ghost-buttons in the header.
- `.mode-menu` `position: absolute`, `top: 100% + 4px`, right-aligned, `min-width: 220px`. Two-row item with title + sub. Footer with kbd hint.

Default mode stays `build`.

---

## 4. Composer — `+` menu, paste, attachment chips

### DOM (`.enhance-input` block ~lines 2685–2700)

```html
<div class="enhance-input">
  <div class="reply-banner" id="reply-banner">…unchanged…</div>

  <div class="attachment-strip" id="attachment-strip" hidden></div>

  <textarea id="enhance-prompt" placeholder="Type what you want to change…"
            maxlength="2000" rows="3"></textarea>

  <div class="row">
    <div class="row-left">
      <button class="icon-btn plus-btn" id="plus-btn" type="button"
              aria-haspopup="menu" aria-expanded="false" title="Add">
        <svg ...><line x1="12" y1="5" x2="12" y2="19"/>
                 <line x1="5" y1="12" x2="19" y2="12"/></svg>
      </button>
      <div class="plus-menu" id="plus-menu" role="menu" hidden>
        <button role="menuitem" id="plus-attach">
          <svg ...><!-- paperclip --></svg>
          <span>Attach</span>
        </button>
      </div>
      <input type="file" id="attach-input" multiple
             accept="image/png,image/jpeg,image/webp,image/gif" hidden>
    </div>
    <span class="warn" id="enhance-warn"></span>
    <button class="btn btn-primary" id="enhance-send">Send</button>
  </div>
</div>
```

### Attachment chips

`#attachment-strip` is a flex row of cards: 56×56 thumbnail, truncated filename, KB size, `×` remove. Thumb URL via `URL.createObjectURL(file)` (revoked on chip removal / send completion).

### Client-side state

```js
let pendingAttachments = []; // [{ id, file: File, kind: 'image', previewUrl }]
```

- `+` → `#plus-attach` → `#attach-input.click()` → `change` handler validates + pushes + renders.
- `paste` handler on `#enhance-prompt`: walk `clipboardData.items`, take any `kind === 'file' && type.startsWith('image/')` via `getAsFile()`, push. Text paste unaffected.
- `dragover` on textarea: `preventDefault` + add `.drag-over` class. `drop`: read `dataTransfer.files`, push valid ones.
- `×` removes by id, revokes URL, re-renders.
- **Send:** if `pendingAttachments.length > 0`, build `FormData`; otherwise POST JSON as today (no contract change for the empty-attachments path).
- After request fires: clear `pendingAttachments`, hide `#attachment-strip`.

### Validation (client-side)

- MIME not in `{image/png, image/jpeg, image/webp, image/gif}` → toast: *"Only PNG / JPEG / WebP / GIF images are supported."*
- File > 5 MB → toast: *"<filename> is too large (max 5 MB)."*
- Total chip count would exceed 5 → toast: *"Up to 5 attachments per message."*

### `+` menu open/close

Same listener pattern as Build/Plan dropdown (outside-click closes, Esc closes, `aria-expanded` toggled). Anchored upward (composer is at panel bottom).

---

## 5. Server — multipart endpoint + storage

### Signature change (`routes_tasks.py:623`)

Today:
```python
class EnhanceRequest(BaseModel):
    source_task_id: UUID
    prompt: str

@router.post("/enhance", response_model=TaskOut, status_code=202)
async def enhance(body: EnhanceRequest, user: AdminUser = Depends(current_admin)):
```

After:
```python
@router.post("/enhance", response_model=TaskOut, status_code=202)
async def enhance(
    source_task_id: UUID = Form(...),
    prompt: str = Form(...),
    files: list[UploadFile] = File(default_factory=list),
    user: AdminUser = Depends(current_admin),
):
```

### JSON-body back-compat

- **Approach A (recommended):** drop JSON support. Client always uses `FormData`. Pre-merge: grep `webhook-handler/` and `n8n-workflows/` for any non-browser caller — if found, switch to **B**.
- **Approach B (fallback):** inspect `Content-Type` and parse accordingly (~10 LOC wrapper at top of handler).

### Validation (server-side, defence in depth)

```python
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 5

if len(files) > MAX_FILES:
    raise HTTPException(400, f"Too many attachments (max {MAX_FILES})")
for f in files:
    if f.content_type not in ALLOWED_MIME:
        raise HTTPException(400, f"Unsupported type: {f.content_type}")
    # read in chunks; abort if cumulative > cap
```

Magic-byte sniff (first 12 bytes) to verify the declared MIME — small inline check, no `python-magic` dep.

### Storage path

```
apps/<built_app_slug>/.attachments/<new_task_id>/<safe_filename>
```

- `<safe_filename>` = sanitized via existing helper or new `_safe_filename(name)` (strip path components, no `..`, no slashes; collision-suffix if exists).
- Created **after** `new_task` row commit (need `new_task.id`), **before** `_run_execution` fires.
- Append `.attachments/` to per-app `.gitignore` template at build time (extend the `gitignore` write in `claude_executor.py`).

### Prompt extension (`claude_executor.py`)

```python
def build_enhance_prompt(..., attachments: list[str] | None = None) -> str:
    ...
    if attachments:
        body += "\n\n## Attached images\n" \
                "The user attached these images. Read them with your Read tool " \
                "before responding — the user is referencing them in the request. " \
                "If a file can't be read, tell the user which one:\n"
        for rel_path in attachments:
            body += f"- {rel_path}\n"
    return body
```

`attachments` are repo-relative paths (e.g. `.attachments/<task_id>/screenshot.png`). Agent CWD is `apps/<slug>/`.

---

## 6. Tab-title em-dash

`preview.html:6`:
```diff
-<title>Preview — AIUI Tasks</title>
+<title>Preview - AIUI Tasks</title>
```

---

## Testing plan (manual)

1. **Files-tab:** click Files → tree+search visible. Click a file → tab auto-switches to Code, file loads. `/` from any tab → Files tab + search focused.
2. **Build/Plan dropdown:** click `Build ▾` → menu. Switch to `Plan` → label updates, sending a message no longer fires a build. `Alt+P` toggles. Esc + outside-click both close.
3. **Composer +:** menu opens upward, Attach triggers picker. 1 PNG → chip with thumbnail. 6 files → 6th rejected. PDF rejected. 10 MB image rejected.
4. **Paste/drop:** screenshot paste into textarea → chip, no text inserted. Desktop drag-drop → chip.
5. **Send with attachment:** "describe this image" + attach → request fires as multipart. File appears at `apps/<slug>/.attachments/<task_id>/`. Tail enhance log → agent uses Read on the file. Reply references image content.
6. **Send without attachment:** unchanged from today; no regression.
7. **Existing tests:** if `mcp-servers/tasks/tests/` has an enhance-endpoint test, switch its request from JSON to FormData.

---

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Existing JSON callers of `/enhance` break (§5 Approach A) | Medium — depends on grep | Pre-merge grep `webhook-handler/`, `n8n-workflows/` for `/enhance` callers. Switch to Approach B if any. |
| `.attachments/` polluting build git history | High if not handled | Append to per-app `.gitignore` at build time. |
| Disk fills up over months | Medium | Follow-up: janitor cron + Grafana panel. |
| Magic-byte sniff misses crafted images | Low | Worst case "AI sees garbage" — no exec path. Acceptable. |
| Claude CLI Read tool fails to load image | Low | Prompt stanza tells agent to surface the failure to the user. |

---

## Out of scope (follow-ups)

- `.attachments/` janitor + Grafana disk dashboard.
- Text-file attachments (Approach 2 full parity).
- Drag-to-reorder tabs.
- Multi-thread chat history per project.
