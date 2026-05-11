# Functional Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 new "alive, purposeful" templates (`flight-booking`, `food-delivery`, `job-board`, `movie-tickets`, `recipe-site`) to the App Builder gallery. Each is a single-page Alpine.js state machine with real filters, real cart, real localStorage persistence, and a 800-1400ms fake-network delay so skeleton loaders have airtime. The user experience is "this feels like a working app" — not a static showcase.

**Spec:** `docs/superpowers/specs/2026-05-11-functional-templates-design.md`

**Architecture:** Each template is self-contained under `mcp-servers/tasks/template_apps/<key>/`. Three reusable Alpine primitives (`router.js`, `persistence.js`, `skeleton.js`) are **copied verbatim** into each template's `src/lib/` — no shared `_shared/` directory, no cross-template imports. The publish/build pipeline already handles `template_apps/<key>/*` as a single self-contained tree. Catalog registration (rules + SVG + `Template(...)` entry) makes them appear in the gallery.

**Tech Stack:** Static HTML5 + Tailwind CDN + Alpine.js 3.x + vanilla ES modules. No build step, no npm install. Local screenshot capture via Python + Playwright. Tests: pytest against the FastAPI tasks service, with optional Playwright "alive interaction" coverage.

**Branch strategy:** Worktree at `IO-functional-templates/` branched from `feat/design-templates` (so the 24-template baseline, capture-local-templates.py, and PREVIEW_VER plumbing are inherited).

---

## File Structure

### Files to create (per-template, ×5)

```
mcp-servers/tasks/template_apps/<key>/
  index.html                       # single-page state machine, 4-6 x-show views
  styles/main.css                  # palette tokens, transitions, skeleton pulse
  src/main.js                      # window.appState() Alpine root
  src/data.js                      # demo data array(s), stable ids
  src/lib/router.js                # createRouter() — copied verbatim, see Block A
  src/lib/persistence.js           # createPersistence() — copied verbatim, see Block B
  src/lib/skeleton.js              # simulateNetwork() — copied verbatim, see Block C
  README.md                        # 1-paragraph description + photo-ID provenance
  public/.gitkeep                  # empty placeholder so the dir exists
  preview.png                      # 1280×800 Playwright screenshot (Task 10)
```

### Files to modify

- `mcp-servers/tasks/templates.py` — add `_RULES_<KEY>`, `_SVG_<KEY>` constants, append 5 `Template(...)` entries (placed before `agency` so functional templates sort first)
- `mcp-servers/tasks/tests/test_templates.py` — `EXPECTED_KEYS` 24→29, `test_24_templates_present` → `test_29_templates_present`
- `mcp-servers/tasks/static/templates.html` — `FEATURED_KEYS` 10→15, `PREVIEW_VER "4"` → `"5"`, optional "Functional apps" heading row
- `mcp-servers/tasks/static/projects.html` — `FEATURED_TEMPLATE_KEYS` 10→15, `PREVIEW_VER "4"` → `"5"`
- `_tplpng/capture-local-templates.py` — append 5 new keys to `TEMPLATES` + `DEMO_NAMES`, add per-template driver step

### Files to create (tests + tooling)

- `mcp-servers/tasks/tests/test_functional_templates_static.py` — parametrized static checks (9 × 5 = 45 assertions)
- `mcp-servers/tasks/tests/test_functional_templates_alive.py` — Playwright interaction tests (5 tests, one per template)

### Reusable code blocks (copied verbatim into each template's `src/lib/`)

These are the canonical source. Each template task pastes them verbatim — no edits, no shared dir.

#### Block A: `src/lib/router.js`

```js
// View router with history-stack-based back navigation.
// Used by every template's main.js via ...createRouter({ initial, views }).
export function createRouter({ initial, views }) {
  return {
    view: initial,
    history: [initial],

    setView(name) {
      if (!views.includes(name)) return;
      if (this.view !== name) {
        this.history.push(name);
        this.view = name;
        if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          window.scrollTo({ top: 0, behavior: 'smooth' });
        } else {
          window.scrollTo(0, 0);
        }
      }
    },

    back() {
      if (this.history.length <= 1) return;
      this.history.pop();
      this.view = this.history[this.history.length - 1];
      window.scrollTo(0, 0);
    },
  };
}
```

#### Block B: `src/lib/persistence.js`

```js
// localStorage hydration/save scoped by namespace.
// Wraps every read/write in try/catch — private browsing or quota issues
// must NOT crash the app.
export function createPersistence({ namespace, keys }) {
  const ns = (k) => `io-template:${namespace}:${k}`;
  const obj = {
    _hydrate() {
      for (const k of keys) {
        try {
          const raw = localStorage.getItem(ns(k));
          if (raw !== null) this[k] = JSON.parse(raw);
        } catch { /* private browsing / corrupted entry: ignore */ }
      }
    },
    _save(k) {
      try {
        localStorage.setItem(ns(k), JSON.stringify(this[k]));
      } catch { /* quota exceeded or disabled: ignore */ }
    },
  };
  for (const k of keys) obj[k] = [];   // default empty array per key
  return obj;
}
```

#### Block C: `src/lib/skeleton.js`

```js
// Fake network delay. Used to gate data swaps so skeleton placeholders
// have time to render (otherwise the data flashes through instantly).
// Honors prefers-reduced-motion: short delay (50ms) so the loading state
// still toggles for assertion purposes, just imperceptibly.
export async function simulateNetwork(minMs = 800, maxMs = 1400) {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const ms = reduced ? 50 : minMs + Math.random() * (maxMs - minMs);
  await new Promise((r) => setTimeout(r, ms));
}
```

#### Block D: compact app header pattern (shared shape across all 5 templates)

```html
<!-- Place at top of <body>, before any view sections. -->
<header
  x-data="{ scrolled: false }"
  x-init="window.addEventListener('scroll', () => { scrolled = window.scrollY > 32; }, { passive: true })"
  :class="scrolled ? 'h-12 shadow-sm' : 'h-14 shadow-none'"
  class="sticky top-0 z-30 bg-white/95 backdrop-blur transition-all duration-150 flex items-center px-4 sm:px-6"
>
  <a href="#" class="flex items-center gap-2 font-semibold" @click.prevent="setView('search')">
    <span class="inline-block w-6 h-6 rounded bg-[var(--accent)]"></span>
    <!-- Per-template: replace BRAND_NAME with Skylane / Roost / Workpath / etc. -->
    <span>BRAND_NAME</span>
  </a>

  <nav class="ml-auto flex items-center gap-4 text-sm">
    <!-- Optional: contextual breadcrumb pill -->
    <button @click="setView('search')" class="hidden sm:inline-block text-gray-500 hover:text-black">Search</button>
    <!-- Profile chip stub -->
    <div class="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-xs font-medium">U</div>
  </nav>
</header>
```

#### Block E: skeleton placeholder HTML pattern

```html
<!-- Show while isLoading; replace with actual results after simulateNetwork() resolves. -->
<template x-if="isLoading">
  <div class="space-y-3" aria-live="polite" aria-busy="true">
    <div class="h-20 bg-gray-200 rounded animate-pulse"></div>
    <div class="h-20 bg-gray-200 rounded animate-pulse"></div>
    <div class="h-20 bg-gray-200 rounded animate-pulse"></div>
    <div class="h-20 bg-gray-200 rounded animate-pulse"></div>
  </div>
</template>
<template x-if="!isLoading">
  <div>
    <!-- actual content -->
  </div>
</template>
```

#### Block F: count-up factory (used by movie-tickets running total, recipe-site ingredient quantities)

```js
// src/lib/countUp.js — small rAF tween, honors reduced motion.
// Usage: createCountUp().to(targetValue, callback)
export function createCountUp(durationMs = 400) {
  return {
    _raf: null,
    to(target, set) {
      if (this._raf) cancelAnimationFrame(this._raf);
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (reduced) { set(target); return; }
      const start = parseFloat(set.last ?? 0);
      const t0 = performance.now();
      const tick = (now) => {
        const k = Math.min(1, (now - t0) / durationMs);
        const eased = 1 - Math.pow(1 - k, 3);
        const v = Math.round((start + (target - start) * eased) * 100) / 100;
        set(v); set.last = v;
        if (k < 1) this._raf = requestAnimationFrame(tick);
      };
      this._raf = requestAnimationFrame(tick);
    },
  };
}
```

**Note:** Block F is only included in template tasks that use it (`movie-tickets`, `recipe-site`). `flight-booking`, `food-delivery`, and `job-board` do not include `countUp.js`.

#### Block G: toast/snackbar pattern

```html
<!-- Place at end of <body>, outside every view. -->
<div
  x-show="toastMsg"
  x-transition.opacity.duration.200ms
  class="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded bg-black text-white text-sm shadow-lg"
  role="status"
  aria-live="polite"
  x-text="toastMsg"
></div>
```

```js
// Add to every template's appState():
toastMsg: '',
toast(msg) {
  this.toastMsg = msg;
  setTimeout(() => { this.toastMsg = ''; }, 2000);
},
```

---

## Tasks

### Task 1: Worktree setup + baseline verification

**Files (no changes yet, verification only):**
- Verify: `C:\Users\alama\Desktop\Lukas Work\IO-design-templates\mcp-servers\tasks\templates.py` has 24 `Template(...)` entries
- Verify: `C:\Users\alama\Desktop\Lukas Work\IO-design-templates\_tplpng\capture-local-templates.py` exists
- Verify: `C:\Users\alama\Desktop\Lukas Work\IO-design-templates\mcp-servers\tasks\static\templates.html` has `PREVIEW_VER = "4"`

**Goal:** Create the worktree, confirm we have the inherited yesterday-state, switch to the new branch.

- [ ] **Step 1: Create worktree from `feat/design-templates`.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO"
git worktree add -b feat/functional-templates "../IO-functional-templates" feat/design-templates
```

Expected: prints "Preparing worktree (new branch 'feat/functional-templates')" + "HEAD is now at <sha> …"

- [ ] **Step 2: Verify the baseline.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-functional-templates"
git branch --show-current
grep -c '^\s*Template(' mcp-servers/tasks/templates.py
ls _tplpng/capture-local-templates.py
grep 'PREVIEW_VER' mcp-servers/tasks/static/templates.html | head -1
```

Expected:
```
feat/functional-templates
24                                    # 24 Template entries
_tplpng/capture-local-templates.py    # exists
PREVIEW_VER = "4";                    # already at "4" from yesterday
```

If any check fails: `feat/design-templates` did not merge yesterday's work cleanly. Stop and surface to the user — do not proceed.

- [ ] **Step 3: Confirm directory layout for the 5 new keys.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-functional-templates"
ls mcp-servers/tasks/template_apps/
```

Expected: 10 entries — `agency  crud  dashboard  event  invoice  landing  photography  portfolio  real-estate  restaurant`. None of the new keys exist yet. Good.

- [ ] **Step 4: No commit yet** — worktree creation isn't committed; the branch is now in place.

---

### Task 2: Catalog wiring — register 5 templates in `templates.py`, update tests

**Files:**
- Modify: `mcp-servers/tasks/templates.py` (add 5 `_RULES_*`, 5 `_SVG_*`, 5 `Template(...)` entries)
- Modify: `mcp-servers/tasks/tests/test_templates.py` (`EXPECTED_KEYS`, rename `test_24_templates_present` → `test_29_templates_present`)

**Goal:** After this task, the gallery already shows the 5 new templates as featured cards (with their SVG mockups, since `preview.png` doesn't exist yet). Builds will FAIL because `template_apps/<key>/` folders don't exist — that's intentional. Catalog test drives implementation.

- [ ] **Step 1: Update `tests/test_templates.py` to expect 29 templates with the new keys.**

Locate the existing `EXPECTED_KEYS` set and the `test_24_templates_present` function. Replace as follows:

```python
# tests/test_templates.py — EXPECTED_KEYS additions + renamed count test
EXPECTED_KEYS = {
    "landing", "dashboard", "crud", "crm", "portfolio", "docs",
    "ecommerce", "booking", "chat", "auth", "blog", "blank",
    "invoice", "project-tracker", "ai-chatbot", "expense-tracker",
    "form-builder", "social-feed", "custom",
    # Design-forward templates (2026-05-08):
    "agency", "restaurant", "photography", "event", "real-estate",
    # Functional templates (2026-05-11):
    "flight-booking", "food-delivery", "job-board", "movie-tickets", "recipe-site",
}

def test_29_templates_present():
    assert len(TEMPLATES) == 29
    assert {t.key for t in TEMPLATES} == EXPECTED_KEYS
```

Also update the API endpoint test (search for the `expected_fields` assertion that asserts `len(items) == 24`):

```python
async def test_get_endpoint_excludes_rules_field():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/templates", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 29
    expected_fields = {
        "key", "label", "emoji", "description", "placeholder",
        "storage", "role_tag", "feature_bullets", "has_app", "svg_mockup",
    }
    for item in items:
        assert set(item.keys()) == expected_fields, (
            f"unexpected fields on {item.get('key')}: {set(item.keys())}"
        )
        assert "rules" not in item
```

- [ ] **Step 2: Run the test to verify it fails.**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_templates.py -v
```

Expected: FAIL on `test_29_templates_present` (`assert 24 == 29`) and on metadata-required tests that iterate `TEMPLATES` looking for the 5 new keys.

- [ ] **Step 3: Add `_RULES_<KEY>` constants to `templates.py`.**

Place before the `TEMPLATES = (...)` tuple, near the existing `_RULES_*` constants. Each follows the existing four-section pattern (`PURPOSE:`, `TECH:`, `MUST INCLUDE:`, `LAYOUT:`) plus this spec's additions (`ANIMATIONS PRESENT:`, `DO NOT REMOVE:`, `SAFE TO CUSTOMIZE:`, `IMAGE SLOTS:`, `TYPOGRAPHY:`).

