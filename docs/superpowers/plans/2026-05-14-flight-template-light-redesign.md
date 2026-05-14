# Flight-booking Template Light Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-skin the `flight-booking` base template to a light, professional theme (Plus Jakarta Sans) and add the missing Saved Trips view so the header counter leads to a real screen.

**Architecture:** Targeted re-skin of one static template app — no layout overhaul, no architecture refactor. Part 1 adds a 5th Alpine view (`saved`) that is purely additive. Part 2 swaps the CSS-variable palette + font and rewrites the dark-mode Tailwind utilities hardcoded throughout `index.html`. The `localStorage` persistence layer already works and is not touched.

**Tech Stack:** Static HTML + Tailwind CDN + Alpine.js + vanilla ES modules. No build step. No npm. Verification is the existing static-structure test plus manual browser preview.

---

## Context for the implementer

- **Spec:** `docs/superpowers/specs/2026-05-14-flight-template-light-redesign-design.md` — read it first.
- The target files are the `flight-booking` **base template**, which currently lives **only on the production server**, not in this branch. Task 1 fetches the full directory.
- The template is a single-page Alpine app: `index.html` (markup), `src/main.js` (Alpine root: router + persistence + handlers), `src/data.js` (seed flight data), `src/lib/` (shared `router.js` / `persistence.js` / `skeleton.js` — **do not modify**), `styles/main.css` (palette CSS variables).
- This change is to the **base template** — already-generated apps (`alama-flight`, `pacific-wings`, `tokyo-air`) are unaffected.
- Server access: `ssh root@46.224.193.25`. Server repo path: `/root/proxy-server/`. Container name: `tasks`.
- **There are no unit tests for template apps.** Verification = the existing `tests/test_functional_templates_static.py` (validates template structure) + manual browser preview of all 5 views. For browser verification use the @superpowers:playwright-skill or open the file directly.

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `mcp-servers/tasks/template_apps/flight-booking/src/main.js` | Alpine root state — add `saved` view + `removeTrip()` | Modify |
| `mcp-servers/tasks/template_apps/flight-booking/index.html` | Markup — header button, new `<section>`, light re-skin of all sections | Modify |
| `mcp-servers/tasks/template_apps/flight-booking/styles/main.css` | Palette CSS variables + font-family | Modify |
| `mcp-servers/tasks/template_apps/flight-booking/{README.md,preview.png,src/data.js,src/lib/*,public/.gitkeep}` | Rest of the template | Fetch only — do not modify |

---

## Task 1: Fetch the base template + baseline check

**Files:**
- Create (fetch): `mcp-servers/tasks/template_apps/flight-booking/` (entire directory)

- [ ] **Step 1: Create the local directory and fetch the full template from the server**

```bash
mkdir -p mcp-servers/tasks/template_apps
scp -r root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/flight-booking \
  mcp-servers/tasks/template_apps/flight-booking
```

- [ ] **Step 2: Verify the fetched structure**

Run: `find mcp-servers/tasks/template_apps/flight-booking -type f | sort`
Expected: `README.md`, `index.html`, `preview.png`, `public/.gitkeep`, `src/data.js`, `src/main.js`, `src/lib/persistence.js`, `src/lib/router.js`, `src/lib/skeleton.js`, `styles/main.css`

- [ ] **Step 3: Baseline — run the static template test**

Run (locally): `cd mcp-servers/tasks && DATABASE_URL="postgresql+asyncpg://x:x@localhost/x" python -m pytest tests/test_functional_templates_static.py -q`
If the test file is not present locally or needs the container, run instead: `ssh root@46.224.193.25 'docker exec tasks bash -lc "cd /app && python -m pytest tests/test_functional_templates_static.py -q"'`
Expected: PASS (this is the baseline — the same test must still pass at the end).

- [ ] **Step 4: Baseline — open the template in a browser**