```python
_RULES_FLIGHT_BOOKING: str = "\n".join([
    "PURPOSE: A flight search and booking app. User searches for flights by route/date/passengers, filters results by price/stops/time, picks a flight, reviews, and saves to a trips list.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES modules. Single-page state machine with views: search, results, detail, review. No build step. No npm install.",
    "MUST INCLUDE:",
    "  - Compact sticky app header (~56px, logo + brand name + profile chip stub, NOT a marketing hero).",
    "  - Search view: origin (datalist autocomplete), destination, depart/return dates, passenger count, cabin class. Big 'Search flights' button.",
    "  - Results view: filter sidebar (price range slider, stops radio, time-of-day pills, airlines multi-select, duration slider) + scrollable result list. Skeleton placeholders during 800-1400ms simulateNetwork().",
    "  - Detail view: full flight info, baggage allowance, decorative seat-map SVG, 'Save trip' + 'Continue to review' buttons.",
    "  - Review view: passenger names form, payment summary placeholder, 'Confirm' that toasts + resets to search.",
    "  - Saved trips persist in localStorage under namespace 'flight-booking'.",
    "LAYOUT: navy #0a1f3d primary, coral #ff6b5b accent, off-white background. Inter typography. CSS custom properties --bg, --primary, --accent.",
    "ANIMATIONS PRESENT: x-transition.duration.200ms between view changes, animate-pulse skeleton placeholders, slider thumb micro-shadow, card hover lift (2px y).",
    "DO NOT REMOVE: simulateNetwork() delay (gates skeleton), the prefers-reduced-motion guards, localStorage hydration in init().",
    "SAFE TO CUSTOMIZE: all copy, flight data in src/data.js, palette CSS variables, brand name, airline list. Image URLs must stay on whitelist (images.unsplash.com).",
    "IMAGE SLOTS (data-img-slot): hero (optional destination image in search view).",
    "TYPOGRAPHY: Inter loaded via fonts.googleapis.com.",
])

_RULES_FOOD_DELIVERY: str = "\n".join([
    "PURPOSE: A food delivery marketplace. User browses restaurants, opens a menu, adds items to a real cart, fake-checks-out.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES modules. Single-page state machine with views: restaurants, menu, cart, checkout, confirmation. No build step.",
    "MUST INCLUDE:",
    "  - Compact sticky header with cart-count badge (live total).",
    "  - Restaurants view: cuisine filter pills (Pizza/Sushi/Burger/Asian/Mexican/Vegan/Indian/Thai), min-rating slider, max-delivery-time slider, restaurant grid (image, name, cuisine, rating, ETA).",
    "  - Menu view: restaurant hero banner, items grid (image, name, description, price, +/- quantity stepper that updates cart).",
    "  - Cart view: line items grouped by restaurant, +/- stepper for each line, subtotal + $3.99 delivery fee + 8% tax + total, 'Place order' button.",
    "  - Checkout view: delivery address form, payment placeholder (last-4 input — visual only).",
    "  - Confirmation view: 'On its way' + fake ETA + decorative map placeholder.",
    "  - Cart persists in localStorage under namespace 'food-delivery'.",
    "LAYOUT: cream #fff8ec background, orange #ff8c42 accent, slate text. Inter for body, DM Sans for headings.",
    "ANIMATIONS PRESENT: x-transition.duration.200ms between views, cart-count badge count-up animation, animate-pulse skeleton, +/- button micro-bounce on click, item-card hover lift.",
    "DO NOT REMOVE: simulateNetwork() delay, prefers-reduced-motion guards, localStorage hydration in init(), the cart-state shape (changing it breaks reload-recovery).",
    "SAFE TO CUSTOMIZE: restaurant + menu data in src/data.js, cuisine tags, palette CSS variables, brand name, photo URLs (whitelist only).",
    "IMAGE SLOTS (data-img-slot): restaurant-hero, restaurant-thumb, menu-item.",
    "TYPOGRAPHY: Inter + DM Sans loaded via fonts.googleapis.com.",
])

_RULES_JOB_BOARD: str = "\n".join([
    "PURPOSE: A job search board. User searches and filters jobs, opens detail, bookmarks favorites, applies via a form.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES modules. Single-page state machine with views: list, detail, apply, submitted. No build step.",
    "MUST INCLUDE:",
    "  - Compact sticky header with brand name + 'Saved (n)' counter.",
    "  - List view: debounced search bar (250ms — matches title + company), remote-mode toggle, salary range slider ($60k-$300k), role-family multi-select pills (Engineering/Design/PM/Marketing/Data), seniority pills (junior/mid/senior/staff+).",
    "  - Job list: cards with DiceBear-generated company logo, title, location, salary range, posted-date (relative format), bookmark toggle.",
    "  - Detail view: full job description, company info card, 'Save' + 'Apply' buttons, similar-roles strip.",
    "  - Apply form: name, email, resume 'upload' (displays filename only — no real upload), cover letter textarea, required-field validation.",
    "  - Submitted view: 'Application sent' + fake tracking ID.",
    "  - Saved jobs persist in localStorage under namespace 'job-board'.",
    "LAYOUT: white background, blue #2563eb accent, slate text. Inter typography.",
    "ANIMATIONS PRESENT: x-transition.duration.200ms between views, debounced search filter, bookmark icon outline-to-filled swap, list-card hover lift, 'Sent' confirmation slide-up.",
    "DO NOT REMOVE: simulateNetwork() delay, prefers-reduced-motion guards, debounce timer cleanup, localStorage hydration.",
    "SAFE TO CUSTOMIZE: jobs and companies in src/data.js, role families, palette CSS variables, brand name.",
    "IMAGE SLOTS (data-img-slot): none — company logos are generated from DiceBear initials API.",
    "TYPOGRAPHY: Inter loaded via fonts.googleapis.com.",
])

_RULES_MOVIE_TICKETS: str = "\n".join([
    "PURPOSE: A cinema ticket booking app. User picks a film, chooses a showtime, selects seats from a live grid, fake-checks-out.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES modules. Single-page state machine with views: now-showing, film, showtime, seats, checkout, tickets. No build step.",
    "MUST INCLUDE:",
    "  - Compact sticky header with brand name (cinema chain).",
    "  - Now-showing grid: film posters (3:4 aspect), rating, genre tags, duration. Click → film view.",
    "  - Film detail view: synopsis, trailer-thumb placeholder, theater dropdown, showtime grid (clickable times). Click → seats view.",
    "  - Seats view: 10 rows × 14 seats per theater. Seat classes: available (gray), taken (~30% of seats, locked), selected (accent color), aisle (cols 5+10, non-clickable). Running total animates count-up as seats are added.",
    "  - Max 8 seats per booking. 'Continue' button disables beyond 8 or when 0 selected.",
    "  - Checkout view: ticket summary (seats + showtime + film), fake 'Pay' button.",
    "  - Tickets view: QR-code SVG placeholder + confirmation, 'Save to history' button.",
    "  - Booked showings persist in localStorage under namespace 'movie-tickets'.",
    "LAYOUT: black #0a0a0a background, amber #f59e0b accent, white text. Inter typography.",
    "ANIMATIONS PRESENT: x-transition.duration.200ms between views, seat-toggle micro-pop (scale 1 → 1.1 → 1), running total count-up, poster hover scale 1.02.",
    "DO NOT REMOVE: the seat-grid Set/Map state shape, simulateNetwork() delay, prefers-reduced-motion guards, taken-seat exclusion in the click handler.",
    "SAFE TO CUSTOMIZE: films, showtimes, theaters, palette CSS variables, brand name, poster URLs (whitelist only).",
    "IMAGE SLOTS (data-img-slot): film-poster.",
    "TYPOGRAPHY: Inter loaded via fonts.googleapis.com.",
])

_RULES_RECIPE_SITE: str = "\n".join([
    "PURPOSE: A recipe site with a 'cook mode' interactive flow. User browses recipes, opens a recipe, scales servings live (which recalculates all ingredient quantities), starts cook mode, advances step-by-step with optional timers.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES modules. Single-page state machine with views: catalog, recipe, cook-mode, completed. No build step.",
    "MUST INCLUDE:",
    "  - Compact sticky header with brand name + 'Favorites (n)' counter.",
    "  - Catalog view: ingredient search (matches ingredient names across recipes), diet pills (vegan/vegetarian/gluten-free/dairy-free), time-to-cook bucket (<15min / <30min / <60min / any), difficulty.",
    "  - Recipe grid: cards with hero image, name, time, difficulty, favorite toggle.",
    "  - Recipe detail view: hero image, byline, intro paragraph, ingredient list with serving-size slider (default 2, range 1-8 — quantities scale linearly, fractions render as fractions: '½ cup' not '0.5 cup'), step preview, 'Start Cooking' button.",
    "  - Cook-mode view: FULLSCREEN single-step view, 'Step n of N' indicator, large readable step text, optional inline 3:00 countdown timer (chime at 0), 'Next step' button, 'Exit' button. Attempt navigator.wakeLock.request('screen') on enter; gracefully no-op if unsupported.",
    "  - Completed view: celebration message, rating prompt, save-to-favorites toggle.",
    "  - Favorites + cookingHistory persist in localStorage under namespace 'recipe-site'.",
    "LAYOUT: warm white #faf6f1 background, olive #556b2f accent, slate text. Fraunces display + Inter body.",
    "ANIMATIONS PRESENT: x-transition.duration.200ms between views, ingredient-quantity count-up on serving change, hero-image fade-in.",
    "DO NOT REMOVE: the fraction renderer (formatQuantity), the wakelock try/catch, prefers-reduced-motion guards, localStorage hydration.",
    "SAFE TO CUSTOMIZE: recipes in src/data.js, diet tags, palette CSS variables, brand name, photo URLs (whitelist only).",
    "IMAGE SLOTS (data-img-slot): recipe-hero, recipe-thumb.",
    "TYPOGRAPHY: Fraunces (display) + Inter (body) loaded via fonts.googleapis.com.",
])
```

- [ ] **Step 4: Add `_SVG_<KEY>` constants** (place next to existing `_SVG_*` constants).

```python
_SVG_FLIGHT_BOOKING = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#0a1f3d"/>
  <text x="20" y="44" fill="#ffffff" font-family="ui-sans-serif" font-size="14" font-weight="600">Skylane</text>
  <rect x="20" y="60" width="130" height="26" fill="#1a2f5c" rx="4"/>
  <text x="32" y="78" fill="#ffffff" font-family="ui-sans-serif" font-size="11">JFK → LHR</text>
  <rect x="160" y="60" width="130" height="26" fill="#ff6b5b" rx="4"/>
  <text x="225" y="78" fill="#ffffff" font-family="ui-sans-serif" font-size="11" text-anchor="middle">Search</text>
  <rect x="20" y="100" width="270" height="22" fill="#1a2f5c" rx="3"/>
  <rect x="20" y="128" width="270" height="22" fill="#1a2f5c" rx="3"/>
  <rect x="20" y="156" width="270" height="22" fill="#1a2f5c" rx="3"/>
</svg>"""

_SVG_FOOD_DELIVERY = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#fff8ec"/>
  <text x="20" y="36" fill="#1a1208" font-family="ui-sans-serif" font-size="14" font-weight="600">Roost</text>
  <rect x="20" y="50" width="50" height="20" fill="#ff8c42" rx="10"/>
  <text x="45" y="64" fill="#ffffff" font-family="ui-sans-serif" font-size="10" text-anchor="middle">Pizza</text>
  <rect x="76" y="50" width="50" height="20" fill="#ffffff" stroke="#ff8c42" rx="10"/>
  <text x="101" y="64" fill="#ff8c42" font-family="ui-sans-serif" font-size="10" text-anchor="middle">Sushi</text>
  <rect x="20" y="84" width="130" height="60" fill="#ffe6c9" rx="4"/>
  <rect x="160" y="84" width="130" height="60" fill="#ffe6c9" rx="4"/>
  <rect x="20" y="156" width="270" height="28" fill="#ff8c42" rx="4"/>
  <text x="155" y="174" fill="#ffffff" font-family="ui-sans-serif" font-size="11" font-weight="600" text-anchor="middle">Cart (3) · $42</text>
</svg>"""

_SVG_JOB_BOARD = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#ffffff"/>
  <text x="20" y="36" fill="#0f172a" font-family="ui-sans-serif" font-size="14" font-weight="600">Workpath</text>
  <rect x="20" y="50" width="280" height="26" fill="#f1f5f9" stroke="#e2e8f0" rx="4"/>
  <text x="32" y="68" fill="#64748b" font-family="ui-sans-serif" font-size="11">Search jobs…</text>
  <rect x="20" y="86" width="60" height="20" fill="#2563eb" rx="10"/>
  <text x="50" y="100" fill="#ffffff" font-family="ui-sans-serif" font-size="10" text-anchor="middle">Remote</text>
  <rect x="20" y="116" width="280" height="22" fill="#f8fafc" rx="3"/>
  <rect x="20" y="144" width="280" height="22" fill="#f8fafc" rx="3"/>
  <rect x="20" y="172" width="280" height="22" fill="#f8fafc" rx="3"/>
</svg>"""

_SVG_MOVIE_TICKETS = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#0a0a0a"/>
  <text x="20" y="32" fill="#ffffff" font-family="ui-sans-serif" font-size="13" font-weight="600">Lumen Cinemas</text>
  <text x="20" y="50" fill="#f59e0b" font-family="ui-sans-serif" font-size="11">Dune Pt 2 · 7:30pm</text>
  <g transform="translate(20,68)">
    <rect x="0" y="0" width="16" height="16" fill="#333333" rx="2"/>
    <rect x="20" y="0" width="16" height="16" fill="#555555" rx="2"/>
    <rect x="40" y="0" width="16" height="16" fill="#555555" rx="2"/>
    <rect x="60" y="0" width="16" height="16" fill="#f59e0b" rx="2"/>
    <rect x="80" y="0" width="16" height="16" fill="#f59e0b" rx="2"/>
    <rect x="100" y="0" width="16" height="16" fill="#333333" rx="2"/>
    <rect x="0" y="20" width="16" height="16" fill="#333333" rx="2"/>
    <rect x="20" y="20" width="16" height="16" fill="#333333" rx="2"/>
    <rect x="40" y="20" width="16" height="16" fill="#555555" rx="2"/>
    <rect x="60" y="20" width="16" height="16" fill="#333333" rx="2"/>
    <rect x="80" y="20" width="16" height="16" fill="#333333" rx="2"/>
    <rect x="100" y="20" width="16" height="16" fill="#333333" rx="2"/>
  </g>
  <rect x="20" y="158" width="160" height="26" fill="#f59e0b" rx="4"/>
  <text x="100" y="176" fill="#0a0a0a" font-family="ui-sans-serif" font-size="11" font-weight="600" text-anchor="middle">2 seats · $32</text>
</svg>"""

_SVG_RECIPE_SITE = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#faf6f1"/>
  <text x="20" y="36" fill="#1f2937" font-family="Georgia,serif" font-size="16" font-weight="700" font-style="italic">Salt &amp; Pan</text>
  <rect x="20" y="52" width="280" height="80" fill="#e8e0d0" rx="4"/>
  <text x="160" y="100" fill="#556b2f" font-family="Georgia,serif" font-size="14" text-anchor="middle">Lemon Garlic Pasta</text>
  <text x="160" y="120" fill="#6b7280" font-family="ui-sans-serif" font-size="11" text-anchor="middle">25 min · easy</text>
  <rect x="20" y="148" width="40" height="22" fill="#556b2f" rx="11"/>
  <text x="40" y="163" fill="#ffffff" font-family="ui-sans-serif" font-size="10" text-anchor="middle">Vegan</text>
  <rect x="68" y="148" width="60" height="22" fill="#ffffff" stroke="#556b2f" rx="11"/>
  <text x="98" y="163" fill="#556b2f" font-family="ui-sans-serif" font-size="10" text-anchor="middle">30 min</text>
</svg>"""
```

- [ ] **Step 5: Add 5 `Template(...)` entries** before the existing `Template(key="agency", ...)` entry. (Functional templates sort before design showcases.)

```python
    Template(
        key="flight-booking",
        label="Flight Booking",
        emoji="✈️",
        description="flight search + booking flow",
        placeholder="e.g. Flight search app called 'Skylane'. Routes between 8 major cities (JFK, LHR, SFO, NRT, LAX, CDG, ATL, FCO). Filters by price, stops, time of day. Save trips. Navy + coral palette.",
        rules=_RULES_FLIGHT_BOOKING,
        storage="none",
        role_tag="Search + booking",
        feature_bullets=(
            "Live filter sliders (price, stops, time of day)",
            "Skeleton loaders gated on a real 800-1400ms fake-network delay",
            "Saved trips persist across page reloads",
        ),
        svg_mockup=_SVG_FLIGHT_BOOKING,
    ),
    Template(
        key="food-delivery",
        label="Food Delivery",
        emoji="🍔",
        description="restaurant marketplace + cart",
        placeholder="e.g. Food delivery marketplace called 'Roost'. 14 restaurants across 8 cuisines, 12 menu items each. Real cart with quantity stepper. Cream + orange palette.",
        rules=_RULES_FOOD_DELIVERY,
        storage="none",
        role_tag="Marketplace + cart",
        feature_bullets=(
            "Cuisine filter pills, rating + delivery-time sliders",
            "Real cart with quantity stepper — survives page reload",
            "Multi-step checkout with confirmation view",
        ),
        svg_mockup=_SVG_FOOD_DELIVERY,
    ),
    Template(
        key="job-board",
        label="Job Board",
        emoji="💼",
        description="job search with filters + apply",
        placeholder="e.g. Job board called 'Workpath'. 60 jobs across 12 companies, mixed role families. Debounced search. Remote/hybrid/onsite filter. Save jobs. Application form. White + blue palette.",
        rules=_RULES_JOB_BOARD,
        storage="none",
        role_tag="Search + apply",
        feature_bullets=(
            "Debounced 250ms search bar with multi-filter chips",
            "Bookmark toggle persists per-user",
            "Application form with required-field validation",
        ),
        svg_mockup=_SVG_JOB_BOARD,
    ),
    Template(
        key="movie-tickets",
        label="Movie Tickets",
        emoji="🎬",
        description="cinema seat picker + checkout",
        placeholder="e.g. Cinema chain 'Lumen Cinemas'. 12 films, 3 theaters, ~5 showtimes each. Interactive 10×14 seat grid. Black + amber palette.",
        rules=_RULES_MOVIE_TICKETS,
        storage="none",
        role_tag="Seat picker + checkout",
        feature_bullets=(
            "Interactive 10×14 seat grid (available/taken/selected/aisle)",
            "Running total count-up as seats are added",
            "Multi-step booking with ticket history persisted",
        ),
        svg_mockup=_SVG_MOVIE_TICKETS,
    ),
    Template(
        key="recipe-site",
        label="Recipe Site",
        emoji="🥘",
        description="recipes + cook mode + serving scale",
        placeholder="e.g. Recipe site 'Salt & Pan'. 30 recipes with diet tags. Live serving-size slider that rescales ingredients (½ cup, not 0.5 cup). Fullscreen cook mode with step timer. Warm white + olive palette.",
        rules=_RULES_RECIPE_SITE,
        storage="none",
        role_tag="Browse + cook mode",
        feature_bullets=(
            "Serving-size slider rescales ingredient quantities live",
            "Fullscreen cook mode with optional step timer",
            "Wakelock attempt prevents screen sleep while cooking",
        ),
        svg_mockup=_SVG_RECIPE_SITE,
    ),
```

- [ ] **Step 6: Run the test, confirm count test passes.**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_templates.py -v
```

Expected: `test_29_templates_present` PASSES. The metadata-required tests for the 5 new keys (`test_each_template_has_required_metadata`, `test_each_template_has_rules_sections`) should also pass — every required field is populated.

- [ ] **Step 7: Commit.**

```bash
git add mcp-servers/tasks/templates.py mcp-servers/tasks/tests/test_templates.py
git commit -m "feat(templates): register 5 functional templates in catalog"
```

---

### Task 3: Flight booking template (reference template)

**Files to create:**
- `mcp-servers/tasks/template_apps/flight-booking/index.html`
- `mcp-servers/tasks/template_apps/flight-booking/styles/main.css`
- `mcp-servers/tasks/template_apps/flight-booking/src/main.js`
- `mcp-servers/tasks/template_apps/flight-booking/src/data.js`
- `mcp-servers/tasks/template_apps/flight-booking/src/lib/router.js` (paste Block A verbatim)
- `mcp-servers/tasks/template_apps/flight-booking/src/lib/persistence.js` (paste Block B verbatim)
- `mcp-servers/tasks/template_apps/flight-booking/src/lib/skeleton.js` (paste Block C verbatim)
- `mcp-servers/tasks/template_apps/flight-booking/README.md`
- `mcp-servers/tasks/template_apps/flight-booking/public/.gitkeep`

**Goal:** Implement the reference template end-to-end. After this task, `flight-booking/index.html` is openable in a browser via a local HTTP server and the user can search → results → detail → review → back-to-search cleanly. Real filter changes, real saved-trips persistence.

- [ ] **Step 1: Create the directory + scaffolding files.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-functional-templates"
mkdir -p mcp-servers/tasks/template_apps/flight-booking/{styles,src/lib,public}
touch mcp-servers/tasks/template_apps/flight-booking/public/.gitkeep
```

- [ ] **Step 2: Write `src/lib/router.js`, `src/lib/persistence.js`, `src/lib/skeleton.js` — paste Blocks A, B, C verbatim.**

(See "Reusable code blocks" at the top of this plan. No edits — copy character-for-character.)

- [ ] **Step 3: Write `src/data.js`.** Define `flights` (30 entries across 8 routes) + `airlines` + helper enums.

```js
// src/data.js — flight catalog. Stable IDs (no Math.random at load).
export const airlines = [
  "Skylane", "Northwind", "Aegis Air", "Pacific Crest",
  "Lumen Atlantic", "Cirrus", "Helios", "Veridian",
];

export const cities = [
  { code: "JFK", label: "New York (JFK)" },
  { code: "LHR", label: "London (LHR)" },
  { code: "SFO", label: "San Francisco (SFO)" },
  { code: "NRT", label: "Tokyo (NRT)" },
  { code: "LAX", label: "Los Angeles (LAX)" },
  { code: "CDG", label: "Paris (CDG)" },
  { code: "ATL", label: "Atlanta (ATL)" },
  { code: "FCO", label: "Rome (FCO)" },
];

// Bucket departure times for the time-of-day filter.
const bucketize = (hour) =>
  hour < 6 ? "early" : hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";

// 30 flights across 8 routes. Realistic prices ($420-$1840) + durations.
// Generate in code so this is paste-friendly while staying deterministic.
const routes = [
  ["JFK","LHR"], ["JFK","LHR"], ["JFK","LHR"], ["JFK","LHR"],
  ["SFO","NRT"], ["SFO","NRT"], ["SFO","NRT"],
  ["LAX","CDG"], ["LAX","CDG"], ["LAX","CDG"],
  ["ATL","FCO"], ["ATL","FCO"], ["ATL","FCO"],
  ["LHR","JFK"], ["LHR","JFK"], ["LHR","JFK"],
  ["NRT","SFO"], ["NRT","SFO"], ["NRT","SFO"],
  ["CDG","LAX"], ["CDG","LAX"],
  ["FCO","ATL"], ["FCO","ATL"],
  ["JFK","CDG"], ["JFK","CDG"],
  ["SFO","LHR"], ["SFO","LHR"],
  ["LAX","NRT"], ["LAX","NRT"], ["LAX","NRT"],
];

const seedPrices = [642, 589, 531, 728, 1240, 1180, 1395, 980, 1120, 875,
  812, 925, 760, 598, 642, 720, 1310, 1260, 1410, 1095, 1240,
  890, 940, 720, 810, 1180, 1245, 1530, 1610, 1480];
const seedStops = [0,0,1,1, 0,1,0, 1,0,1, 1,2,1, 0,1,0, 0,1,0, 0,1, 1,0, 1,0, 1,2, 0,1,2];
const seedDurations = [420,490,540,460, 660,720,640, 690,640,720, 600,720,580, 420,490,470, 720,780,640, 720,840, 600,540, 460,500, 690,750, 700,800,860];
const seedDepartHours = [8,11,14,19, 9,11,13, 7,15,21, 8,13,18, 10,14,20, 8,13,19, 11,17, 9,16, 7,16, 10,15, 12,18,22];

export const flights = routes.map(([origin, destination], i) => {
  const depHour = seedDepartHours[i];
  return {
    id: `flt-${String(i + 1).padStart(3, "0")}`,
    origin,
    destination,
    airline: airlines[i % airlines.length],
    price: seedPrices[i],
    stops: seedStops[i],
    duration: seedDurations[i],         // minutes
    departureHour: depHour,
    departureBucket: bucketize(depHour),
    departureLabel: `${String(depHour).padStart(2, "0")}:00`,
    arrivalLabel: `${String((depHour + Math.floor(seedDurations[i] / 60)) % 24).padStart(2, "0")}:${String(seedDurations[i] % 60).padStart(2, "0")}`,
    cabin: i % 5 === 0 ? "Business" : "Economy",
    baggage: i % 5 === 0 ? "2× 32kg checked" : "1× 23kg checked",
  };
}).sort((a, b) => a.price - b.price);
```

- [ ] **Step 4: Write `src/main.js`** — the Alpine root.

```js
// src/main.js — Alpine root with router, persistence, search, filters, save.
import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { simulateNetwork }   from "./lib/skeleton.js";
import { flights, cities, airlines } from "./data.js";

window.appState = () => ({
  ...createRouter({ initial: "search", views: ["search", "results", "detail", "review"] }),
  ...createPersistence({ namespace: "flight-booking", keys: ["savedTrips"] }),

  // Reference data
  cities,
  airlines,
  allFlights: flights,

  // Search form
  searchForm: { origin: "JFK", destination: "LHR", depart: "2026-10-12", returnDate: "2026-10-19", pax: 1, cabin: "Economy" },

  // Results state
  filteredFlights: [],
  isLoading: false,
  filters: { maxPrice: 2000, stops: "any", timeOfDay: "any", airlines: [], maxDuration: 900 },

  // Detail/review state
  selectedFlight: null,
  passengerNames: [""],

  // Toast
  toastMsg: "",

  init() {
    this._hydrate();
    this.filteredFlights = this.allFlights;
  },

  async runSearch() {
    this.isLoading = true;
    this.setView("results");
    await simulateNetwork();
    this.applyFilters();
    this.isLoading = false;
  },

  applyFilters() {
    this.filteredFlights = this.allFlights.filter((f) =>
      f.price <= this.filters.maxPrice &&
      f.duration <= this.filters.maxDuration &&
      (this.filters.stops === "any" || (this.filters.stops === "0" ? f.stops === 0 : f.stops >= 1)) &&
      (this.filters.timeOfDay === "any" || f.departureBucket === this.filters.timeOfDay) &&
      (this.filters.airlines.length === 0 || this.filters.airlines.includes(f.airline))
    );
  },

  toggleAirline(name) {
    const i = this.filters.airlines.indexOf(name);
    if (i >= 0) this.filters.airlines.splice(i, 1);
    else this.filters.airlines.push(name);
    this.applyFilters();
  },

  openDetail(flightId) {
    this.selectedFlight = this.allFlights.find((f) => f.id === flightId);
    this.setView("detail");
  },

  saveTrip() {
    if (!this.selectedFlight) return;
    if (!this.savedTrips.find((t) => t.id === this.selectedFlight.id)) {
      this.savedTrips.push(this.selectedFlight);
      this._save("savedTrips");
      this.toast("Trip saved");
    } else {
      this.toast("Already saved");
    }
  },

  goReview() {
    this.passengerNames = Array.from({ length: this.searchForm.pax }, () => "");
    this.setView("review");
  },

  confirmBooking() {
    this.toast(`Confirmation sent (demo)`);
    this.selectedFlight = null;
    this.setView("search");
  },

  toast(msg) {
    this.toastMsg = msg;
    setTimeout(() => { this.toastMsg = ""; }, 2000);
  },

  formatDuration(min) {
    return `${Math.floor(min / 60)}h ${min % 60}m`;
  },
});
```

- [ ] **Step 5: Write `index.html`** — single file with all four views.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Skylane — Flight Booking</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="styles/main.css" />
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
</head>
<body x-data="appState()" x-init="init()" class="bg-[var(--bg)] text-[var(--text)] font-sans">

  <!-- Header (compact, sticky) -->
  <header
    x-data="{ scrolled: false }"
    x-init="window.addEventListener('scroll', () => { scrolled = window.scrollY > 32; }, { passive: true })"
    :class="scrolled ? 'h-12 shadow-sm' : 'h-14 shadow-none'"
    class="sticky top-0 z-30 bg-[var(--bg)] backdrop-blur transition-all duration-150 flex items-center px-4 sm:px-6 border-b border-white/5"
  >
    <a href="#" @click.prevent="setView('search')" class="flex items-center gap-2 font-semibold text-white">
      <span class="inline-block w-6 h-6 rounded bg-[var(--accent)]"></span>
      <span>Skylane</span>
    </a>
    <nav class="ml-auto flex items-center gap-4 text-sm text-white/80">
      <button @click="setView('search')" class="hidden sm:inline-block hover:text-white">Search</button>
      <button @click="setView('search')" class="hidden sm:inline-block hover:text-white">
        Saved <span x-text="savedTrips.length ? `(${savedTrips.length})` : ''"></span>
      </button>
      <div class="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center text-xs font-medium">U</div>
    </nav>
  </header>

  <!-- ===================== SEARCH VIEW ===================== -->
  <section x-show="view === 'search'" x-transition.duration.200ms class="max-w-5xl mx-auto px-4 sm:px-6 py-12">
    <h1 class="text-3xl sm:text-4xl font-bold text-white mb-2">Where to next?</h1>
    <p class="text-white/60 mb-8">Search non-stop and connecting flights across 8 cities.</p>

    <form @submit.prevent="runSearch()" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 bg-white/5 rounded-xl p-4">
      <label class="flex flex-col text-xs text-white/60">
        From
        <select x-model="searchForm.origin" class="mt-1 bg-transparent border border-white/10 rounded px-3 py-2 text-white">
          <template x-for="c in cities" :key="c.code">
            <option :value="c.code" x-text="c.label" class="text-black"></option>
          </template>
        </select>
      </label>
      <label class="flex flex-col text-xs text-white/60">
        To
        <select x-model="searchForm.destination" class="mt-1 bg-transparent border border-white/10 rounded px-3 py-2 text-white">
          <template x-for="c in cities" :key="c.code">
            <option :value="c.code" x-text="c.label" class="text-black"></option>
          </template>
        </select>
      </label>
      <label class="flex flex-col text-xs text-white/60">
        Depart
        <input type="date" x-model="searchForm.depart" class="mt-1 bg-transparent border border-white/10 rounded px-3 py-2 text-white" />
      </label>
      <label class="flex flex-col text-xs text-white/60">
        Return
        <input type="date" x-model="searchForm.returnDate" class="mt-1 bg-transparent border border-white/10 rounded px-3 py-2 text-white" />
      </label>
      <label class="flex flex-col text-xs text-white/60">
        Passengers
        <input type="number" min="1" max="9" x-model.number="searchForm.pax" class="mt-1 bg-transparent border border-white/10 rounded px-3 py-2 text-white" />
      </label>
      <label class="flex flex-col text-xs text-white/60 lg:col-span-2">
        Cabin
        <select x-model="searchForm.cabin" class="mt-1 bg-transparent border border-white/10 rounded px-3 py-2 text-white">
          <option class="text-black">Economy</option>
          <option class="text-black">Premium Economy</option>
          <option class="text-black">Business</option>
          <option class="text-black">First</option>
        </select>
      </label>
      <button type="submit" class="lg:col-span-1 bg-[var(--accent)] text-white font-semibold rounded px-4 py-2 hover:opacity-90 transition">
        Search flights
      </button>
    </form>

    <p class="mt-6 text-sm text-white/50">Showing all <span x-text="allFlights.length"></span> flights in the catalog. Real filtering happens on the next view.</p>
  </section>

  <!-- ===================== RESULTS VIEW ===================== -->
  <section x-show="view === 'results'" x-transition.duration.200ms class="max-w-6xl mx-auto px-4 sm:px-6 py-8">
    <div class="flex items-center mb-6">
      <button @click="back()" class="text-white/60 hover:text-white">← Modify search</button>
      <h2 class="text-xl font-semibold text-white ml-6" x-text="`${searchForm.origin} → ${searchForm.destination}`"></h2>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-6">
      <!-- Filter sidebar -->
      <aside class="bg-white/5 rounded-xl p-4 space-y-5 h-fit lg:sticky lg:top-20">
        <div>
          <label class="text-xs uppercase tracking-wide text-white/50">Max price</label>
          <input type="range" min="400" max="2000" step="50" x-model.number="filters.maxPrice" @input="applyFilters()" class="w-full mt-2 accent-[var(--accent)]" />
          <div class="text-sm text-white mt-1">Up to $<span x-text="filters.maxPrice"></span></div>
        </div>
        <div>
          <label class="text-xs uppercase tracking-wide text-white/50">Stops</label>
          <div class="flex gap-2 mt-2">
            <template x-for="opt in [['any','Any'],['0','Non-stop'],['1','1+']]" :key="opt[0]">
              <button @click="filters.stops = opt[0]; applyFilters()"
                :class="filters.stops === opt[0] ? 'bg-[var(--accent)] text-white' : 'bg-white/10 text-white/70'"
                class="px-3 py-1 rounded-full text-xs" x-text="opt[1]"></button>
            </template>
          </div>
        </div>
        <div>
          <label class="text-xs uppercase tracking-wide text-white/50">Time of day</label>
          <div class="grid grid-cols-2 gap-2 mt-2">
            <template x-for="opt in [['any','Any'],['early','Early'],['morning','Morning'],['afternoon','Afternoon'],['evening','Evening']]" :key="opt[0]">
              <button @click="filters.timeOfDay = opt[0]; applyFilters()"
                :class="filters.timeOfDay === opt[0] ? 'bg-[var(--accent)] text-white' : 'bg-white/10 text-white/70'"
                class="px-3 py-1 rounded text-xs" x-text="opt[1]"></button>
            </template>
          </div>
        </div>
        <div>
          <label class="text-xs uppercase tracking-wide text-white/50">Max duration</label>
          <input type="range" min="300" max="1000" step="30" x-model.number="filters.maxDuration" @input="applyFilters()" class="w-full mt-2 accent-[var(--accent)]" />
          <div class="text-sm text-white mt-1" x-text="formatDuration(filters.maxDuration)"></div>
        </div>
        <div>
          <label class="text-xs uppercase tracking-wide text-white/50">Airlines</label>
          <div class="flex flex-wrap gap-1 mt-2">
            <template x-for="a in airlines" :key="a">
              <button @click="toggleAirline(a)"
                :class="filters.airlines.includes(a) ? 'bg-[var(--accent)] text-white' : 'bg-white/10 text-white/70'"
                class="px-2 py-1 rounded text-xs" x-text="a"></button>
            </template>
          </div>
        </div>
      </aside>

      <!-- Result list -->
      <div>
        <p class="text-sm text-white/60 mb-3">
          <span x-text="filteredFlights.length"></span> of <span x-text="allFlights.length"></span> flights match
        </p>

        <template x-if="isLoading">
          <div class="space-y-3" aria-busy="true">
            <div class="h-20 bg-white/10 rounded animate-pulse"></div>
            <div class="h-20 bg-white/10 rounded animate-pulse"></div>
            <div class="h-20 bg-white/10 rounded animate-pulse"></div>
            <div class="h-20 bg-white/10 rounded animate-pulse"></div>
          </div>
        </template>

        <template x-if="!isLoading">
          <div class="space-y-3">
            <template x-for="f in filteredFlights" :key="f.id">
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
                <div class="text-right">
                  <div class="text-2xl font-bold text-[var(--accent)]" x-text="`$${f.price}`"></div>
                  <div class="text-xs text-white/40 mt-1">per passenger</div>
                </div>
              </article>
            </template>
            <template x-if="filteredFlights.length === 0">
              <p class="text-white/50 text-center py-12">No flights match these filters. Try widening the price or duration.</p>
            </template>
          </div>
        </template>
      </div>
    </div>
  </section>

  <!-- ===================== DETAIL VIEW ===================== -->
  <section x-show="view === 'detail'" x-transition.duration.200ms class="max-w-4xl mx-auto px-4 sm:px-6 py-8" x-cloak>
    <button @click="back()" class="text-white/60 hover:text-white mb-6">← Back to results</button>

    <template x-if="selectedFlight">
      <div>
        <div class="bg-white/5 rounded-xl p-6">
          <div class="text-xs text-white/50" x-text="selectedFlight.airline + ' · ' + selectedFlight.cabin"></div>
          <h2 class="text-3xl font-bold text-white mt-1" x-text="`${selectedFlight.origin} → ${selectedFlight.destination}`"></h2>
          <div class="mt-2 text-white/70">
            <span x-text="`${selectedFlight.departureLabel} – ${selectedFlight.arrivalLabel}`"></span>
            <span class="mx-2">·</span>
            <span x-text="formatDuration(selectedFlight.duration)"></span>
            <span class="mx-2">·</span>
            <span x-text="selectedFlight.stops === 0 ? 'Non-stop' : selectedFlight.stops + ' stop' + (selectedFlight.stops > 1 ? 's' : '')"></span>
          </div>
          <div class="mt-6 grid grid-cols-2 gap-4 text-sm">
            <div class="bg-white/5 rounded p-3">
              <div class="text-white/50 text-xs">Baggage</div>
              <div class="text-white mt-1" x-text="selectedFlight.baggage"></div>
            </div>
            <div class="bg-white/5 rounded p-3">
              <div class="text-white/50 text-xs">Total</div>
              <div class="text-white mt-1 text-xl font-semibold" x-text="`$${selectedFlight.price * searchForm.pax}`"></div>
            </div>
          </div>

          <!-- Decorative seat-map SVG (illustrative only) -->
          <div class="mt-6">
            <div class="text-xs text-white/50 mb-2">Seat map preview</div>
            <svg viewBox="0 0 400 100" class="w-full h-20" aria-hidden="true">
              <rect width="400" height="100" fill="rgba(255,255,255,0.05)" rx="8"/>
              <g fill="rgba(255,255,255,0.4)">
                <rect x="20" y="20" width="14" height="14" rx="2"/><rect x="40" y="20" width="14" height="14" rx="2"/>
                <rect x="76" y="20" width="14" height="14" rx="2"/><rect x="96" y="20" width="14" height="14" rx="2"/>
                <rect x="132" y="20" width="14" height="14" rx="2"/><rect x="152" y="20" width="14" height="14" rx="2"/>
                <rect x="188" y="20" width="14" height="14" rx="2"/><rect x="208" y="20" width="14" height="14" rx="2"/>
                <rect x="244" y="20" width="14" height="14" rx="2"/><rect x="264" y="20" width="14" height="14" rx="2"/>
                <rect x="300" y="20" width="14" height="14" rx="2"/><rect x="320" y="20" width="14" height="14" rx="2"/>
                <rect x="356" y="20" width="14" height="14" rx="2"/><rect x="376" y="20" width="14" height="14" rx="2"/>
              </g>
            </svg>
          </div>

          <div class="mt-6 flex gap-3">
            <button @click="saveTrip()" class="bg-white/10 hover:bg-white/20 text-white rounded px-4 py-2 transition">Save trip</button>
            <button @click="goReview()" class="bg-[var(--accent)] hover:opacity-90 text-white rounded px-4 py-2 font-semibold transition">Continue to review</button>
          </div>
        </div>
      </div>
    </template>
  </section>

  <!-- ===================== REVIEW VIEW ===================== -->
  <section x-show="view === 'review'" x-transition.duration.200ms class="max-w-3xl mx-auto px-4 sm:px-6 py-8" x-cloak>
    <button @click="back()" class="text-white/60 hover:text-white mb-6">← Back to detail</button>
    <h2 class="text-2xl font-bold text-white mb-6">Review and confirm</h2>

    <template x-if="selectedFlight">
      <form @submit.prevent="confirmBooking()" class="space-y-6">
        <div class="bg-white/5 rounded-xl p-5">
          <div class="text-sm text-white/70">Passenger details</div>
          <template x-for="(name, i) in passengerNames" :key="i">
            <input type="text" required x-model="passengerNames[i]"
              :placeholder="`Passenger ${i + 1} full name`"
              class="mt-3 w-full bg-transparent border border-white/10 rounded px-3 py-2 text-white" />
          </template>
        </div>
        <div class="bg-white/5 rounded-xl p-5 flex items-center justify-between">
          <div>
            <div class="text-sm text-white/50">Total</div>
            <div class="text-2xl font-bold text-[var(--accent)]" x-text="`$${selectedFlight.price * searchForm.pax}`"></div>
          </div>
          <button type="submit" class="bg-[var(--accent)] hover:opacity-90 text-white rounded px-5 py-3 font-semibold transition">Confirm booking</button>
        </div>
      </form>
    </template>
  </section>

  <!-- Toast -->
  <div x-show="toastMsg" x-transition.opacity.duration.200ms
    class="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded bg-white text-black text-sm shadow-lg"
    role="status" aria-live="polite" x-text="toastMsg"></div>

  <script type="module" src="src/main.js"></script>