Open `mcp-servers/tasks/template_apps/flight-booking/index.html` in a browser. Confirm the current **dark** theme renders and you can: search → see results → open a detail → save a trip → see the header counter become `Saved (1)` → click "Saved" and observe it just returns to the search view (the bug being fixed).

- [ ] **Step 5: Commit**

```bash
git add mcp-servers/tasks/template_apps/flight-booking
git commit -m "chore(flight-template): vendor base template for redesign work"
```

---

## Task 2: Add the Saved Trips view

**Files:**
- Modify: `mcp-servers/tasks/template_apps/flight-booking/src/main.js`
- Modify: `mcp-servers/tasks/template_apps/flight-booking/index.html`

This task is purely additive — done in the current dark theme. Task 3 re-skins it.

- [ ] **Step 1: Add `"saved"` to the router views array**

In `src/main.js`, in `_buildAppState()`, change the `createRouter` spread:

```js
  ...createRouter({ initial: "search", views: ["search", "results", "detail", "review", "saved"] }),
```

- [ ] **Step 2: Add the `removeTrip` method**

In `src/main.js`, immediately after the `saveTrip()` method, add:

```js
  removeTrip(flightId) {
    const i = this.savedTrips.findIndex((t) => t.id === flightId);
    if (i < 0) return;
    this.savedTrips.splice(i, 1);
    this._save("savedTrips");
    this.toast("Trip removed");
  },
```

- [ ] **Step 3: Point the header "Saved" button at the saved view**

In `index.html`, in the `<header>` `<nav>`, change the Saved button's click handler:

```html
      <button @click="setView('saved')" class="hidden sm:inline-block hover:text-white">
        Saved <span x-text="savedTrips.length ? `(${savedTrips.length})` : ''"></span>
      </button>
```

(Only the `@click` value changes from `setView('search')` to `setView('saved')`; classes stay as-is for now — Task 3 re-skins them.)

- [ ] **Step 4: Add the Saved view `<section>`**

In `index.html`, immediately after the closing `</section>` of the REVIEW view and before the `<!-- Toast -->` comment, insert:

```html
  <!-- ===================== SAVED VIEW ===================== -->
  <section x-show="view === 'saved'" x-transition.duration.200ms class="max-w-4xl mx-auto px-4 sm:px-6 py-8" x-cloak>
    <button @click="setView('search')" class="text-white/60 hover:text-white mb-6">← Back to search</button>
    <h2 class="text-2xl font-bold text-white mb-6">Saved trips</h2>

    <template x-if="savedTrips.length === 0">
      <p class="text-white/50 text-center py-12">No saved trips yet — save a flight from its detail page.</p>
    </template>

    <div class="space-y-3">
      <template x-for="f in savedTrips" :key="f.id">
        <article @click="openDetail(f.id)"
          class="bg-white/5 hover:bg-white/10 rounded-xl p-4 grid grid-cols-[1fr_auto] gap-4 cursor-pointer transition hover:-translate-y-0.5">
          <div>
            <div class="text-xs text-white/50" x-text="f.airline + ' · ' + f.cabin"></div>
            <div class="text-lg font-semibold text-white mt-1" x-text="`${f.origin} → ${f.destination}`"></div>
            <div class="text-sm text-white/70 mt-1">
              <span x-text="`${f.departureLabel} – ${f.arrivalLabel}`"></span>
              <span class="mx-2">·</span>
              <span x-text="formatDuration(f.duration)"></span>
              <span class="mx-2">·</span>
              <span x-text="f.stops === 0 ? 'Non-stop' : f.stops + ' stop' + (f.stops > 1 ? 's' : '')"></span>
            </div>
          </div>
          <div class="text-right flex flex-col items-end justify-between">
            <div class="text-2xl font-bold text-[var(--accent)]" x-text="`$${f.price}`"></div>
            <button @click.stop="removeTrip(f.id)"
              class="text-xs text-white/50 hover:text-white underline">Remove</button>
          </div>
        </article>
      </template>
    </div>
  </section>
```

Note the `@click.stop` on the Remove button — it prevents the card's `openDetail` click from also firing.

- [ ] **Step 5: Verify in a browser**

Open `index.html`. Walk through: search → results → open a flight detail → "Save trip" → header shows `Saved (1)` → click "Saved" → the Saved view lists the trip → click the card → it reopens the Detail view → go back to Saved → click "Remove" → the trip disappears and the header counter clears → save two trips → reload the page → confirm both are still listed (localStorage persisted).

- [ ] **Step 6: Run the static template test**

Run the same command as Task 1 Step 3.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/template_apps/flight-booking/src/main.js mcp-servers/tasks/template_apps/flight-booking/index.html
git commit -m "feat(flight-template): add Saved Trips view + removeTrip"
```

---

## Task 3: Light theme re-skin

**Files:**
- Modify: `mcp-servers/tasks/template_apps/flight-booking/styles/main.css`
- Modify: `mcp-servers/tasks/template_apps/flight-booking/index.html`

- [ ] **Step 1: Swap the palette + font in `styles/main.css`**

Replace the `:root` block and the `html`/`body` rules. The current `:root` defines `--bg --bg-card --text --accent --muted`. The new version **renames** `--muted` → `--text-muted` and **adds** `--border`:

```css
/* Skylane palette — light, professional */
:root {
  --bg: #f4f5f7;
  --bg-card: #ffffff;
  --border: #e5e7eb;
  --text: #1f2937;
  --text-muted: #6b7280;
  --accent: #2563eb;
}

html { background: var(--bg); }
body { font-family: "Plus Jakarta Sans", ui-sans-serif, system-ui, sans-serif; }
```

Leave the `@media (prefers-reduced-motion)` block, the `[x-cloak]` rule, and the `article { transition }` rule unchanged.

- [ ] **Step 2: Swap the font link in `index.html`**

In `<head>`, replace the Inter Google Fonts `<link>` with Plus Jakarta Sans:

```html
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
```

(Keep the two `preconnect` links above it unchanged.)

- [ ] **Step 3: Re-skin the header**

The header currently uses dark translucency. Change it to a white bar with a bottom border, keeping the scroll-shrink behaviour. Apply the class mapping (Step 4 table) to the `<header>` element and its children: the brand text and nav buttons go from `text-white` / `text-white/80` to `text-[var(--text)]` / `text-[var(--text-muted)]`; the `bg-[var(--bg)] backdrop-blur` becomes `bg-[var(--bg-card)]`; the `border-white/5` becomes `border-[var(--border)]`. The profile chip `bg-white/10` becomes `bg-[var(--border)]`.

- [ ] **Step 4: Re-skin all view sections using this class mapping**

Apply consistently across the search, results, detail, review, **and** saved sections, plus the toast. Search the file for each left-hand pattern and replace:

| Dark utility (find) | Light replacement |
|---------------------|-------------------|
| `text-white` | `text-[var(--text)]` |
| `text-white/80`, `text-white/70`, `text-white/60`, `text-white/50`, `text-white/40` | `text-[var(--text-muted)]` |
| `bg-white/5` (cards, panels, form wrapper, aside) | `bg-[var(--bg-card)] border border-[var(--border)] shadow-sm` |
| `bg-white/10` (result-card hover base, filter pills unselected, profile chip, "Save trip" button) | `bg-[var(--bg-card)] border border-[var(--border)]` |
| `hover:bg-white/10`, `hover:bg-white/20` | `hover:bg-[var(--border)]` |
| `border-white/10`, `border-white/5` | `border-[var(--border)]` |
| inner nested `bg-white/5` blocks (e.g. baggage/total tiles inside the detail card) | `bg-[var(--bg)]` (so they recede against the white card) |
| `text-black` on `<option>` elements | remove the class (default option colour is fine on a light page) |
| `bg-black` on the toast | `bg-[var(--text)]` (dark toast on light page) |

The `[var(--accent)]` references (price text, primary buttons, `accent-[var(--accent)]` on range inputs, the brand logo square) already point at the variable — they update automatically. Leave them.

For the **filter pills** (stops / time-of-day / airlines) the selected state is `bg-[var(--accent)] text-white` — keep that; only the *unselected* state (`bg-white/10 text-white/70`) changes to `bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)]`.

For the **skeleton loaders** (`h-20 bg-white/10 animate-pulse`) change `bg-white/10` to `bg-[var(--border)]`.

For the **seat-map SVG**: change the `<rect width="400" height="100" fill="rgba(255,255,255,0.05)">` to `fill="var(--bg)"` and the seat `<g fill="rgba(255,255,255,0.4)">` to `fill="var(--text-muted)"`.

- [ ] **Step 5: Verify every view in a browser**

Open `index.html`. Confirm: soft cool-gray page background (not white); white cards that lift with a subtle shadow; blue accent on prices and primary buttons; Plus Jakarta Sans throughout; **no** white-on-white or low-contrast text anywhere. Click through all 5 views (search, results + filters, detail, review, saved). Resize to <768px and confirm the header and layout still hold. Re-check the Task 2 flow (save / view / remove / reload) still works in the new theme.

- [ ] **Step 6: Run the static template test**

Run the same command as Task 1 Step 3.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mcp-servers/tasks/template_apps/flight-booking/styles/main.css mcp-servers/tasks/template_apps/flight-booking/index.html
git commit -m "feat(flight-template): light professional theme + Plus Jakarta Sans"
```