</body>
</html>
```

- [ ] **Step 6: Write `styles/main.css`.**

```css
/* Skylane palette + transitions */
:root {
  --bg: #0a1f3d;
  --bg-card: #1a2f5c;
  --text: #f8fafc;
  --accent: #ff6b5b;
  --muted: #94a3b8;
}

html { background: var(--bg); }
body { font-family: "Inter", ui-sans-serif, system-ui, sans-serif; }

/* Reduced-motion guard */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}

/* Prevent flash of un-Alpine'd content */
[x-cloak] { display: none !important; }

/* Subtle card lift */
article { transition: transform 150ms ease-out, background-color 150ms; }
```

- [ ] **Step 7: Write `README.md`.**

```markdown
# Skylane — Flight Booking Template

Single-page flight search and booking app built on the IO App Builder's
static-template baseline (Tailwind CDN + Alpine.js + vanilla ES modules,
no build step).

## What's included

- Single-page state machine: search → results → detail → review
- 30 demo flights across 8 routes (JFK, LHR, SFO, NRT, LAX, CDG, ATL, FCO)
- Real client-side filters: price slider, stops, time of day, airlines, duration
- 800-1400ms fake-network delay so skeleton placeholders have airtime
- Saved trips persist across reloads (localStorage namespace: `flight-booking`)
- Honors `prefers-reduced-motion`

## Local preview

```bash
cd template_apps/flight-booking
python -m http.server 8200
# open http://localhost:8200
```

## Customization safe spots

- `src/data.js` — flight catalog, airlines list, city codes
- `styles/main.css` — `--bg`, `--accent`, `--text` CSS custom properties
- Brand name "Skylane" appears in `index.html` (header) and `<title>`
```

- [ ] **Step 8: Smoke test in a local server.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-functional-templates/mcp-servers/tasks/template_apps/flight-booking"
python -m http.server 8200
```

Open `http://localhost:8200`. Verify in browser:
- Search view renders, default values populated
- "Search flights" shows skeleton briefly then result list
- Drag price slider → list filters
- Click any flight card → detail view
- Click "Save trip" → toast appears, count badge in header increments
- Reload page → "Saved (1)" still visible in header (localStorage works)
- Click "Continue to review" → review form
- "Confirm booking" → returns to search

Stop the server: Ctrl+C.

- [ ] **Step 9: Commit.**

```bash
git add mcp-servers/tasks/template_apps/flight-booking/
git commit -m "feat(template): flight-booking single-page state machine"
```

---

### Task 4: Food delivery template

**Files to create:** `mcp-servers/tasks/template_apps/food-delivery/` (same scaffold as Task 3 — `index.html`, `styles/main.css`, `src/main.js`, `src/data.js`, `src/lib/{router,persistence,skeleton}.js`, `README.md`, `public/.gitkeep`)

**Goal:** Restaurant browsing + real cart with localStorage persistence. The highlight: cart count survives page reload, +/- stepper updates the cart in real time.

**Note:** No `countUp.js` for this template. Cart count is shown as plain text (the spec allows count-up on cart total but it is not required, and the +/- stepper interaction already gives the cart visible immediate feedback). `countUp.js` only appears in `movie-tickets` and `recipe-site`.

- [ ] **Step 1: Create scaffolding and paste Blocks A, B, C into `src/lib/`.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-functional-templates"
mkdir -p mcp-servers/tasks/template_apps/food-delivery/{styles,src/lib,public}
touch mcp-servers/tasks/template_apps/food-delivery/public/.gitkeep
```

Paste `router.js`, `persistence.js`, `skeleton.js` (Blocks A, B, C) verbatim into `src/lib/`. **Do NOT include `countUp.js`** for this template.

- [ ] **Step 2: Write `src/data.js`** — 14 restaurants, 12 menu items each (170 entries).

Generate compactly via JS rather than spelling out 170 lines:

```js
// src/data.js — restaurants + menus.

const cuisines = ["Pizza", "Sushi", "Burger", "Asian", "Mexican", "Vegan", "Indian", "Thai"];

// 14 restaurants, deterministic seed-generated.
const restaurantSeeds = [
  ["Tony's Pizza", "Pizza", 4.7, 25],
  ["Sushi Kai", "Sushi", 4.8, 35],
  ["Burger Block", "Burger", 4.5, 20],
  ["Mei Wok", "Asian", 4.6, 30],
  ["Casa Lupita", "Mexican", 4.4, 28],
  ["Green Roots", "Vegan", 4.7, 32],
  ["Taj Spice", "Indian", 4.5, 38],
  ["Bangkok Heat", "Thai", 4.6, 28],
  ["Slice & Co", "Pizza", 4.3, 22],
  ["Nori House", "Sushi", 4.7, 40],
  ["Patty Lane", "Burger", 4.2, 18],
  ["Wok Around", "Asian", 4.5, 32],
  ["Verde", "Vegan", 4.6, 30],
  ["Curry Club", "Indian", 4.4, 35],
];

// Stable Unsplash photo IDs (food + restaurant interiors)
const heroPhotos = [
  "1565299624946-b28f40a0ae38", "1579871494447-9811cf80d66c",
  "1568901346375-23c9450c58cd", "1552566626-52f8b828add9",
  "1564507592333-c60657eea523", "1490645935967-10de6ba17061",
  "1565557623262-b51c2513a641", "1562565652-a0d8f0c59eb4",
  "1513104890138-7c749659a591", "1579584425555-c3ce17fd4351",
  "1568901346375-23c9450c58cd", "1547573854-74d2a71d0826",
  "1490645935967-10de6ba17061", "1565958011703-44f9829ba187",
];

// Generic menu-item templates per cuisine (8 base items, varied by restaurant).
const itemTemplatesByCuisine = {
  Pizza: [
    ["Margherita", 14, "Tomato, mozzarella, basil"],
    ["Pepperoni", 16, "Cured pepperoni, mozzarella"],
    ["Quattro Formaggi", 17, "Four-cheese blend"],
    ["Funghi", 16, "Wild mushroom, thyme"],
    ["Diavola", 17, "Spicy salami, chili oil"],
    ["Bianca", 15, "White pizza, ricotta, garlic"],
    ["Capricciosa", 18, "Ham, mushroom, artichoke, olive"],
    ["Marinara", 13, "Tomato, garlic, oregano"],
  ],
  Sushi: [
    ["Salmon Nigiri (2pc)", 7, "Fresh Atlantic salmon"],
    ["Tuna Nigiri (2pc)", 8, "Yellowfin tuna"],
    ["California Roll", 11, "Crab, avocado, cucumber"],
    ["Spicy Tuna Roll", 12, "Tuna, sriracha mayo"],
    ["Dragon Roll", 15, "Eel, avocado, tobiko"],
    ["Rainbow Roll", 16, "Assorted sashimi over California"],
    ["Miso Soup", 4, "Tofu, scallion, wakame"],
    ["Edamame", 5, "Steamed soy beans, sea salt"],
  ],
  Burger: [
    ["Classic Burger", 12, "Beef, lettuce, tomato, pickle"],
    ["Cheese Burger", 13, "Add aged cheddar"],
    ["Bacon Burger", 15, "Bacon, cheddar, mayo"],
    ["Mushroom Swiss", 14, "Mushroom, swiss cheese"],
    ["BBQ Burger", 15, "BBQ sauce, onion ring"],
    ["Veggie Burger", 13, "Black bean, avocado"],
    ["Truffle Fries", 8, "Parmesan, truffle oil"],
    ["Onion Rings", 6, "Beer-battered, ranch"],
  ],
  Asian: [
    ["Beef & Broccoli", 14, "Garlic, soy, ginger"],
    ["Sweet & Sour Chicken", 13, "Pineapple, peppers"],
    ["Mongolian Beef", 15, "Scallion, soy glaze"],
    ["Kung Pao Chicken", 13, "Peanuts, chili"],
    ["Vegetable Lo Mein", 11, "Soft noodles, garden veg"],
    ["Pork Dumplings (6pc)", 9, "Soy-vinegar dip"],
    ["Hot & Sour Soup", 6, "Tofu, bamboo, egg"],
    ["Fried Rice", 10, "Egg, scallion, peas"],
  ],
  Mexican: [
    ["Beef Tacos (3pc)", 12, "Cilantro, onion, lime"],
    ["Chicken Burrito", 13, "Rice, beans, salsa"],
    ["Veggie Quesadilla", 11, "Cheese, peppers"],
    ["Chips & Guac", 8, "Fresh avocado, lime"],
    ["Pork Carnitas Bowl", 14, "Rice, beans, pico"],
    ["Fish Tacos (2pc)", 13, "Baja crema, cabbage"],
    ["Nachos Grande", 13, "Cheese, jalapeño, sour cream"],
    ["Churros (4pc)", 7, "Cinnamon sugar, chocolate"],
  ],
  Vegan: [
    ["Buddha Bowl", 13, "Quinoa, kale, tahini"],
    ["Cauliflower Tacos (3pc)", 12, "Salsa verde, cashew cream"],
    ["Chickpea Curry", 13, "Coconut, basmati rice"],
    ["Lentil Soup", 8, "Hearty, lemon-finished"],
    ["Veggie Sushi (8pc)", 11, "Avocado, cucumber, carrot"],
    ["Mushroom Risotto", 14, "Arborio, white wine"],
    ["Kale Caesar", 11, "Tempeh croutons"],
    ["Chocolate Avocado Mousse", 7, "Cacao, maple"],
  ],
  Indian: [
    ["Butter Chicken", 14, "Tomato, cream, basmati"],
    ["Chana Masala", 12, "Chickpeas, garam masala"],
    ["Lamb Vindaloo", 15, "Spicy, with potato"],
    ["Paneer Tikka", 13, "Tandoori-spiced cheese"],
    ["Vegetable Biryani", 12, "Aromatic basmati"],
    ["Naan", 4, "Brick-oven baked"],
    ["Garlic Naan", 5, "Fresh garlic, butter"],
    ["Mango Lassi", 5, "Yogurt smoothie"],
  ],
  Thai: [
    ["Pad Thai", 13, "Rice noodles, peanuts, lime"],
    ["Green Curry", 14, "Coconut, basil, chili"],
    ["Massaman Beef", 15, "Slow-cooked, peanut sauce"],
    ["Tom Yum Soup", 9, "Lemongrass, lime, chili"],
    ["Drunken Noodles", 13, "Wide rice noodles, basil"],
    ["Mango Sticky Rice", 8, "Coconut cream, fresh mango"],
    ["Thai Iced Tea", 4, "Sweet, creamy"],
    ["Spring Rolls (3pc)", 7, "Fresh herbs, peanut dip"],
  ],
};

export const restaurants = restaurantSeeds.map(([name, cuisine, rating, eta], i) => ({
  id: `rest-${String(i + 1).padStart(3, "0")}`,
  name,
  cuisine,
  rating,
  eta,
  deliveryFee: 3.99,
  hero: `https://images.unsplash.com/photo-${heroPhotos[i]}?w=800&q=80&auto=format`,
  thumb: `https://images.unsplash.com/photo-${heroPhotos[i]}?w=400&q=80&auto=format`,
  description: `${cuisine} restaurant. ${rating} stars · ~${eta} min.`,
  // Items: 12 per restaurant. 8 from the cuisine template + 4 picked from neighbors.
  items: (() => {
    const base = itemTemplatesByCuisine[cuisine].map(([n, p, d], j) => ({
      id: `rest-${String(i + 1).padStart(3, "0")}-item-${j + 1}`,
      name: n,
      price: p,
      description: d,
      photo: `https://picsum.photos/seed/${name.replace(/\s+/g, "")}${j}/400/300`,
    }));
    // Pad to 12 with cross-cuisine items.
    const cross = Object.values(itemTemplatesByCuisine)
      .flat()
      .filter((_, k) => k % 11 === (i % 11))
      .slice(0, 4)
      .map(([n, p, d], j) => ({
        id: `rest-${String(i + 1).padStart(3, "0")}-extra-${j + 1}`,
        name: n,
        price: p,
        description: d,
        photo: `https://picsum.photos/seed/${name.replace(/\s+/g, "")}x${j}/400/300`,
      }));
    return [...base, ...cross].slice(0, 12);
  })(),
}));

export { cuisines };
```

- [ ] **Step 3: Write `src/main.js`** — Alpine root with cart logic.

```js
import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { simulateNetwork }   from "./lib/skeleton.js";
import { restaurants, cuisines } from "./data.js";