---

## Task 4: Deploy + end-to-end verification

**Files:** none modified — deployment + verification only.

- [ ] **Step 1: Deploy the 3 changed files to the server**

```bash
B=mcp-servers/tasks/template_apps/flight-booking
scp $B/index.html $B/src/main.js $B/styles/main.css \
  root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/flight-booking/
```

- [ ] **Step 2: Rebuild + recreate the tasks container**

```bash
ssh root@46.224.193.25 'cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks'
```

- [ ] **Step 3: Confirm the container is healthy and serving the new template**

```bash
ssh root@46.224.193.25 'docker exec tasks curl -sS http://127.0.0.1:8210/health'
ssh root@46.224.193.25 'docker exec tasks grep -c "Plus+Jakarta" /app/template_apps/flight-booking/index.html'
```
Expected: `{"status":"ok","service":"tasks"}` and the grep prints `1`.

- [ ] **Step 4: Run the static test in the deployed container**

```bash
ssh root@46.224.193.25 'docker exec tasks bash -lc "cd /app && python -m pytest tests/test_functional_templates_static.py -q"'
```
Expected: PASS.

- [ ] **Step 5: Generate one fresh flight-booking app end-to-end**

Through the app-builder panel (or the tasks API as used previously), create + execute a BUILD task with `template_key: "flight-booking"` and a fresh slug, with a specific description. Confirm: the task reaches `completed`, the agent customised the **light** base (not the old dark one), and the Saved view is present in the generated app. This proves the agent's CUSTOMIZE MODE still works against the new base.

- [ ] **Step 6: Final commit (if any working-tree changes remain)**

If Steps 1–5 produced no file changes, skip. Otherwise commit any fixes made during verification with an appropriate message.

---

## Done criteria

- [ ] Saved view lists saved trips, supports remove, reopens detail on click, shows an empty state, and persists across reload.
- [ ] Header "Saved" counter navigates to the Saved view.
- [ ] Template renders in the light theme (soft gray bg, white cards, blue accent, Plus Jakarta Sans) with no contrast regressions across all 5 views, mobile included.
- [ ] `test_functional_templates_static.py` passes locally and in the deployed container.
- [ ] A freshly generated flight-booking app inherits the light theme + Saved view, and the build completes cleanly.