window.appState = () => ({
  ...createRouter({ initial: "restaurants", views: ["restaurants", "menu", "cart", "checkout", "confirmation"] }),
  ...createPersistence({ namespace: "food-delivery", keys: ["cart"] }),

  restaurants,
  cuisines,

  // Filter state (in-memory; not persisted)
  filters: { cuisine: "all", minRating: 0, maxEta: 60 },
  filteredRestaurants: [],
  isLoading: false,

  // Current selection
  activeRestaurantId: null,

  // Cart shape: { restaurantId, items: [{itemId, qty}] }
  // Initialized to null by persistence factory; hydrated in init()
  cart: { restaurantId: null, items: [] },

  // Checkout form
  address: { line1: "", city: "", zip: "" },
  card: "",

  toastMsg: "",

  init() {
    this._hydrate();
    // Persistence factory defaults cart to [] but our shape is an object.
    // Recover or initialize.
    if (Array.isArray(this.cart) || !this.cart || typeof this.cart !== "object") {
      this.cart = { restaurantId: null, items: [] };
    }
    if (!this.cart.items) this.cart.items = [];
    this.applyFilters();
  },

  applyFilters() {
    this.filteredRestaurants = this.restaurants.filter((r) =>
      (this.filters.cuisine === "all" || r.cuisine === this.filters.cuisine) &&
      r.rating >= this.filters.minRating &&
      r.eta <= this.filters.maxEta
    );
  },

  async openMenu(restaurantId) {
    this.activeRestaurantId = restaurantId;
    this.isLoading = true;
    this.setView("menu");
    await simulateNetwork();
    this.isLoading = false;
  },

  get activeRestaurant() {
    return this.restaurants.find((r) => r.id === this.activeRestaurantId);
  },

  get cartTotal() {
    if (!this.cart.items.length) return 0;
    const rest = this.restaurants.find((r) => r.id === this.cart.restaurantId);
    if (!rest) return 0;
    return this.cart.items.reduce((sum, line) => {
      const item = rest.items.find((it) => it.id === line.itemId);
      return sum + (item ? item.price * line.qty : 0);
    }, 0);
  },

  get cartCount() {
    return this.cart.items.reduce((sum, line) => sum + line.qty, 0);
  },

  get cartDeliveryFee() {
    return this.cart.items.length ? 3.99 : 0;
  },

  get cartTax() {
    return Math.round(this.cartTotal * 0.08 * 100) / 100;
  },

  get cartGrandTotal() {
    return Math.round((this.cartTotal + this.cartDeliveryFee + this.cartTax) * 100) / 100;
  },

  addItem(itemId) {
    // If cart belongs to a different restaurant, replace.
    if (this.cart.restaurantId && this.cart.restaurantId !== this.activeRestaurantId) {
      this.cart = { restaurantId: this.activeRestaurantId, items: [] };
    }
    if (!this.cart.restaurantId) this.cart.restaurantId = this.activeRestaurantId;
    const line = this.cart.items.find((l) => l.itemId === itemId);
    if (line) line.qty++;
    else this.cart.items.push({ itemId, qty: 1 });
    this._save("cart");
    this.toast("Added to cart");
  },

  removeItem(itemId) {
    const line = this.cart.items.find((l) => l.itemId === itemId);
    if (!line) return;
    line.qty--;
    if (line.qty <= 0) {
      this.cart.items = this.cart.items.filter((l) => l.itemId !== itemId);
    }
    if (this.cart.items.length === 0) this.cart.restaurantId = null;
    this._save("cart");
  },

  clearCart() {
    this.cart = { restaurantId: null, items: [] };
    this._save("cart");
  },

  itemQty(itemId) {
    const line = this.cart.items.find((l) => l.itemId === itemId);
    return line ? line.qty : 0;
  },

  // Called from the checkout view's "Confirm order" button (NOT from the cart view).
  // The cart view's "Place order" button advances to checkout via setView('checkout').
  placeOrder() {
    this.toast("Order placed!");
    this.clearCart();
    this.setView("confirmation");
  },

  toast(msg) {
    this.toastMsg = msg;
    setTimeout(() => { this.toastMsg = ""; }, 2000);
  },
});
```

- [ ] **Step 4: Write `index.html`** with 5 views (restaurants, menu, cart, checkout, confirmation). The implementer writes the views following these patterns:

**View 1 — `restaurants`:** cuisine pills, rating + eta sliders, grid of restaurant cards (image + name + rating + eta).

**View 2 — `menu`:** restaurant hero banner, items grid where each item has a +/- stepper bound to `itemQty(itemId)` / `addItem(itemId)` / `removeItem(itemId)`.

**View 3 — `cart`:** line items with stepper, subtotal/delivery/tax/total breakdown, "Place order" button.

**View 4 — `checkout`:** address form (street, city, zip) + card last-4 input. Submit advances to confirmation.

**View 5 — `confirmation`:** "On its way" + decorative map placeholder + "Back to restaurants" button.

Use the same overall HTML skeleton as Task 3 (Tailwind CDN, Alpine.js script, font links, `<body x-data="appState()" x-init="init()">`, header from Block D adapted with cart-count badge). Substitute palette CSS custom properties in `styles/main.css`:

```css
:root {
  --bg: #fff8ec;
  --text: #1a1208;
  --accent: #ff8c42;
  --accent-soft: #ffe6c9;
}
body { font-family: "Inter", ui-sans-serif, sans-serif; }
.heading-font { font-family: "DM Sans", ui-sans-serif, sans-serif; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}
[x-cloak] { display: none !important; }
```

- [ ] **Step 5: Add cart-count badge to the header** (Block D variant for food-delivery):

```html
<button @click="setView('cart')" class="relative px-3 py-1.5 bg-[var(--accent)] text-white rounded text-sm">
  Cart
  <span x-show="cartCount > 0"
    class="absolute -top-1 -right-1 bg-black text-white text-xs rounded-full w-5 h-5 flex items-center justify-center"
    x-text="cartCount"></span>
</button>
```

- [ ] **Step 6: Smoke test.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-functional-templates/mcp-servers/tasks/template_apps/food-delivery"
python -m http.server 8201
```

Verify in browser at `http://localhost:8201`:
- Restaurants view shows 14 restaurants
- Click cuisine pill → list filters
- Click first restaurant → menu view loads (with brief skeleton)
- Click + on an item three times → cart-count badge in header reads "3"
- Click cart button → cart view shows the 3 items, correct subtotal/tax/total
- Reload page → cart-count badge still "3" (localStorage persisted)
- Click - twice → item removed when qty hits 0
- "Place order" → confirmation view, cart now empty

- [ ] **Step 7: Write `README.md`** (1-paragraph + customize section + image whitelist note).

- [ ] **Step 8: Commit.**

```bash
git add mcp-servers/tasks/template_apps/food-delivery/
git commit -m "feat(template): food-delivery cart-driven marketplace"
```

---

### Task 5: Job board template

**Files to create:** `mcp-servers/tasks/template_apps/job-board/` (same scaffold as Task 3, no `countUp.js`)

**Goal:** Job list with debounced 250ms search, multi-filter chips, bookmark toggle, application form.

- [ ] **Step 1: Create scaffolding and paste Blocks A, B, C into `src/lib/`.**

```bash
mkdir -p mcp-servers/tasks/template_apps/job-board/{styles,src/lib,public}
touch mcp-servers/tasks/template_apps/job-board/public/.gitkeep
```

- [ ] **Step 2: Write `src/data.js`** — ~60 jobs across 12 companies.

```js
// src/data.js — job catalog, stable IDs.

const companies = [
  ["Northwind Logistics", "Logistics", "Boston, MA"],
  ["Lumen Health", "Healthcare", "Austin, TX"],
  ["Halftone Studio", "Design", "Remote"],
  ["Cirrus Cloud", "DevOps", "San Francisco, CA"],
  ["Aegis Security", "Cybersecurity", "Remote"],
  ["Pacific Crest Bank", "Fintech", "Seattle, WA"],
  ["Skylane Travel", "Travel-tech", "Remote"],
  ["Verde Wellness", "Consumer", "Brooklyn, NY"],
  ["Helios Energy", "Climate-tech", "Denver, CO"],
  ["Veridian Robotics", "Robotics", "Pittsburgh, PA"],
  ["DevCon Berlin", "Events", "Berlin, DE"],
  ["Salt & Pan Media", "Media", "Remote"],
];

const roleSeeds = [
  ["Senior Frontend Engineer", "Engineering", "senior", 145, 180, "remote"],
  ["Staff Backend Engineer", "Engineering", "staff+", 175, 230, "hybrid"],
  ["Product Designer", "Design", "mid", 110, 140, "remote"],
  ["Senior Product Manager", "PM", "senior", 150, 200, "hybrid"],
  ["Data Engineer", "Data", "mid", 130, 165, "remote"],
  ["Marketing Lead", "Marketing", "senior", 120, 155, "hybrid"],
  ["DevOps Engineer", "Engineering", "mid", 125, 160, "remote"],
  ["Junior Frontend Developer", "Engineering", "junior", 75, 105, "onsite"],
  ["Senior UX Researcher", "Design", "senior", 130, 170, "remote"],
  ["Engineering Manager", "Engineering", "staff+", 195, 250, "hybrid"],
  ["Content Strategist", "Marketing", "mid", 90, 120, "remote"],
  ["Machine Learning Engineer", "Data", "senior", 165, 220, "hybrid"],
];

// 60 jobs = 12 companies × 5 roles each (rotated through roleSeeds).
export const jobs = (() => {
  const out = [];
  let id = 1;
  for (let c = 0; c < companies.length; c++) {
    for (let r = 0; r < 5; r++) {
      const role = roleSeeds[(c + r) % roleSeeds.length];
      const [comp, industry, baseLocation] = companies[c];
      out.push({
        id: `job-${String(id++).padStart(3, "0")}`,
        title: role[0],
        company: comp,
        industry,
        location: role[5] === "remote" ? "Remote" : baseLocation,
        remoteMode: role[5],
        roleFamily: role[1],
        seniority: role[2],
        salaryMin: role[3] * 1000,
        salaryMax: role[4] * 1000,
        postedDaysAgo: ((c * 5 + r) % 14) + 1,
        // DiceBear initials avatar
        logo: `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(comp)}&backgroundColor=2563eb`,
        description: [
          `Join ${comp} as a ${role[0]}.`,
          `Reporting to the Head of ${role[1]}, you'll own the roadmap for our ${industry.toLowerCase()} platform — shipping product to customers across our core markets.`,
          `**Requirements:** 5+ years of experience, strong fundamentals, ability to mentor. Familiarity with our stack (TypeScript, Python, Postgres) is a plus.`,
          `**We offer:** competitive comp ($${role[3]}k-$${role[4]}k), full benefits, ${role[5]} working, generous PTO, learning budget.`,
        ].join("\n\n"),
      });
    }
  }
  return out.sort((a, b) => a.postedDaysAgo - b.postedDaysAgo);
})();

export const companiesList = companies.map(([name]) => name);
export const roleFamilies = ["Engineering", "Design", "PM", "Marketing", "Data"];
```

- [ ] **Step 3: Write `src/main.js`** — Alpine root with debounced search + bookmark.

```js
import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { simulateNetwork }   from "./lib/skeleton.js";
import { jobs, roleFamilies } from "./data.js";

window.appState = () => ({
  ...createRouter({ initial: "list", views: ["list", "detail", "apply", "submitted"] }),
  ...createPersistence({ namespace: "job-board", keys: ["savedJobs"] }),

  jobs,
  roleFamilies,
  filteredJobs: jobs,
  isLoading: false,

  filters: {
    search: "",
    remoteMode: "any",
    salaryMin: 60000,
    salaryMax: 300000,
    roleFamilies: [],
    seniority: "any",
  },

  _searchTimer: null,
  selectedJobId: null,
  application: { name: "", email: "", resume: "", cover: "" },
  trackingId: "",
  toastMsg: "",

  init() {
    this._hydrate();
    this.applyFilters();
  },

  onSearchInput() {
    if (this._searchTimer) clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(() => this.applyFilters(), 250);
  },

  applyFilters() {
    const q = this.filters.search.trim().toLowerCase();
    this.filteredJobs = this.jobs.filter((j) =>
      (q === "" || j.title.toLowerCase().includes(q) || j.company.toLowerCase().includes(q)) &&
      (this.filters.remoteMode === "any" || j.remoteMode === this.filters.remoteMode) &&
      j.salaryMin >= this.filters.salaryMin &&
      j.salaryMax <= this.filters.salaryMax + 50000 &&
      (this.filters.roleFamilies.length === 0 || this.filters.roleFamilies.includes(j.roleFamily)) &&
      (this.filters.seniority === "any" || j.seniority === this.filters.seniority)
    );
  },

  toggleRoleFamily(name) {
    const i = this.filters.roleFamilies.indexOf(name);
    if (i >= 0) this.filters.roleFamilies.splice(i, 1);
    else this.filters.roleFamilies.push(name);
    this.applyFilters();
  },

  openJob(jobId) {
    this.selectedJobId = jobId;
    this.setView("detail");
  },

  toggleSave(jobId) {
    const i = this.savedJobs.indexOf(jobId);
    if (i >= 0) this.savedJobs.splice(i, 1);
    else this.savedJobs.push(jobId);
    this._save("savedJobs");
  },

  isSaved(jobId) { return this.savedJobs.includes(jobId); },

  get selectedJob() {
    return this.jobs.find((j) => j.id === this.selectedJobId);
  },

  async submitApplication() {
    if (!this.application.name || !this.application.email || !this.application.cover) return;
    this.isLoading = true;
    await simulateNetwork();
    this.isLoading = false;
    this.trackingId = `APP-${Math.floor(Math.random() * 90000 + 10000)}`;
    this.setView("submitted");
    this.application = { name: "", email: "", resume: "", cover: "" };
  },

  postedLabel(days) {
    if (days === 0) return "Today";
    if (days === 1) return "Yesterday";
    return `${days} days ago`;
  },

  formatSalary(min, max) {
    return `$${Math.round(min / 1000)}k – $${Math.round(max / 1000)}k`;
  },

  toast(msg) { this.toastMsg = msg; setTimeout(() => { this.toastMsg = ""; }, 2000); },
});
```

- [ ] **Step 4: Write `index.html`** with 4 views (list, detail, apply, submitted).

**View 1 — `list`:** sticky filter sidebar (search input bound to `filters.search` with `@input="onSearchInput()"`, remote-mode toggle, salary range slider, role-family multi-select pills, seniority pills) + job cards grid. Each card shows logo, title, company, location, salary, posted-date, bookmark toggle button.

**View 2 — `detail`:** "← Back to results" button, full job description (formatted with `\n\n` paragraphs), company info card, "Save" + "Apply" buttons.

**View 3 — `apply`:** form with name/email/resume/cover, validation (required fields). Submit calls `submitApplication()`.

**View 4 — `submitted`:** "Application sent" + tracking ID. "Back to jobs" button.

Header from Block D, adapted with "Saved (n)" counter linking to a saved-jobs filter (or just shown as text). Use `var(--accent)` = `#2563eb`.

- [ ] **Step 5: Write `styles/main.css`.**

```css
:root {
  --bg: #ffffff;
  --bg-card: #f8fafc;
  --text: #0f172a;
  --text-muted: #64748b;
  --accent: #2563eb;
  --border: #e2e8f0;
}
body { font-family: "Inter", ui-sans-serif, sans-serif; background: var(--bg); color: var(--text); }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}
[x-cloak] { display: none !important; }
article { transition: transform 150ms ease-out, box-shadow 150ms; }
article:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
```

- [ ] **Step 6: Smoke test.**

```bash
cd template_apps/job-board
python -m http.server 8202
```

Verify:
- List view shows 60 jobs
- Type "Engineer" in search → list filters in ~250ms
- Toggle "Remote" filter → list narrows
- Click bookmark on a job → icon fills
- Reload → bookmark still filled (localStorage)
- Click job card → detail view, description renders
- Click "Apply" → form view
- Submit with valid fields → submitted view with tracking ID

- [ ] **Step 7: Write `README.md` + commit.**

```bash
git add mcp-servers/tasks/template_apps/job-board/
git commit -m "feat(template): job-board with debounced search and bookmarks"
```

---

### Task 6: Movie tickets template

**Files to create:** `mcp-servers/tasks/template_apps/movie-tickets/` (same scaffold + `src/lib/countUp.js` from Block F)

**Goal:** The interactive seat picker is the highlight. 10×14 grid with available/taken/selected/aisle states, running total animates count-up.

- [ ] **Step 1: Create scaffolding + paste Blocks A, B, C, F.**

```bash
mkdir -p mcp-servers/tasks/template_apps/movie-tickets/{styles,src/lib,public}
touch mcp-servers/tasks/template_apps/movie-tickets/public/.gitkeep
```

- [ ] **Step 2: Write `src/data.js`** — 12 films, 3 theaters, ~5 showtimes each.

```js
// src/data.js — film catalog with showtimes + per-showtime seat occupancy.

// Stable Unsplash photo IDs that look like film stills / cinema imagery.
const posterIds = [
  "1489599849927-2ee91cede3ba", "1502136969935-8d8eef54d77b",
  "1517604931442-7e0c8ed2963c", "1485846234645-a62644f84728",
  "1542204165-65bf26472b9b", "1478720568477-152d9b164e26",
  "1543536448-d209d2d13a1c", "1554080353-a576cf803bda",
  "1499415479124-43c32433a620", "1536440136628-849c177e76a1",
  "1485095329183-d0797cdc5676", "1518929458119-e5bf444c30f4",
];

const filmSeeds = [
  ["Dune Pt 2", "PG-13", "Sci-Fi", 166, "Paul Atreides unites with Chani and the Fremen."],
  ["The Crow", "R", "Action", 110, "A musician resurrected to avenge his murder."],
  ["Argylle", "PG-13", "Action / Comedy", 139, "A reclusive spy novelist becomes entangled in real espionage."],
  ["Madame Web", "PG-13", "Action", 116, "A clairvoyant New York paramedic unlocks her powers."],
  ["Drive-Away Dolls", "R", "Comedy", 84, "Two friends embark on a wild road trip."],
  ["Ordinary Angels", "PG", "Drama", 116, "A small-town hairdresser rallies her community."],
  ["Bob Marley: One Love", "PG-13", "Biopic", 107, "The story of the music icon."],
  ["Wonka", "PG", "Family", 116, "A young Willy Wonka begins his chocolate adventure."],
  ["Migration", "PG", "Animation", 92, "A duck family on their first migration."],
  ["The Beekeeper", "R", "Action", 105, "A man's quest for vengeance takes a national turn."],
  ["Anyone But You", "R", "Comedy", 103, "Two enemies fake-date at a wedding in Australia."],
  ["The Iron Claw", "R", "Drama", 132, "The rise and fall of the Von Erich wrestling family."],
];

export const films = filmSeeds.map(([title, rating, genre, runtime, synopsis], i) => ({
  id: `film-${String(i + 1).padStart(2, "0")}`,
  title,
  rating,
  genre,
  runtime,
  synopsis,
  poster: `https://images.unsplash.com/photo-${posterIds[i]}?w=600&q=80&auto=format`,
}));

export const theaters = [
  { id: "th-1", name: "Lumen Downtown", address: "1200 Market St" },
  { id: "th-2", name: "Lumen Westside", address: "4400 Sunset Blvd" },
  { id: "th-3", name: "Lumen Bayview", address: "88 Bayview Ave" },
];

// Showtimes: per film × per theater × 5 times.
const showtimeSlots = ["12:30", "15:00", "17:30", "20:00", "22:30"];

// Pre-generate seat occupancy per showtime so it's stable across renders.
// 10 rows × 14 cols. Aisle = cols 5 & 10. ~30% randomly taken (deterministic by showtime hash).
const SEAT_PRICE = 14;

function hash(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = ((h << 5) - h + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export const showtimes = (() => {
  const out = [];
  films.forEach((f) => {
    theaters.forEach((t) => {
      showtimeSlots.forEach((slot) => {
        const id = `${f.id}-${t.id}-${slot.replace(":", "")}`;
        // Deterministic seat occupancy via hash.
        const seed = hash(id);
        const taken = new Set();
        for (let r = 0; r < 10; r++) {
          for (let c = 0; c < 14; c++) {
            if (c === 4 || c === 9) continue;  // aisle
            // ~30% taken
            if ((seed * (r + 1) * (c + 2)) % 10 < 3) taken.add(`${r}-${c}`);
          }
        }
        out.push({
          id, filmId: f.id, theaterId: t.id, slot,
          takenSeats: Array.from(taken),
        });
      });
    });
  });
  return out;
})();

export { SEAT_PRICE };
```

- [ ] **Step 3: Write `src/main.js`** — Alpine root with seat picker logic.

```js
import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { simulateNetwork }   from "./lib/skeleton.js";
import { createCountUp }     from "./lib/countUp.js";
import { films, theaters, showtimes, SEAT_PRICE } from "./data.js";

const MAX_SEATS = 8;
const ROWS = 10;
const COLS = 14;
const AISLES = new Set([4, 9]);

window.appState = () => ({
  ...createRouter({ initial: "now-showing", views: ["now-showing", "film", "showtime", "seats", "checkout", "tickets"] }),
  ...createPersistence({ namespace: "movie-tickets", keys: ["bookedShowings"] }),

  films, theaters, showtimes,
  filters: { genre: "all", theaterId: "all" },
  filteredFilms: films,

  // Selection state
  selectedFilmId: null,
  selectedShowtimeId: null,
  selectedSeats: [],         // array of "row-col" strings

  // Counter (animated)
  displayedTotal: 0,
  _countUp: null,

  toastMsg: "",

  init() {
    this._hydrate();
    this._countUp = createCountUp(300);
    this.applyFilters();
  },

  applyFilters() {
    this.filteredFilms = this.films.filter((f) =>
      this.filters.genre === "all" || f.genre.toLowerCase().includes(this.filters.genre.toLowerCase())
    );
  },

  openFilm(filmId) { this.selectedFilmId = filmId; this.setView("film"); },

  pickShowtime(showtimeId) {
    this.selectedShowtimeId = showtimeId;
    this.selectedSeats = [];
    this.displayedTotal = 0;
    this.setView("seats");
  },

  get selectedFilm() { return this.films.find((f) => f.id === this.selectedFilmId); },
  get selectedShowtime() { return this.showtimes.find((s) => s.id === this.selectedShowtimeId); },

  isAisle(row, col) { return AISLES.has(col); },
  isTaken(row, col) { return this.selectedShowtime?.takenSeats.includes(`${row}-${col}`); },
  isSelected(row, col) { return this.selectedSeats.includes(`${row}-${col}`); },

  seatClass(row, col) {
    if (this.isAisle(row, col)) return "bg-transparent";
    if (this.isTaken(row, col)) return "bg-gray-700 cursor-not-allowed";
    if (this.isSelected(row, col)) return "bg-[var(--accent)] text-black scale-110";
    return "bg-gray-500 hover:bg-gray-400 cursor-pointer";
  },

  toggleSeat(row, col) {
    if (this.isAisle(row, col) || this.isTaken(row, col)) return;
    const key = `${row}-${col}`;
    const idx = this.selectedSeats.indexOf(key);
    if (idx >= 0) this.selectedSeats.splice(idx, 1);
    else if (this.selectedSeats.length < MAX_SEATS) this.selectedSeats.push(key);
    // Animate total
    const target = this.selectedSeats.length * SEAT_PRICE;
    this._countUp.to(target, (v) => { this.displayedTotal = v; });
  },

  rows() { return Array.from({ length: ROWS }, (_, r) => r); },
  cols() { return Array.from({ length: COLS }, (_, c) => c); },

  goCheckout() {
    if (this.selectedSeats.length === 0) return;
    this.setView("checkout");
  },

  confirmPayment() {
    this.bookedShowings.push({
      id: this.selectedShowtimeId,
      seats: [...this.selectedSeats],
      total: this.selectedSeats.length * SEAT_PRICE,
      bookedAt: new Date().toISOString(),
    });
    this._save("bookedShowings");
    this.setView("tickets");
  },

  startOver() {
    this.selectedFilmId = null;
    this.selectedShowtimeId = null;
    this.selectedSeats = [];
    this.displayedTotal = 0;
    this.setView("now-showing");
  },

  showtimesForFilm(filmId) {
    return this.showtimes.filter((s) => s.filmId === filmId &&
      (this.filters.theaterId === "all" || s.theaterId === this.filters.theaterId));
  },

  theaterById(id) { return this.theaters.find((t) => t.id === id); },

  toast(msg) { this.toastMsg = msg; setTimeout(() => { this.toastMsg = ""; }, 2000); },
});
```

- [ ] **Step 4: Write `index.html` views.** The seat picker view is the centerpiece. Inside the `<section x-show="view === 'seats'">`:

```html
<section x-show="view === 'seats'" x-transition.duration.200ms class="max-w-3xl mx-auto px-4 py-8" x-cloak>
  <button @click="back()" class="text-white/60 hover:text-white mb-6">← Back</button>
  <h2 class="text-2xl font-bold text-white" x-text="selectedFilm?.title + ' · ' + selectedShowtime?.slot"></h2>
  <p class="text-white/50 mb-6" x-text="theaterById(selectedShowtime?.theaterId)?.name"></p>

  <!-- Screen indicator -->
  <div class="text-center text-xs text-white/40 mb-4 border-t border-[var(--accent)]/40 pt-2">SCREEN</div>

  <!-- Seat grid -->
  <div class="space-y-2 max-w-2xl mx-auto" role="grid" aria-label="Seat selection">
    <template x-for="row in rows()" :key="row">
      <div class="flex gap-1 justify-center items-center">
        <span class="w-6 text-center text-xs text-white/40" x-text="String.fromCharCode(65 + row)"></span>
        <template x-for="col in cols()" :key="col">
          <button
            @click="toggleSeat(row, col)"
            :class="seatClass(row, col)"
            :aria-label="`Row ${String.fromCharCode(65 + row)} seat ${col + 1}` + (isTaken(row, col) ? ' (unavailable)' : isSelected(row, col) ? ' (selected)' : '')"
            :disabled="isAisle(row, col) || isTaken(row, col)"
            class="w-7 h-7 rounded transition-all duration-150"></button>
        </template>
      </div>
    </template>
  </div>

  <!-- Sticky total bar -->
  <div class="mt-8 bg-white/5 rounded-xl p-4 flex items-center justify-between">
    <div>
      <div class="text-xs text-white/50">Selected</div>
      <div class="text-white font-semibold" x-text="selectedSeats.length + ' / 8 seats'"></div>
    </div>
    <div>
      <div class="text-xs text-white/50">Total</div>
      <div class="text-2xl font-bold text-[var(--accent)]" x-text="`$${displayedTotal}`"></div>
    </div>
    <button @click="goCheckout()" :disabled="selectedSeats.length === 0"
      :class="selectedSeats.length === 0 ? 'opacity-40 cursor-not-allowed' : 'hover:opacity-90'"
      class="bg-[var(--accent)] text-black font-semibold rounded px-5 py-2 transition">
      Continue
    </button>
  </div>
</section>
```

Other views (`now-showing` poster grid, `film` detail, `showtime` picker, `checkout` summary, `tickets` confirmation with QR-code SVG placeholder) follow the standard pattern. Use palette tokens in `styles/main.css`:

```css
:root {
  --bg: #0a0a0a;
  --bg-card: #1a1a1a;
  --text: #ffffff;
  --accent: #f59e0b;
}
body { font-family: "Inter", ui-sans-serif, sans-serif; background: var(--bg); color: var(--text); }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}
[x-cloak] { display: none !important; }
.poster:hover { transform: scale(1.02); }
.poster { transition: transform 150ms; }
```

- [ ] **Step 5: Smoke test.**

```bash
cd template_apps/movie-tickets
python -m http.server 8203
```

Verify:
- Now-showing grid shows 12 posters
- Click a film → film detail
- Click a showtime → seat picker
- Click 2 available seats → both turn amber, total animates to "$28"
- Try clicking a taken (dark gray) seat → no change
- Try clicking 9 seats → 9th is blocked (max 8)
- "Continue" → checkout
- "Pay" → tickets view with QR placeholder

- [ ] **Step 6: Write `README.md` + commit.**

```bash
git add mcp-servers/tasks/template_apps/movie-tickets/
git commit -m "feat(template): movie-tickets with interactive seat picker"
```

---

### Task 7: Recipe site template

**Files to create:** `mcp-servers/tasks/template_apps/recipe-site/` (same scaffold + `src/lib/countUp.js` for ingredient-quantity tweens)

**Goal:** Catalog browse → recipe detail with live serving-size slider that rescales ingredient quantities (½ cup not 0.5 cup) → fullscreen cook mode with step timer and wakelock attempt.

- [ ] **Step 1: Create scaffolding + paste Blocks A, B, C, F.**

```bash
mkdir -p mcp-servers/tasks/template_apps/recipe-site/{styles,src/lib,public}
touch mcp-servers/tasks/template_apps/recipe-site/public/.gitkeep
```

- [ ] **Step 2: Write `src/data.js`** — ~30 recipes with ingredients and steps.

```js
// src/data.js — recipe catalog. Ingredients use { qty, unit, name }
// shape so quantities can scale linearly with servings.

const photoIds = [
  "1565299624946-b28f40a0ae38", "1490645935967-10de6ba17061",
  "1565958011703-44f9829ba187", "1546069901-ba9599a7e63c",
  "1565557623262-b51c2513a641", "1551782450-a2132b4ba21d",
  "1567620905732-2d1ec7ab7445", "1551183053-bf91a1d81141",
  "1565299507177-b0ac66763828", "1540189549336-e6e99c3679fe",
  "1502301197179-65228ab57f78", "1572441710269-fda88a25dc46",
  "1543353071-873f17a7a088", "1490645935967-10de6ba17061",
  "1565958011703-44f9829ba187", "1546069901-ba9599a7e63c",
  "1565557623262-b51c2513a641", "1542010589-c5d49a40c69e",
  "1546069901-ba9599a7e63c", "1547592180-85f173990554",
  "1540189549336-e6e99c3679fe", "1502301197179-65228ab57f78",
  "1572441710269-fda88a25dc46", "1543353071-873f17a7a088",
  "1543339494-b4cd0e80c1c8", "1546069901-ba9599a7e63c",
  "1551782450-a2132b4ba21d", "1567620905732-2d1ec7ab7445",
  "1551183053-bf91a1d81141", "1565299507177-b0ac66763828",
];

const recipeSeeds = [
  ["Lemon Garlic Pasta", ["vegan"], "easy", 25, "A bright weeknight pasta with lemon and toasted garlic."],
  ["Cacio e Pepe", ["vegetarian"], "medium", 20, "Three ingredients, all about technique."],
  ["Mushroom Risotto", ["vegetarian", "gluten-free"], "medium", 45, "Wild mushrooms, white wine, parmesan."],
  ["Chickpea Curry", ["vegan", "gluten-free"], "easy", 30, "Coconut, garam masala, basmati rice."],
  ["Roasted Tomato Soup", ["vegan", "gluten-free"], "easy", 40, "Slow-roasted tomatoes blended smooth."],
  ["Bibimbap Bowl", ["vegetarian"], "medium", 45, "Korean rice bowl with sautéed veg + egg."],
  ["Lentil Bolognese", ["vegan"], "medium", 35, "Hearty plant-based ragu."],
  ["Cauliflower Tacos", ["vegan"], "easy", 25, "Spiced cauliflower, salsa verde, cashew cream."],
  ["Greek Salad", ["vegetarian", "gluten-free"], "easy", 12, "Crisp vegetables, feta, olive oil."],
  ["Coconut Curry Soup", ["vegan", "gluten-free"], "easy", 25, "Thai-inspired, lime + ginger."],
  ["Caprese Skewers", ["vegetarian", "gluten-free"], "easy", 10, "Tomato, mozzarella, basil, balsamic."],
  ["Sweet Potato Hash", ["vegan", "gluten-free"], "easy", 30, "Breakfast hash with peppers + onions."],
  ["Beef & Broccoli", [], "medium", 30, "Classic stir-fry with garlic sauce."],
  ["Chicken Tikka Masala", ["gluten-free"], "medium", 45, "Marinated chicken in spiced tomato cream."],
  ["Salmon Teriyaki", ["gluten-free", "dairy-free"], "easy", 20, "Glazed salmon, jasmine rice, edamame."],
  ["Shakshuka", ["vegetarian", "gluten-free"], "easy", 25, "Eggs poached in spiced tomato."],
  ["Roasted Veg Bowl", ["vegan", "gluten-free"], "easy", 35, "Seasonal veg, tahini drizzle."],
  ["Carbonara", ["dairy-free"], "easy", 20, "Pancetta, egg, pecorino, pepper."],
  ["Spinach Lasagna", ["vegetarian"], "medium", 60, "Layered with béchamel and ricotta."],
  ["Pesto Gnocchi", ["vegetarian"], "easy", 15, "Fresh basil pesto, toasted pine nuts."],
  ["Crispy Tofu Bowl", ["vegan", "gluten-free"], "easy", 25, "Cornstarch-crisped tofu, sticky rice."],
  ["Chana Masala", ["vegan", "gluten-free"], "easy", 30, "Chickpeas, onion, ginger, garam masala."],
  ["Quinoa Buddha Bowl", ["vegan", "gluten-free"], "easy", 25, "Roasted veg, tahini, lemon."],
  ["Eggplant Parmesan", ["vegetarian"], "medium", 50, "Layered, baked, golden."],
  ["Banh Mi Bowl", ["dairy-free"], "easy", 30, "Pork, pickled veg, sriracha mayo."],
  ["Black Bean Tacos", ["vegan"], "easy", 15, "Smoky black beans, lime crema."],
  ["Tuscan Bean Soup", ["vegan", "gluten-free"], "easy", 35, "White beans, kale, rosemary."],
  ["Stuffed Bell Peppers", ["gluten-free"], "medium", 50, "Rice, beef, herbs, tomato."],
  ["Spring Rolls", ["vegan", "gluten-free"], "easy", 20, "Rice paper, herbs, peanut sauce."],
  ["Apple Crumble", ["vegetarian"], "easy", 45, "Cinnamon apples, buttery oat topping."],
];

// 4-step generator (most recipes have 6-10 steps; 8 here for consistency).
const stepTemplates = [
  "Prep ingredients: wash, chop, and measure everything.",
  "Heat oil in a large skillet over medium-high heat.",
  "Add aromatics (onion, garlic, ginger) and cook for 2-3 minutes until fragrant.",
  "Add the main ingredient and stir to coat.",
  "Pour in liquids (broth, sauce, or water) and bring to a simmer.",
  "Cover and cook for 10-15 minutes, stirring occasionally.",
  "Taste and adjust seasoning with salt, pepper, and acid (lemon or vinegar).",
  "Plate, garnish, and serve immediately while hot.",
];

const ingredientTemplates = [
  { qty: 1, unit: "lb", name: "main protein or base (substitute as needed)" },
  { qty: 2, unit: "tbsp", name: "olive oil" },
  { qty: 3, unit: "clove", name: "garlic, minced" },
  { qty: 1, unit: "cup", name: "broth or stock" },
  { qty: 0.5, unit: "tsp", name: "salt" },
  { qty: 0.25, unit: "tsp", name: "black pepper" },
  { qty: 1, unit: "", name: "lemon, juiced" },
  { qty: 2, unit: "tbsp", name: "fresh herbs, chopped" },
];

export const recipes = recipeSeeds.map(([title, diet, difficulty, minutes, intro], i) => ({
  id: `rec-${String(i + 1).padStart(3, "0")}`,
  title, diet, difficulty, minutes, intro,
  hero: `https://images.unsplash.com/photo-${photoIds[i] || photoIds[0]}?w=800&q=80&auto=format`,
  thumb: `https://images.unsplash.com/photo-${photoIds[i] || photoIds[0]}?w=400&q=80&auto=format`,
  baseServings: 2,
  ingredients: ingredientTemplates.map((ing, j) => ({
    ...ing,
    name: j === 0 ? title.toLowerCase().split(" ")[0] : ing.name,
  })),
  steps: stepTemplates,
}));
```

- [ ] **Step 3: Write `src/main.js`** with serving-scale + cook mode + wakelock.

```js
import { createRouter }      from "./lib/router.js";
import { createPersistence } from "./lib/persistence.js";
import { simulateNetwork }   from "./lib/skeleton.js";
import { recipes }           from "./data.js";

const FRACTIONS = [
  [0.125, "⅛"], [0.25, "¼"], [0.333, "⅓"], [0.5, "½"],
  [0.667, "⅔"], [0.75, "¾"],
];

function formatQuantity(value) {
  if (value === 0) return "";
  const whole = Math.floor(value);
  const frac = Math.round((value - whole) * 1000) / 1000;
  // Find nearest fraction within tolerance
  let glyph = "";
  for (const [v, sym] of FRACTIONS) {
    if (Math.abs(frac - v) < 0.04) { glyph = sym; break; }
  }
  if (whole === 0 && glyph) return glyph;
  if (whole > 0 && glyph) return `${whole} ${glyph}`;
  if (whole > 0 && frac === 0) return `${whole}`;
  return value.toFixed(2).replace(/\.?0+$/, "");
}

window.appState = () => ({
  ...createRouter({ initial: "catalog", views: ["catalog", "recipe", "cook-mode", "completed"] }),
  ...createPersistence({ namespace: "recipe-site", keys: ["favorites", "cookingHistory"] }),

  recipes,
  filteredRecipes: recipes,
  filters: { ingredientSearch: "", diet: [], timeBucket: "any", difficulty: "any" },

  selectedRecipeId: null,
  servings: 2,
  stepIndex: 0,
  timer: { remaining: 0, running: false, _interval: null },
  wakeLock: null,

  toastMsg: "",

  init() {
    this._hydrate();
    this.applyFilters();
    // Audio chime on timer complete
    this._chime = new Audio("data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=");
  },

  applyFilters() {
    const q = this.filters.ingredientSearch.trim().toLowerCase();
    this.filteredRecipes = this.recipes.filter((r) =>
      (q === "" || r.ingredients.some((ing) => ing.name.toLowerCase().includes(q)) || r.title.toLowerCase().includes(q)) &&
      (this.filters.diet.length === 0 || this.filters.diet.every((d) => r.diet.includes(d))) &&
      (this.filters.timeBucket === "any" || (
        this.filters.timeBucket === "<15" ? r.minutes < 15 :
        this.filters.timeBucket === "<30" ? r.minutes < 30 :
        this.filters.timeBucket === "<60" ? r.minutes < 60 : true
      )) &&
      (this.filters.difficulty === "any" || r.difficulty === this.filters.difficulty)
    );
  },

  toggleDiet(d) {
    const i = this.filters.diet.indexOf(d);
    if (i >= 0) this.filters.diet.splice(i, 1);
    else this.filters.diet.push(d);
    this.applyFilters();
  },

  openRecipe(id) {
    this.selectedRecipeId = id;
    const r = this.selectedRecipe;
    this.servings = r?.baseServings ?? 2;
    this.setView("recipe");
  },

  get selectedRecipe() { return this.recipes.find((r) => r.id === this.selectedRecipeId); },

  scaledQty(ing) {
    const r = this.selectedRecipe;
    if (!r) return "";
    const scale = this.servings / r.baseServings;
    return formatQuantity(ing.qty * scale);
  },

  toggleFavorite(id) {
    const i = this.favorites.indexOf(id);
    if (i >= 0) this.favorites.splice(i, 1);
    else this.favorites.push(id);
    this._save("favorites");
  },

  isFavorite(id) { return this.favorites.includes(id); },

  async startCookMode() {
    this.stepIndex = 0;
    this.timer = { remaining: 0, running: false, _interval: null };
    try {
      if ("wakeLock" in navigator) {
        this.wakeLock = await navigator.wakeLock.request("screen");
      }
    } catch { /* unsupported or denied: silently no-op */ }
    this.setView("cook-mode");
  },

  exitCookMode() {
    if (this.timer._interval) clearInterval(this.timer._interval);
    if (this.wakeLock) { this.wakeLock.release().catch(() => {}); this.wakeLock = null; }
    this.setView("recipe");
  },

  nextStep() {
    if (!this.selectedRecipe) return;
    if (this.stepIndex < this.selectedRecipe.steps.length - 1) {
      this.stepIndex++;
      if (this.timer._interval) clearInterval(this.timer._interval);
      this.timer = { remaining: 0, running: false, _interval: null };
    } else {
      this.completeCooking();
    }
  },

  prevStep() {
    if (this.stepIndex > 0) this.stepIndex--;
  },

  startTimer(seconds = 180) {
    if (this.timer._interval) clearInterval(this.timer._interval);
    this.timer.remaining = seconds;
    this.timer.running = true;
    this.timer._interval = setInterval(() => {
      this.timer.remaining--;
      if (this.timer.remaining <= 0) {
        clearInterval(this.timer._interval);
        this.timer.running = false;
        try { this._chime.play().catch(() => {}); } catch {}
        this.toast("Timer done");
      }
    }, 1000);
  },

  timerLabel() {
    if (this.timer.remaining <= 0) return "—";
    const m = Math.floor(this.timer.remaining / 60);
    const s = this.timer.remaining % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  },

  completeCooking() {
    if (this.selectedRecipeId) {
      this.cookingHistory.push({
        recipeId: this.selectedRecipeId,
        completedAt: new Date().toISOString(),
      });
      this._save("cookingHistory");
    }
    if (this.wakeLock) { this.wakeLock.release().catch(() => {}); this.wakeLock = null; }
    this.setView("completed");
  },

  toast(msg) { this.toastMsg = msg; setTimeout(() => { this.toastMsg = ""; }, 2000); },
});
```

- [ ] **Step 4: Write `index.html` views.** Use Fraunces for headings, Inter for body. Palette tokens in CSS:

```css
:root {
  --bg: #faf6f1;
  --text: #1f2937;
  --text-muted: #6b7280;
  --accent: #556b2f;
  --accent-soft: #e8e0d0;
}
body { font-family: "Inter", ui-sans-serif, sans-serif; background: var(--bg); color: var(--text); }
.display { font-family: "Fraunces", Georgia, serif; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}
[x-cloak] { display: none !important; }
```

**View 1 — `catalog`:** filter sidebar (ingredient search, diet pills with `data.js`'s diet values, time-bucket pills `<15 / <30 / <60 / any`, difficulty pills `easy / medium / any`) + recipe grid (hero + title + minutes + difficulty + favorite toggle).

**View 2 — `recipe`:** hero image, title in Fraunces, byline, intro paragraph, **servings slider** (`<input type="range" min="1" max="8" x-model.number="servings">`), ingredient list with `x-text="scaledQty(ing)"`, step preview, "Start Cooking" button, "Save to favorites" toggle.

**View 3 — `cook-mode`:** full-screen single-step view:

```html
<section x-show="view === 'cook-mode'" x-transition.duration.200ms class="fixed inset-0 bg-[var(--bg)] z-40 flex flex-col items-center justify-center px-6 py-12" x-cloak>
  <button @click="exitCookMode()" class="absolute top-4 right-6 text-[var(--text-muted)]">Exit</button>
  <div class="text-sm text-[var(--text-muted)] mb-4" x-text="`Step ${stepIndex + 1} of ${selectedRecipe?.steps.length}`"></div>
  <p class="display text-2xl sm:text-3xl text-center max-w-2xl leading-relaxed" x-text="selectedRecipe?.steps[stepIndex]"></p>

  <!-- Timer -->
  <div class="mt-10 flex gap-3 items-center">
    <button @click="startTimer(180)" class="px-4 py-2 bg-[var(--accent-soft)] rounded text-sm">Start 3:00 timer</button>
    <div class="text-2xl font-mono tabular-nums" x-text="timerLabel()"></div>
  </div>

  <!-- Step nav -->
  <div class="mt-10 flex gap-4">
    <button @click="prevStep()" :disabled="stepIndex === 0"
      :class="stepIndex === 0 ? 'opacity-40 cursor-not-allowed' : ''"
      class="px-5 py-3 border border-[var(--text-muted)] rounded">Previous</button>
    <button @click="nextStep()"
      x-text="stepIndex === selectedRecipe?.steps.length - 1 ? 'Finish' : 'Next step'"
      class="px-5 py-3 bg-[var(--accent)] text-white rounded font-semibold">Next step</button>
  </div>
</section>
```

**View 4 — `completed`:** "Recipe completed!" celebration, rating prompt (1-5 stars), "Save to favorites" if not already, "Back to catalog" button.

- [ ] **Step 5: Smoke test.**

```bash
cd template_apps/recipe-site
python -m http.server 8204
```

Verify:
- Catalog shows 30 recipes
- Click "Vegan" diet pill → list narrows
- Type "lemon" in ingredient search → list narrows further
- Click first recipe → recipe view
- Drag servings slider from 2 to 4 → all ingredient quantities visibly double; "1 cup" becomes "2", "½ tsp" becomes "1", etc.
- Click "Start Cooking" → fullscreen cook mode
- Click "Start 3:00 timer" → countdown ticks
- Click "Next step" → advances; final step's button reads "Finish"
- Click "Finish" → completed view
- Click "Back to catalog" → favorites count increased

- [ ] **Step 6: Write `README.md` + commit.**

```bash
git add mcp-servers/tasks/template_apps/recipe-site/
git commit -m "feat(template): recipe-site with cook mode and serving scale"
```

---

### Task 8: Static structural tests

**Files to create:** `mcp-servers/tasks/tests/test_functional_templates_static.py`

**Goal:** Parametrized over the 5 keys. 9 assertions × 5 = 45 tests. Verify each template's scaffold matches the contract (single h1, has views, has main.js, all img tags have alt + loading + dimensions, no placeholder strings, only whitelisted CDNs, src/data.js exports a non-empty array).

- [ ] **Step 1: Write the test file.**

```python
"""Static structural checks for the 5 functional templates.

Parametrized over each key. Each test verifies a single structural
property — together they enforce the spec's static contract without
opening a browser.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_APPS = ROOT / "template_apps"

FUNCTIONAL_KEYS = [
    "flight-booking",
    "food-delivery",
    "job-board",
    "movie-tickets",
    "recipe-site",
]

WHITELISTED_CDN_DOMAINS = {
    "cdn.tailwindcss.com",
    "unpkg.com",
    "cdn.jsdelivr.net",
    "images.unsplash.com",
    "picsum.photos",
    "api.dicebear.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
}

PLACEHOLDER_PHRASES = ["Lorem ipsum", "TODO", "<%= APP_NAME %>", "Coming soon", "Add content here"]


def _read(key: str, *parts: str) -> str:
    return (TEMPLATE_APPS / key / Path(*parts)).read_text(encoding="utf-8")


def _strip_html(text: str) -> str:
    """Remove tags and Alpine attributes so placeholder checks scan visible text only."""
    no_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", no_tags).strip()


@pytest.fixture(scope="module", params=FUNCTIONAL_KEYS)
def key(request):
    return request.param


def test_index_html_exists_and_substantial(key):
    p = TEMPLATE_APPS / key / "index.html"
    assert p.exists(), f"{key}/index.html missing"
    size = p.stat().st_size
    assert size > 8192, f"{key}/index.html is only {size} bytes (expected > 8KB)"


def test_index_html_has_exactly_one_h1(key):
    html = _read(key, "index.html")
    h1_count = len(re.findall(r"<h1\b", html, flags=re.IGNORECASE))
    assert h1_count == 1, f"{key}/index.html has {h1_count} <h1> tags (expected exactly 1)"


def test_index_html_has_state_machine_markers(key):
    html = _read(key, "index.html")
    assert 'x-data="appState()"' in html, f"{key}: missing x-data=\"appState()\""
    view_count = len(re.findall(r"x-show=\"view === '[a-z\-]+'\"", html))
    assert view_count >= 2, f"{key}: only {view_count} view sections found (expected >= 2)"


def test_index_html_imports_main_js_as_module(key):
    html = _read(key, "index.html")
    assert re.search(r'<script\s+type="module"\s+src="src/main\.js"', html), \
        f"{key}: missing <script type=\"module\" src=\"src/main.js\">"


def test_lib_files_present(key):
    base = TEMPLATE_APPS / key / "src"
    for f in ("main.js", "data.js", "lib/router.js", "lib/persistence.js", "lib/skeleton.js"):
        assert (base / f).exists(), f"{key}/src/{f} missing"


def test_img_tags_have_required_attrs(key):
    html = _read(key, "index.html")
    # Find every <img> tag. Skip the decorative SVG (those aren't <img>).
    img_tags = re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE)
    for tag in img_tags:
        assert re.search(r'\balt="[^"]+"', tag), f"{key}: <img> missing non-empty alt: {tag[:120]}"
        assert re.search(r"\bloading=", tag), f"{key}: <img> missing loading attr: {tag[:120]}"
        # Width/height must be numeric (not "auto" or "100%")
        w = re.search(r'\bwidth="(\d+)"', tag)
        h = re.search(r'\bheight="(\d+)"', tag)
        assert w and h, f"{key}: <img> missing numeric width/height: {tag[:120]}"


def test_no_placeholder_strings_in_visible_text(key):
    html = _read(key, "index.html")
    visible = _strip_html(html)
    for phrase in PLACEHOLDER_PHRASES:
        assert phrase not in visible, f"{key}: placeholder phrase '{phrase}' appears in visible text"


def test_only_whitelisted_cdns(key):
    html = _read(key, "index.html")
    urls = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    for url in urls:
        domain = re.match(r"https?://([^/]+)", url).group(1)
        # Allow exact matches OR subdomains of whitelisted entries
        ok = any(domain == d or domain.endswith("." + d) for d in WHITELISTED_CDN_DOMAINS)
        assert ok, f"{key}: external URL {url} (domain {domain}) not on whitelist"


def test_data_js_exports_nonempty_array(key):
    data = _read(key, "src/data.js")
    # Each template exports at least one named array. We accept the primary entity name
    # OR any `export const X = [...]` / `export const X = (() => {...})()` pattern.
    has_array_export = bool(re.search(r"export\s+const\s+\w+\s*=\s*\[", data)) \
        or bool(re.search(r"export\s+const\s+\w+\s*=\s*\(\(\)\s*=>", data)) \
        or bool(re.search(r"export\s+const\s+\w+\s*=\s*\w+\.map", data))
    assert has_array_export, f"{key}: src/data.js has no `export const X = [...]` style array export"
    # Sanity: file is substantial
    assert len(data) > 2000, f"{key}: src/data.js is only {len(data)} bytes (expected >2KB)"
```

- [ ] **Step 2: Run the test suite.**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_functional_templates_static.py -v
```

Expected output: **45 passed in <1s**. If any fail, the failing template needs the contract fix (e.g., a missing img attr, a forgotten view section). Fix and re-run until green.

- [ ] **Step 3: Commit.**

```bash
git add mcp-servers/tasks/tests/test_functional_templates_static.py
git commit -m "test(templates): static structural checks for 5 functional templates"
```

---

### Task 9: Playwright interaction tests (the "alive" tests)

**Files to create:** `mcp-servers/tasks/tests/test_functional_templates_alive.py`

**Goal:** One end-to-end test per template, exercising the key "alive interaction" from the spec. Local HTTP server (file:// blocks ES modules). Wrapped in `pytest.importorskip("playwright")` so it skips cleanly on machines without Playwright.

- [ ] **Step 1: Write the test file.**

```python
"""Playwright tests asserting each functional template's key "alive" behavior.

Each test spins up a local HTTP server rooted at the template's directory
(file:// URLs block ES module imports), navigates Playwright Chromium to it,
exercises the headline interaction, and asserts the expected post-state.

Skipped automatically if Playwright isn't installed.
"""
import http.server
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright.sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_APPS = ROOT / "template_apps"


def _make_handler(directory: Path):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)
        def log_message(self, *args, **kwargs):
            pass
    return Handler


@contextmanager
def _serve(directory: Path):
    handler_cls = _make_handler(directory)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = http.server.HTTPServer(("127.0.0.1", port), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _new_page(browser, viewport=(1280, 800)):
    ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]})
    page = ctx.new_page()
    return ctx, page


def test_flight_booking_search_and_filter(browser):
    with _serve(TEMPLATE_APPS / "flight-booking") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            # Submit the default search form
            page.locator("button[type='submit']").click()
            # Wait for skeleton -> results
            page.wait_for_selector("article", timeout=5_000)
            initial_count = page.locator("article").count()
            assert initial_count > 0, "no results rendered after search"
            # Drag price filter to a very low value via input.fill
            price_slider = page.locator("input[type='range']").first
            price_slider.evaluate(
                """(el) => { el.value = 500; el.dispatchEvent(new Event('input', { bubbles: true })); }"""
            )
            page.wait_for_timeout(200)
            new_count = page.locator("article").count()
            assert new_count < initial_count, f"filter didn't narrow results: {initial_count} -> {new_count}"
        finally:
            ctx.close()


def test_food_delivery_cart_persistence(browser):
    with _serve(TEMPLATE_APPS / "food-delivery") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            # Open the first restaurant
            page.locator("[data-restaurant-id], .restaurant-card, article").first.click()
            page.wait_for_timeout(1_500)  # simulateNetwork
            # Add 3 items via "+" button
            add_btn = page.locator('button:has-text("+"), button[aria-label*="Add"]').first
            for _ in range(3):
                add_btn.click()
                page.wait_for_timeout(80)
            # Assert badge shows 3
            badge_text = page.locator("[x-text='cartCount'], .cart-count").first.text_content()
            assert "3" in (badge_text or ""), f"cart badge expected '3', got '{badge_text}'"
            # Reload and re-check
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(500)
            badge_text = page.locator("[x-text='cartCount'], .cart-count").first.text_content()
            assert "3" in (badge_text or ""), "cart did not persist across reload"
        finally:
            ctx.close()


def test_job_board_search_debounce_and_bookmark(browser):
    with _serve(TEMPLATE_APPS / "job-board") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            initial = page.locator("article").count()
            search = page.locator("input[type='search'], input[placeholder*='Search']").first
            search.fill("Engineer")
            page.wait_for_timeout(400)  # past 250ms debounce
            filtered = page.locator("article").count()
            assert filtered < initial, f"search didn't filter: {initial} -> {filtered}"
            # Bookmark first job
            bookmark = page.locator("[aria-label*='Save'], button:has-text('Save')").first
            bookmark.click()
            page.wait_for_timeout(150)
            # Reload, assert bookmark count via localStorage
            saved_count = page.evaluate(
                """() => JSON.parse(localStorage.getItem('io-template:job-board:savedJobs') || '[]').length"""
            )
            assert saved_count >= 1, "bookmark did not persist to localStorage"
        finally:
            ctx.close()


def test_movie_tickets_seat_picker(browser):
    with _serve(TEMPLATE_APPS / "movie-tickets") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            # Drive Alpine state to seats view directly (more reliable than click chain)
            page.evaluate(
                """() => {
                    const root = document.querySelector('[x-data]');
                    const state = root._x_dataStack[0];
                    state.openFilm(state.films[0].id);
                    state.pickShowtime(state.showtimes.find(s => s.filmId === state.films[0].id).id);
                }"""
            )
            page.wait_for_timeout(300)
            # Pick 2 non-aisle, non-taken seats
            available_seats = page.locator("button.bg-gray-500").all()[:2]
            assert len(available_seats) == 2, "expected at least 2 available seats"
            for seat in available_seats:
                seat.click()
                page.wait_for_timeout(100)
            # Assert total reflects 2 × $14 = $28
            page.wait_for_timeout(500)  # let count-up finish
            total_el = page.locator("[x-text*='displayedTotal'], .total").first
            total_text = total_el.text_content() or ""
            assert "28" in total_text, f"expected total to include '28', got '{total_text}'"
        finally:
            ctx.close()


def test_recipe_site_serving_scale(browser):
    with _serve(TEMPLATE_APPS / "recipe-site") as base_url:
        ctx, page = _new_page(browser)
        try:
            page.goto(f"{base_url}/index.html", wait_until="networkidle", timeout=15_000)
            # Open first recipe
            page.locator("article").first.click()
            page.wait_for_timeout(300)
            # Grab the first ingredient quantity text
            first_ing = page.locator("[data-ingredient-qty], .ingredient-qty, li").first
            initial_qty_text = (first_ing.text_content() or "").strip()
            # Drag servings slider from 2 to 4
            slider = page.locator("input[type='range']").first
            slider.evaluate(
                """(el) => { el.value = 4; el.dispatchEvent(new Event('input', { bubbles: true })); }"""
            )
            page.wait_for_timeout(300)
            after_qty_text = (first_ing.text_content() or "").strip()
            assert after_qty_text != initial_qty_text, \
                f"servings slider didn't update ingredient text: '{initial_qty_text}' vs '{after_qty_text}'"
        finally:
            ctx.close()
```

- [ ] **Step 2: Run the tests.**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_functional_templates_alive.py -v
```

Expected: **5 passed**. If Playwright isn't installed locally, the suite reports "skipped" — that's acceptable. Install with:

```bash
pip install playwright
python -m playwright install chromium
```

Test failures here often indicate selector drift (e.g., the test expects `.cart-count` but the template uses a different selector). Fix the test OR the template to align — the spec's "key alive interaction" wording is the source of truth.

- [ ] **Step 3: Commit.**

```bash
git add mcp-servers/tasks/tests/test_functional_templates_alive.py
git commit -m "test(templates): playwright alive-interaction tests for 5 functional templates"
```

---

### Task 10: Featured slots, preview capture, deploy

**Files to modify:**
- `mcp-servers/tasks/static/templates.html` (`FEATURED_KEYS` + `PREVIEW_VER`)
- `mcp-servers/tasks/static/projects.html` (`FEATURED_TEMPLATE_KEYS` + `PREVIEW_VER`)
- `_tplpng/capture-local-templates.py` (`TEMPLATES` + `DEMO_NAMES` + per-template driver step)

**Files generated as artifacts (not committed in raw form):**
- `_tplpng/new-flight-booking.png`
- `_tplpng/new-food-delivery.png`
- `_tplpng/new-job-board.png`
- `_tplpng/new-movie-tickets.png`
- `_tplpng/new-recipe-site.png`

(These get copied into the production server's `_tplpng/` dir as `preview.png` per-template via the deploy step.)

- [ ] **Step 1: Extend `_tplpng/capture-local-templates.py`** — add the 5 new keys to `TEMPLATES` and `DEMO_NAMES`, plus a per-template driver function.

```python
# At the top of capture-local-templates.py, extend:
TEMPLATES = [
    "agency", "restaurant", "photography", "event", "real-estate",
    # NEW (2026-05-11):
    "flight-booking", "food-delivery", "job-board", "movie-tickets", "recipe-site",
]

DEMO_NAMES = {
    # ... yesterday's entries ...
    "flight-booking":  "Skylane",
    "food-delivery":   "Roost",
    "job-board":       "Workpath",
    "movie-tickets":   "Lumen Cinemas",
    "recipe-site":     "Salt & Pan",
}

# Per-template driver step before screenshot. Prefer Alpine state mutation
# over click sequences (more stable across markup changes).
DRIVERS = {
    "flight-booking": """() => {
        const s = document.querySelector('[x-data]')._x_dataStack[0];
        s.runSearch();  // sets view to results, runs simulateNetwork
    }""",
    "food-delivery": """() => {
        const s = document.querySelector('[x-data]')._x_dataStack[0];
        s.openMenu(s.restaurants[0].id);
    }""",
    "job-board": None,  # list view is already photogenic
    "movie-tickets": """() => {
        const s = document.querySelector('[x-data]')._x_dataStack[0];
        s.openFilm(s.films[0].id);
        s.pickShowtime(s.showtimes.find(x => x.filmId === s.films[0].id).id);
        // Seed 2 hardcoded seats
        s.selectedSeats = ['3-5', '3-6'];
        s.displayedTotal = 28;
    }""",
    "recipe-site": """() => {
        const s = document.querySelector('[x-data]')._x_dataStack[0];
        s.openRecipe(s.recipes[0].id);
    }""",
}
```

Inside the capture loop (after `page.goto(...)` and the existing `page.wait_for_timeout(2_000)` settle), add a driver-step block:

```python
            # Drive the template to its most photogenic view.
            driver = DRIVERS.get(key)
            if driver:
                try:
                    page.evaluate(driver)
                    page.wait_for_timeout(2_000)  # let simulateNetwork + transitions settle
                except Exception as e:
                    print(f"  warn: driver step failed for {key}: {e}")
```

- [ ] **Step 2: Run the capture script.**

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-functional-templates"
python _tplpng/capture-local-templates.py
```

Expected output:
```
=== flight-booking (Skylane) ===
  loading http://127.0.0.1:<port>/index.html
  saved _tplpng/new-flight-booking.png (NNN,NNN bytes)
=== food-delivery (Roost) ===
  ...
Done. 10 screenshots captured.
```

Open each new PNG and eyeball it — should show the demo brand name, no `<%= APP_NAME %>` literal, the driven view (results / menu / seat-picker / recipe), and look polished.

- [ ] **Step 2a: Copy each PNG into its `template_apps/<key>/preview.png` slot.**

The static asset mount serves `/api/template-preview/<key>/preview.png` from `mcp-servers/tasks/template_apps/<key>/preview.png` (per `main.py`'s `StaticFiles(directory="template_apps", ...)` mount). The `_tplpng/` directory is a build-artifact location only — files there are NOT served. Each preview must live INSIDE the template's own directory.

```bash
cd "C:/Users/alama/Desktop/Lukas Work/IO-functional-templates"
for key in flight-booking food-delivery job-board movie-tickets recipe-site; do
  cp "_tplpng/new-$key.png" "mcp-servers/tasks/template_apps/$key/preview.png"
done
ls mcp-servers/tasks/template_apps/*/preview.png | wc -l   # should print 10 (yesterday's 5 + today's 5)
```

Commit the per-template `preview.png` files:

```bash
git add mcp-servers/tasks/template_apps/flight-booking/preview.png \
        mcp-servers/tasks/template_apps/food-delivery/preview.png \
        mcp-servers/tasks/template_apps/job-board/preview.png \
        mcp-servers/tasks/template_apps/movie-tickets/preview.png \
        mcp-servers/tasks/template_apps/recipe-site/preview.png \
        _tplpng/new-flight-booking.png \
        _tplpng/new-food-delivery.png \
        _tplpng/new-job-board.png \
        _tplpng/new-movie-tickets.png \
        _tplpng/new-recipe-site.png
git commit -m "feat(templates): capture preview PNGs for 5 functional templates"
```

- [ ] **Step 3: Update `mcp-servers/tasks/static/templates.html`** — extend `FEATURED_KEYS`, bump `PREVIEW_VER`.

```html
<!-- Locate the FEATURED_KEYS constant and PREVIEW_VER -->
<script>
  const FEATURED_KEYS = new Set([
    // Original 5
    "landing", "dashboard", "portfolio", "ecommerce", "blog",
    // Yesterday's design templates
    "agency", "restaurant", "photography", "event", "real-estate",
    // Today's functional templates (2026-05-11)
    "flight-booking", "food-delivery", "job-board", "movie-tickets", "recipe-site",
  ]);
  const PREVIEW_VER = "5";   // was "4"
</script>
```

Optionally, add a heading row to visually group the new templates above the original 10:

```html
<!-- Before the rendered card loop, optionally insert a section header -->
<h3 class="text-xs uppercase tracking-wide text-gray-500 mt-8 mb-3">Functional apps</h3>
```

- [ ] **Step 4: Update `mcp-servers/tasks/static/projects.html`** — same change to `FEATURED_TEMPLATE_KEYS` and `PREVIEW_VER`.

- [ ] **Step 5: Commit + push.**

```bash
git add mcp-servers/tasks/static/templates.html mcp-servers/tasks/static/projects.html _tplpng/capture-local-templates.py
git commit -m "feat(catalog): feature 5 functional templates + bump PREVIEW_VER to 5"
```

- [ ] **Step 6: Deploy to Hetzner.** All deploys go via SCP + docker compose, per `CLAUDE.md` and project memory.

Per-file copies (NOT `scp -r` — it silently skips files):

```bash
# Run from the worktree root.
cd "C:/Users/alama/Desktop/Lukas Work/IO-functional-templates"

# Catalog + tests
scp mcp-servers/tasks/templates.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/templates.py
scp mcp-servers/tasks/tests/test_templates.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/tests/test_templates.py
scp mcp-servers/tasks/tests/test_functional_templates_static.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/tests/test_functional_templates_static.py
scp mcp-servers/tasks/tests/test_functional_templates_alive.py root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/tests/test_functional_templates_alive.py

# Static UI
scp mcp-servers/tasks/static/templates.html root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/templates.html
scp mcp-servers/tasks/static/projects.html root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/static/projects.html

# Per-template scaffolds
for key in flight-booking food-delivery job-board movie-tickets recipe-site; do
  ssh root@46.224.193.25 "mkdir -p /root/proxy-server/mcp-servers/tasks/template_apps/$key/{styles,src/lib,public}"
  scp mcp-servers/tasks/template_apps/$key/index.html       root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/index.html
  scp mcp-servers/tasks/template_apps/$key/styles/main.css  root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/styles/main.css
  scp mcp-servers/tasks/template_apps/$key/src/main.js      root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/src/main.js
  scp mcp-servers/tasks/template_apps/$key/src/data.js      root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/src/data.js
  scp mcp-servers/tasks/template_apps/$key/src/lib/router.js      root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/src/lib/router.js
  scp mcp-servers/tasks/template_apps/$key/src/lib/persistence.js root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/src/lib/persistence.js
  scp mcp-servers/tasks/template_apps/$key/src/lib/skeleton.js    root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/src/lib/skeleton.js
  scp mcp-servers/tasks/template_apps/$key/README.md        root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/README.md
  ssh root@46.224.193.25 "touch /root/proxy-server/mcp-servers/tasks/template_apps/$key/public/.gitkeep"
done
# movie-tickets and recipe-site also have src/lib/countUp.js (food-delivery does NOT):
for key in movie-tickets recipe-site; do
  scp mcp-servers/tasks/template_apps/$key/src/lib/countUp.js root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/src/lib/countUp.js
done

# Preview PNGs — copied to BOTH the per-template path (which the StaticFiles mount serves)
# and the _tplpng/ artifact path (kept for capture-script self-consistency).
for key in flight-booking food-delivery job-board movie-tickets recipe-site; do
  scp mcp-servers/tasks/template_apps/$key/preview.png \
      root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/$key/preview.png
  scp _tplpng/new-$key.png \
      root@46.224.193.25:/root/proxy-server/_tplpng/new-$key.png
done

# Rebuild only the tasks container. `up -d --build <service>` reuses the cache where safe;
# if a stale layer ever bites us, run `docker compose build --no-cache tasks` first as
# a separate step, then `up -d tasks`. (The `--no-cache` flag is NOT valid on `up`.)
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks"
```

- [ ] **Step 7: Verify the deploy.**

```bash
# Catalog count
curl -s https://ai-ui.coolestdomain.win/api/templates | jq 'length'
# Expected: 29

# Each new key returns a 200 preview
for key in flight-booking food-delivery job-board movie-tickets recipe-site; do
  echo -n "$key: "
  curl -s -o /dev/null -w "%{http_code}  %{size_download} bytes\n" \
    "https://ai-ui.coolestdomain.win/api/template-preview/$key/preview.png?v=5"
done
# Expected: all 200 with non-trivial byte counts (>50KB each)

# PREVIEW_VER bumped
curl -s https://ai-ui.coolestdomain.win/templates.html | grep -o 'PREVIEW_VER = "[0-9]"'
# Expected: PREVIEW_VER = "5"
```

Then in a browser, hard-refresh `https://ai-ui.coolestdomain.win/templates.html` and:
- Confirm 15 featured cards render
- Check the 5 new cards show preview PNGs (not the SVG fallback)
- Click a card (e.g., flight-booking) → verify it opens the App Builder with the right rules text

- [ ] **Step 8: Final commit + summary.**

```bash
git log --oneline feat/design-templates..HEAD
# Should show ~10 commits — one per task
```

Push the branch when ready:
```bash
git push -u origin feat/functional-templates
```

---

## End of plan

After all 10 tasks: 5 new functional templates live in production, gallery shows 15 featured cards in two clusters (Functional apps + Design showcases), `PREVIEW_VER=5`, 45 static tests + 5 Playwright tests green, branch ready for PR after `feat/design-templates` lands.






