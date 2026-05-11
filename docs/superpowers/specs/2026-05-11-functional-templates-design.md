# Spec — Functional Templates for the IO App Builder

**Date:** 2026-05-11
**Status:** Draft — awaiting spec review
**Related branches:** `feat/element-picker` → `feat/design-templates` → `feat/functional-templates` (this spec)
**Author:** brainstormed with Lukas via the superpowers/brainstorming flow

---

## 1. Goal

Upgrade the IO App Builder's template catalog from "pretty static showcases" into templates that are **alive and purposeful** — they feel like real, working apps with interactive search/filter/results/cart/checkout flows, even though they remain pure static HTML+CSS+JS.

Yesterday's 5 design-forward templates (`agency`, `restaurant`, `photography`, `event`, `real-estate`) demonstrated that templates can look polished. This spec adds 5 templates that demonstrate templates can **do something** — the user can click through a real flow end-to-end, and state actually persists.

The user's framing:

> *"i want everything on templates website are all functional and alive not just a template but it has purpose something like that example flight website … its still static but its an upgrade version of it it has purpose"*

---

## 2. Scope

### In scope

- 5 new templates, registered with new keys: `flight-booking`, `food-delivery`, `job-board`, `movie-tickets`, `recipe-site`
- Each template is fully scaffolded under `mcp-servers/tasks/template_apps/<key>/`
- Each template follows the **single-page state machine** pattern (one `index.html`, multiple Alpine `x-show` views)
- Each template is **real-tier**: filters actually filter, cart actually holds items, selections actually persist to `localStorage`
- Each template's preview screenshot captured at 1280×800 and registered in the gallery
- Static structural tests (45 total — 9 assertions × 5 templates) and Playwright "alive interaction" tests (5 total)
- Catalog updates: new entries in `templates.py`, new featured slots in `templates.html` + `projects.html`, `PREVIEW_VER` bump

### Out of scope

- No new dependencies beyond the existing `_BASE_RULES` baseline (Tailwind CDN, Alpine.js 3.x, vanilla ES modules)
- No backend / Supabase / Postgres / auth integration — all templates have `storage="none"`
- No build step or bundler — `<script type="module">` directly
- No replacement of the existing rules-only `booking` or `ecommerce` keys — both stay alongside the new scaffolded ones (catalog grows from 24 to 29 entries)
- No edits to yesterday's 5 design-forward templates
- No edits to `task-panel.js` unless required for cache busting

---

## 3. Architecture — single-page state machine

### File layout per template

```
mcp-servers/tasks/template_apps/<key>/
├── index.html
├── styles/
│   └── main.css
├── src/
│   ├── main.js                  ← Alpine root: window.appState()
│   ├── data.js                  ← ES module exporting demo data array(s)
│   └── lib/
│       ├── router.js            ← createRouter() factory — copied verbatim across all 5 templates
│       ├── persistence.js       ← createPersistence() factory — copied verbatim
│       └── skeleton.js          ← simulateNetwork() helper — copied verbatim
├── public/
│   └── .gitkeep                 ← image directory; mostly hot-linked from Unsplash
├── README.md
└── preview.png                  ← 1280×800 captured by _tplpng/capture-local-templates.py
```

**Self-contained per template.** The three `lib/` primitives are deliberately duplicated across all 5 templates — no `template_apps/_shared/` directory — so the publish pipeline can continue to copy a single `template_apps/<key>/*` tree without cross-directory awareness. Yesterday's code reviewer validated this pattern; we're applying it again here.

### State machine shape

```html
<!doctype html>
<html lang="en">
  <head>… Tailwind CDN, Alpine, fonts …</head>
  <body x-data="appState()" x-init="init()">
    <header class="compact-app-header">…</header>

    <section x-show="view === 'search'"  x-transition.duration.200ms>…</section>
    <section x-show="view === 'results'" x-transition.duration.200ms>…</section>
    <section x-show="view === 'detail'"  x-transition.duration.200ms>
      <button @click="back()">← Back</button>
      …
    </section>

    <script type="module" src="src/main.js"></script>
  </body>
</html>
```

```js
// src/main.js
import { createRouter }      from './lib/router.js';
import { createPersistence } from './lib/persistence.js';
import { simulateNetwork }   from './lib/skeleton.js';
import { flights }           from './data.js';

window.appState = () => ({
  ...createRouter({ initial: 'search', views: ['search', 'results', 'detail', 'review'] }),
  ...createPersistence({ namespace: 'flight-booking', keys: ['savedTrips'] }),

  flights,
  filteredFlights: flights,
  isLoading: false,
  filters: { maxPrice: 2000, stops: 'any', timeOfDay: 'any', airlines: [] },

  init() {
    this._hydrate();              // pull savedTrips from localStorage
    this.applyFilters();          // initial render
  },

  async runSearch() {
    this.isLoading = true;
    await simulateNetwork();      // 800–1400ms randomized delay
    this.applyFilters();
    this.isLoading = false;
    this.setView('results');
  },

  applyFilters() {
    this.filteredFlights = this.flights.filter(f =>
      f.price <= this.filters.maxPrice &&
      (this.filters.stops === 'any' || (this.filters.stops === '0' ? f.stops === 0 : f.stops >= 1)) &&
      (this.filters.timeOfDay === 'any' || f.departureBucket === this.filters.timeOfDay) &&
      (this.filters.airlines.length === 0 || this.filters.airlines.includes(f.airline))
    );
  },

  saveTrip(flightId) {
    const trip = this.flights.find(f => f.id === flightId);
    if (trip && !this.savedTrips.find(t => t.id === flightId)) {
      this.savedTrips.push(trip);
      this._save('savedTrips');
      this.toast('Trip saved');
    }
  },

  toast(msg) {
    this.toastMsg = msg;
    setTimeout(() => { this.toastMsg = ''; }, 2000);
  },

  toastMsg: '',
});
```

### Primitive 1 — `src/lib/router.js`

```js
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

### Primitive 2 — `src/lib/persistence.js`

```js
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

**Namespace rule:** every template uses its own namespace string (`flight-booking`, `food-delivery`, etc.) so a single browser holding multiple deployed apps from this builder doesn't cross-pollinate state.

### Primitive 3 — `src/lib/skeleton.js`

```js
export async function simulateNetwork(minMs = 800, maxMs = 1400) {
  const ms = minMs + Math.random() * (maxMs - minMs);
  await new Promise((r) => setTimeout(r, ms));
}
```

This delay is **not decorative**. It gates the data swap so skeleton placeholders have time to render and animate. If the delay is removed, the data flashes through instantly and there's no perceived "loading" state.

### View transitions

Alpine's built-in `x-transition.duration.200ms` with a default opacity-fade + small translate-y. No JS-driven transitions, no GSAP, no framer-motion.

For users with `prefers-reduced-motion: reduce`:
- View changes become instant (opacity goes from 0 → 1 in one tick)
- Count-ups jump straight to final value
- Skeleton pulse becomes static gray
- Card hover lift removed

### Compact app header pattern (shared shape across all 5 templates)

- **Height:** ~56 px (shrinks to 48 px after scrolling 32 px via one `IntersectionObserver`)
- **Left:** 24×24 logo + brand wordmark (per-template demo brand from §6)
- **Center:** contextual breadcrumb or condensed search pill (e.g., flight-booking shows `JFK → LHR · Oct 12–19`)
- **Right:** profile chip (initial-circle, opens stub menu with "Saved", "History"); **no real auth screen**
- **Sticky** to top of viewport, `background-color` from per-template palette, soft shadow when scrolled

---

## 4. Per-template scope

### 4.1 `flight-booking` — Skyscanner-lite

- **Demo brand:** Skylane
- **Views:** `search → results → detail → review`
- **Data:** ~30 flights across 8 routes (JFK↔LHR, SFO↔NRT, LAX↔CDG, ATL↔FCO, ORD↔FRA, DXB↔SYD, GRU↔LIS, ICN↔SIN)
- **Search-view inputs:** origin (datalist autocomplete from 8 cities), destination (same), depart date, return date, passengers, cabin class
- **Results-view filters:** price range slider, stops (`any | 0 | 1+`), departure time-of-day (`any | early | morning | afternoon | evening`), airlines (multi-select pills), duration slider
- **Detail-view content:** full flight info, baggage allowance, seat-map preview (decorative SVG), "Save trip" button, "Continue to review"
- **Review view:** passenger names (form), payment summary (no submission, fake "Confirm" → back to search with a toast)
- **Persistence:** `savedTrips[]` — array of full flight objects
- **Key alive interaction:** filters update `filteredFlights` live as sliders move; "Search" button triggers `simulateNetwork()` + skeleton flash
- **Animation budget:** view transitions, slider thumb shadow on drag, card hover lift, count-up on total price

### 4.2 `food-delivery` — DoorDash-lite

- **Demo brand:** Roost
- **Views:** `restaurants → menu → cart → checkout → confirmation`
- **Data:** ~14 restaurants, ~12 menu items each (~170 items total)
- **Restaurants-view filters:** cuisine pills (Pizza/Sushi/Burger/Asian/Mexican/Vegan/Indian/Thai), min rating, max delivery time
- **Menu-view shape:** restaurant hero banner, cuisine description, items grid (4 cols on desktop, 1 col on mobile), each item with image, name, price, +/− qty stepper
- **Cart-view content:** line items grouped by restaurant, subtotal, $3.99 delivery fee, 8% tax, total, "Place order" button
- **Checkout-view content:** delivery address form (street/city/zip), payment placeholder (last-4 card input — visual only), "Confirm order"
- **Confirmation view:** "Your order is on the way" with fake ETA, mock map placeholder
- **Persistence:** `cart` object `{ restaurantId, items: [{ itemId, qty }] }`
- **Key alive interaction:** +/− stepper updates cart in real time; cart badge in header counts items; checkout flow advances views; reload preserves cart
- **Animation budget:** cart badge count-up, view transitions, item hover lift, +/− button micro-bounce on click

### 4.3 `job-board` — Indeed / Wellfound-lite

- **Demo brand:** Workpath
- **Views:** `list → detail → apply → submitted`
- **Data:** ~60 jobs across ~12 companies, mix of role families (eng, design, PM, marketing, data) and seniorities
- **List-view filters:**
  - Search bar (debounced 250ms, matches title + company name)
  - Remote mode (`remote | hybrid | onsite | any`)
  - Salary range slider (`$60k – $300k`)
  - Role family multi-select pills
  - Seniority (`junior | mid | senior | staff+`)
- **List-view cards:** company logo (DiceBear `initials`), title, location, salary range, posted date (relative format: "2 days ago"), bookmark toggle
- **Detail view:** full job description (long markdown-rendered text), company info card, similar roles, "Save" + "Apply" buttons
- **Apply form:** name, email, resume "upload" (only shows filename — no real upload), cover letter textarea, required-field validation
- **Submitted view:** "Application sent" + fake tracking ID
- **Persistence:** `savedJobs[]` (array of job IDs)
- **Key alive interaction:** debounced search filters list as user types; save toggle persists; apply form validates before submission
- **Animation budget:** view transitions, bookmark icon swap, list-card hover lift, "Sent" confirmation slide-up

### 4.4 `movie-tickets` — Fandango-lite

- **Demo brand:** Lumen Cinemas
- **Views:** `now-showing → film → showtime → seats → checkout → tickets`
- **Data:** ~12 films, 3 theaters, ~5 showtimes per film per theater
- **Now-showing grid:** film posters (~3:4 aspect), rating, genre tags, duration
- **Film-detail view:** synopsis, trailer-thumbnail placeholder, theater dropdown, showtime grid
- **Seat-picker view:** **the highlight interaction**
  - 10 rows × 14 seats per theater
  - Seat classes: `available`, `taken` (~30% randomly per showtime), `selected`, `aisle` (cols 5 + 10)
  - Clicking an available seat toggles `selected`; clicking a `taken` seat does nothing
  - Running total animates count-up as seats are added/removed ($14 per seat)
  - Max 8 seats per booking (button disables beyond that)
- **Checkout view:** ticket summary (seats + showtime), fake "Pay $X" button
- **Tickets view:** QR-code placeholder + booking confirmation, "Save to history"
- **Persistence:** `bookedShowings[]` (history of "purchased" tickets)
- **Animation budget:** seat-toggle micro-pop, running total count-up, view transitions, poster hover scale 1.02

### 4.5 `recipe-site` — NYT Cooking / Yummly-lite

- **Demo brand:** Salt & Pan
- **Views:** `catalog → recipe → cook-mode → completed`
- **Data:** ~30 recipes, ~8 steps each, full ingredient lists with quantities and units
- **Catalog filters:** ingredient search (matches against ingredient names), diet tags (vegan/vegetarian/gluten-free/dairy-free), time-to-cook (`<15min | <30min | <60min | any`), difficulty
- **Recipe-detail view:** hero image, name, byline, intro paragraph, ingredient list with **serving-size slider** (default 2, range 1–8), step preview, "Start Cooking" button, "Save to favorites" toggle
- **Cook-mode view:** fullscreen single-step view with large step text ("Step 3 of 8"), big "Next step" button, optional inline timer (3:00 countdown), `wakeLock.request('screen')` attempted (gracefully no-op if unsupported), "Exit cook mode" button
- **Completed view:** "Recipe completed" celebration, rating prompt, save to favorites if not already
- **Persistence:** `favorites[]` (recipe IDs), `cookingHistory[]` (recipe ID + completion date)
- **Key alive interactions:**
  - Serving-size slider recalculates **all** ingredient quantities in real time (2 servings → 4 → ingredients double; fractions properly displayed: "½ cup" not "0.5 cup")
  - Cook-mode timer counts down, plays audible chime at zero, advances to next step
  - Wakelock attempt prevents screen sleep during cooking
- **Animation budget:** view transitions, ingredient quantity count-up on serving change, step transitions in cook mode

---

## 5. Visual differentiation

Each template has its own palette + typography pair so the gallery grid shows visual variety.

| Template | Primary | Accent | Font (display) | Font (body) |
|---|---|---|---|---|
| `flight-booking` | `#0a1f3d` navy | `#ff6b5b` coral | Inter | Inter |
| `food-delivery` | `#fff8ec` cream | `#ff8c42` orange | Inter | DM Sans |
| `job-board` | `#ffffff` white | `#2563eb` blue | Inter | Inter |
| `movie-tickets` | `#0a0a0a` black | `#f59e0b` amber | Inter | Inter |
| `recipe-site` | `#faf6f1` warm white | `#556b2f` olive | Fraunces | Inter |

Fonts loaded from `fonts.googleapis.com` via `<link>` tags (no JS font loaders). All palettes pass WCAG AA contrast for body text.

---

## 6. Animation primitives — allow / deny list

### Allowed

| Primitive | Where | Implementation |
|---|---|---|
| `x-transition.duration.200ms` opacity + 4px translate-y | every view change | Alpine built-in |
| Skeleton pulse | `x-if="isLoading"` blocks | Tailwind `animate-pulse` |
| Card hover lift (2px y + soft shadow) | result/restaurant/job/film cards | CSS `transition` 150ms |
| Count-up on numeric values | seat-picker total, cart total, ingredient quantities on serving change | factory copied from yesterday's `countUp.js` |
| Live slider value display | range inputs feed `applyFilters()` | optional 80ms debounce on heavy filter sets |
| Toast/snackbar | "Saved", "Added to cart", "Application sent" | 2-second auto-dismiss, fade-up from bottom |
| Sticky header micro-shrink | header collapses from 56px to 48px after scrolling 32px | one `IntersectionObserver` |
| Seat-pick micro-pop | seat scale 1.0 → 1.1 → 1.0 over 150ms when toggled | CSS only |

### Deny list (deliberately not used)

- ❌ No parallax — wrong for app-feel
- ❌ No full-page scroll-reveal sections — apps don't unfold
- ❌ No marquee or text scrollers
- ❌ No mouse-follow cursor effects
- ❌ No giant hero reveals or video backgrounds
- ❌ No GSAP / framer-motion / heavy animation libs

### `prefers-reduced-motion: reduce` handling

Every animation primitive checks this media query. The contract: a user with reduced motion gets a **functionally identical** experience with no animations.

```js
// Example usage in countUp factory
if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  element.textContent = endValue;     // jump straight to final
  return;
}
// … otherwise rAF tween …
```

---

## 7. Data conventions

- Each template has a single `src/data.js` that exports the primary entity array(s):
  ```js
  // template_apps/flight-booking/src/data.js
  export const flights = [
    { id: 'f-001', origin: 'JFK', destination: 'LHR', price: 642, stops: 0, duration: 420, departureBucket: 'morning', airline: 'Skylane', /* … */ },
    /* … */
  ];
  export const airlines = ['Skylane', 'Northwind', 'Aegis Air', /* … */];
  ```
- Every entry has a stable `id` (no `Math.random()` at module load — breaks snapshot tests)
- Prices, dates, ratings are realistic and pre-sorted by something sensible (price ascending for flights, posted-date descending for jobs)
- Dates are absolute ISO strings (`'2026-10-12'`), not `Date.now()` offsets
- Demo content is **plausible but obviously fictional** — restaurant names like "Bistro Pendulum", company names like "Northwind Logistics" — to avoid trademark issues

---

## 8. Image conventions

| Template | Primary source | Backup |
|---|---|---|
| `flight-booking` | Unsplash destination shots (city skylines) | DiceBear text-based airline logos |
| `food-delivery` | Unsplash food photography with stable photo IDs | — |
| `job-board` | DiceBear `initials` API for company logos | — |
| `movie-tickets` | Unsplash film/cinema stills | Custom SVG poster placeholders for 12 films |
| `recipe-site` | Unsplash food photography | — |

**Image URL format (Unsplash):**
```
https://images.unsplash.com/photo-<stable-id>?w=800&q=80&auto=format
```
No `?random=N` queries. No CDN proxies. Photo IDs validated against Unsplash before merge.

**All `<img>` tags must have:**
- non-empty `alt`
- `loading="lazy"` (except hero/LCP image which uses `loading="eager" fetchpriority="high"`)
- numeric `width` and `height` attributes to prevent CLS
- `decoding="async"`

---

## 9. Catalog registration

### 9.1 `_RULES_<KEY>` text blocks

Inserted at the top of `mcp-servers/tasks/templates.py`, one per new key. Each describes the design intent for the LLM (used when a user customizes the template via the AI bubble in the editor).

```python
_RULES_FLIGHT_BOOKING = """- Single-page state machine with views: search, results, detail, review
- Filters update results client-side via .filter() — never fake animation
- 800–1400ms simulateNetwork() before each result swap so skeletons get airtime
- Save trips to localStorage under namespace 'flight-booking'
- Compact app header (sticky, ~56px, logo + condensed search pill + profile chip)
- Honor prefers-reduced-motion in every transition and animation
- Navy + coral palette; Inter typography
- No parallax, no scroll-reveal, no big hero — this is an app, not a landing page"""
```

Same shape for `_RULES_FOOD_DELIVERY`, `_RULES_JOB_BOARD`, `_RULES_MOVIE_TICKETS`, `_RULES_RECIPE_SITE`.

### 9.2 `_SVG_<KEY>` mockup blocks

One per key. Minimal monochrome SVG used as the gallery card fallback when the preview PNG hasn't been generated yet. ~10 lines of `<svg>` markup per template.

### 9.3 Per-template metadata for the `Template(...)` dataclass

The existing `Template` dataclass in `mcp-servers/tasks/templates.py` has these fields (verified against the live file):

```python
@dataclass(frozen=True)
class Template:
    key: str
    label: str
    emoji: str
    description: str
    placeholder: str
    rules: str
    storage: str = "none"
    role_tag: str = ""
    feature_bullets: tuple[str, ...] = ()
    svg_mockup: str = ""
```

**No `category` field exists.** Use `role_tag` (existing field) to give each functional template a short banner tag.

**Emoji field — the tension with the no-emoji UI preference:** The user has a recorded "no emoji in UI" preference (`feedback_no_emoji.md`). However, the existing `test_each_template_has_required_metadata` test (in `tests/test_templates.py` on the `feat/design-templates` branch — line 75: `assert t.emoji, f"{t.key} missing emoji"`) requires every template's `emoji` field to be a truthy string. Yesterday's 5 design templates resolved this by using real emoji (🪐, 🍽️, etc.) and the user accepted that registration — so the established convention on the branch we're stacking from is "emoji field has a thematic glyph; the UI render layer can choose whether to display it." This spec follows that convention rather than expanding scope to amend the test. If the user later wants emoji stripped from the catalog display, that's a separate UI fix in `templates.html` / `projects.html`.

| Key | `label` | `emoji` | `placeholder` | `role_tag` |
|---|---|---|---|---|
| `flight-booking` | "Flight Booking" | "✈️" | "Search flights, filter by price/stops/time, save trips." | "Search + booking" |
| `food-delivery` | "Food Delivery" | "🍔" | "Browse restaurants, add items to a real cart, fake-checkout." | "Marketplace + cart" |
| `job-board` | "Job Board" | "💼" | "Search and filter jobs, save bookmarks, apply with a form." | "Search + apply" |
| `movie-tickets` | "Movie Tickets" | "🎬" | "Pick a film, choose seats from a live grid, fake-checkout." | "Seat picker + checkout" |
| `recipe-site` | "Recipe Site" | "🥘" | "Browse recipes, scale servings live, cook step-by-step." | "Browse + cook mode" |

### 9.4 Example `Template(...)` registration

```python
TEMPLATES = (
    # … existing utility/app entries (landing, dashboard, …) …

    Template(
        key="flight-booking",
        label="Flight Booking",
        emoji="✈️",
        description="Search flights, filter by price/stops/time, review and save trips.",
        placeholder="Search flights, filter by price/stops/time, save trips.",
        rules=_BASE_RULES + _RULES_FLIGHT_BOOKING,
        storage="none",
        role_tag="Search + booking",
        feature_bullets=(
            "Live filter sliders (price, stops, time of day)",
            "Skeleton loaders during search",
            "Saved trips persist across reloads",
        ),
        svg_mockup=_SVG_FLIGHT_BOOKING,
    ),
    Template(key="food-delivery",  …),   # see metadata table above for label/role_tag/placeholder
    Template(key="job-board",      …),
    Template(key="movie-tickets",  …),
    Template(key="recipe-site",    …),

    # then yesterday's design templates (assuming feat/design-templates has merged) …
    Template(key="agency",      …),
    Template(key="restaurant",  …),
    Template(key="photography", …),
    Template(key="event",       …),
    Template(key="real-estate", …),

    Template(key="custom",      …),   # synthetic, always last
)
```

Order in the tuple: functional templates appear **before** the design showcase templates, after the existing app/utility templates. The catalog gallery renders in the order of `TEMPLATES`.

### 9.5 Catalog test updates (`tests/test_templates.py`)

Catalog count math is **conditional on §12's branch stacking**:

- Current `main` / `feat/element-picker` baseline: **19** templates (`test_19_templates_present`)
- After `feat/design-templates` merges: **24** templates (yesterday's spec adds 5 + renames the test to `test_24_templates_present`)
- After `feat/functional-templates` merges (this spec): **29** templates

This spec's test updates assume yesterday's design-templates work has landed (because §12 branches this work from `feat/design-templates`). So:

- Bump `EXPECTED_KEYS` to add the 5 new keys (catalog 24 → 29)
- Rename `test_24_templates_present` → `test_29_templates_present` with `len(TEMPLATES) == 29`
- No new "categories" test exists in the current codebase — none to update. `role_tag` is a free-text string, not an enum.

**If `feat/design-templates` lands AFTER this work** (unlikely given the branching strategy), the plan executor must rebase, resolve the catalog count + `EXPECTED_KEYS` collision, and continue. Same `test_NN_templates_present` rename pattern applies.

---

## 10. Featured slots (templates.html + projects.html)

Both files maintain a `FEATURED_KEYS` / `FEATURED_TEMPLATE_KEYS` constant currently containing 10 keys (5 originals + 5 yesterday's design templates). Add the 5 new keys → 15 featured.

The gallery layout in `templates.html` renders featured cards in a responsive grid. A visual sub-grouping (a small heading row above each cluster) separates "Design showcases" and "Functional apps" — both clusters use the same card shape, the heading row is purely organizational.

`PREVIEW_VER` increments by 1 from whatever value lands on `main` after `feat/design-templates` merges. Yesterday's spec bumped it to `"4"`, so this spec assumes the value at branch base is `"4"` and bumps to `"5"`. If `feat/design-templates` has not merged yet, this branch stacks on it via §12 and inherits `"4"` directly — same bump path.

---

## 11. Preview screenshot capture

Extend yesterday's `_tplpng/capture-local-templates.py` (the Python+Playwright capture script created on `feat/design-templates`; **this script is inherited via §12's branch stacking** — it is not present on `main` or `feat/element-picker` at branch base):

```python
TEMPLATES = [
    # existing showcase templates …
    "agency", "restaurant", "photography", "event", "real-estate",
    # new functional templates …
    "flight-booking", "food-delivery", "job-board", "movie-tickets", "recipe-site",
]

DEMO_NAMES = {
    # … yesterday's entries …
    "flight-booking":  "Skylane",
    "food-delivery":   "Roost",
    "job-board":       "Workpath",
    "movie-tickets":   "Lumen Cinemas",
    "recipe-site":     "Salt & Pan",
}
```

Each new template gets an additional **pre-screenshot driver step** so the capture lands on the most photogenic view (not the empty search form). Per-template:

| Template | Driver step before screenshot |
|---|---|
| `flight-booking` | Click "Search" with default values → land on results view with skeleton-then-data |
| `food-delivery` | Click first restaurant → land on menu view with items grid |
| `job-board` | Pass — list view is already photogenic |
| `movie-tickets` | Drive Alpine state directly via `page.evaluate("Alpine.evaluate(document.body, ...)")` to set view to `seats` AND seed `selectedSeats` with 2 hardcoded seat IDs — avoids fragile multi-click sequences that break if the seat grid layout changes |
| `recipe-site` | Click first recipe → land on recipe detail view with hero image + ingredients |

**Driver step convention:** prefer `page.evaluate(...)` Alpine state mutation (e.g., `Alpine.evaluate(document.body, 'setView("results"); runSearch()')`) over `page.click(...)` selector sequences. State mutation is stable across markup changes; click sequences break the moment a button moves. Use clicks only when the interaction must exercise event handlers (e.g., triggering a `runSearch()` side effect that isn't directly callable).

PNGs land at `_tplpng/new-<key>.png` (1280×800 each).

---

## 12. Branch / worktree strategy

- **Worktree location:** `C:\Users\alama\Desktop\Lukas Work\IO-functional-templates\`
- **Branch:** `feat/functional-templates`
- **Branched from:** `feat/design-templates` (so we inherit yesterday's capture script, `PREVIEW_VER` plumbing, `_BASE_RULES`, and yesterday's 5 templates without merge conflicts)
- **Merge order (eventual):**
  1. `feat/element-picker` → `main`
  2. `feat/design-templates` → `main`
  3. `feat/functional-templates` → `main`

If `feat/design-templates` lands in `main` before this branch is ready, this branch rebases cleanly onto `main`. If it doesn't, the branches stay stacked.

**Where the spec/plan docs live:** This spec and the plan doc that `writing-plans` will produce are committed on `feat/element-picker` (the current `IO/` working tree's branch). They are **not** automatically inherited by the implementation worktree at `IO-functional-templates/` because that worktree branches from `feat/design-templates` (which was created before today's commits). The implementer reads these docs from the `IO/` checkout's filesystem path while writing code in the worktree's path — both directories live side-by-side on disk. No copy/cherry-pick is needed; the docs are reference-only during implementation.

---

## 13. Testing approach

### 13.1 Layer 1 — Static structural tests

File: `mcp-servers/tasks/tests/test_functional_templates_static.py`

Parametrized over `["flight-booking", "food-delivery", "job-board", "movie-tickets", "recipe-site"]`.

Per-template assertions (9 tests × 5 keys = **45 total**):

1. `template_apps/<key>/index.html` exists and is > 8 KB
2. Has exactly one `<h1>` element
3. Contains `x-data="appState()"` and ≥ 2 `x-show="view === '...'"` sections
4. Contains `<script type="module" src="src/main.js">`
5. `src/main.js`, `src/data.js`, `src/lib/router.js`, `src/lib/persistence.js`, `src/lib/skeleton.js` all exist
6. All `<img>` tags have non-empty `alt`, `loading` attribute, numeric `width`/`height`, `decoding="async"`
7. No placeholder strings in visible HTML text (Lorem, TODO, `<%= APP_NAME %>` — checked after stripping `<…>` tags)
8. Only whitelisted CDN domains in `<script src>`/`<link href>` (`cdn.tailwindcss.com`, `unpkg.com/alpinejs`, `images.unsplash.com`, `api.dicebear.com`, `fonts.googleapis.com`, `fonts.gstatic.com`)
9. `src/data.js` exports a non-empty array for the primary entity (verified by static parse / regex)

Runtime target: < 1 second for the full 45-test suite.

### 13.2 Layer 2 — Playwright interaction tests

File: `mcp-servers/tasks/tests/test_functional_templates_alive.py`

Wrapped in `pytest.importorskip("playwright")` so the suite passes on machines without Playwright. Reuses yesterday's `http.server.SimpleHTTPRequestHandler` local-server pattern (`file://` blocks ES modules).

One end-to-end test per template:

| Template | Asserted "alive" behavior |
|---|---|
| `flight-booking` | Type origin "JFK" + destination "LHR" → click Search → wait for skeleton → result count > 0 → drag price slider lower → result count decreases |
| `food-delivery` | Open menu of first restaurant → click + on first item 3 times → cart count badge reads "3" → reload page → cart count still "3" |
| `job-board` | Type "Engineer" in search → result list filters in < 500ms → click bookmark on first job → bookmark icon turns filled → reload → bookmark still filled |
| `movie-tickets` | Pick film → pick showtime → click 2 available seats → seat color changes → running total displays "$28" |
| `recipe-site` | Open a recipe → read first ingredient quantity → drag servings slider from 2 → 4 → first ingredient quantity doubles |

### 13.3 Acceptance bar

Before declaring "done":

- All 45 static tests green
- All 5 Playwright tests green (locally — CI optional)
- Manual smoke from `capture-local-templates.py`'s local server: each template loads, key flow clickable
- Each template's preview screenshot captured at 1280×800
- `curl /api/templates | jq 'length'` returns `29`
- `curl -I /api/template-preview/<key>/preview.png?v=5` returns 200 for all 5 new keys
- Gallery renders 15 featured cards visibly in two groups (functional apps + design showcases)

---

## 14. Deployment plan

Identical pattern to yesterday's deploy:

1. SCP each new file individually to `/root/proxy-server/`:
   - `mcp-servers/tasks/templates.py`
   - `mcp-servers/tasks/static/templates.html`
   - `mcp-servers/tasks/static/projects.html`
   - All files under each new `mcp-servers/tasks/template_apps/<key>/`
   - All 5 preview PNGs to `/root/proxy-server/_tplpng/`
2. On the server: `cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build tasks`
3. Wait for container healthy
4. Verify:
   - `curl https://ai-ui.coolestdomain.win/api/templates | jq 'length'` → 29
   - `curl -I https://ai-ui.coolestdomain.win/api/template-preview/flight-booking/preview.png?v=5` → 200
   - Open gallery in browser, hard-refresh, eyeball 15 cards in two clusters
   - Open the flight-booking demo, exercise key alive interaction, refresh, confirm `savedTrips` persists

If Cloudflare caches stale `/api/template-preview/<key>/preview.png` for the new keys: the `?v=5` query string is the cache-buster. No manual purge needed.

---

## 15. Risks and open questions

### Risks

- **Bundle weight:** Five templates with full feature scope, ~6-15 KB HTML each + ~30 KB main.js + ~10 KB data.js = ~50 KB per template. Within Tailwind CDN limits; no concerns.
- **Image loading from Unsplash:** if Unsplash rate-limits the gallery, capture script falls back to picsum-seeded placeholders. Already handled in `capture-local-templates.py`.
- **Playwright not on CI:** acceptable — tests run locally during execution, marked optional via `importorskip`.
- **localStorage quota:** ~5 MB per origin in Chrome. Even with all 5 templates' worst-case persistence (~10 KB each), we're at < 1 % of quota.
- **Cross-template state pollution:** prevented by per-template namespace strings (`io-template:<ns>:<key>`).

### Open questions surfaced but deferred

- Should the catalog UI show category sub-headings in the gallery? Spec says yes ("Functional apps" + "Design showcases" sub-rows). If the UI changes are too disruptive, fall back to one undifferentiated grid.
- Should we add a "Try the demo" CTA on each card that opens a sandbox URL bypassing the build step? Out of scope for this spec; consider after deploy.

---

## 16. Implementation order (preview — full plan to be written by writing-plans)

Anticipated task breakdown for `subagent-driven-development`:

1. Create worktree from `feat/design-templates`. The canonical source for `router.js`, `persistence.js`, and `skeleton.js` is **§3 of this spec** (full code shown). Each new `template_apps/<key>/src/lib/` gets a hand-written copy of these three files, matching the spec verbatim. No `template_apps/_shared/` directory — copies are deliberate (see §3).
2. Implement `flight-booking` end-to-end (reference template)
3. Implement `food-delivery` end-to-end
4. Implement `job-board` end-to-end
5. Implement `movie-tickets` end-to-end (seat picker is the highest-effort)
6. Implement `recipe-site` end-to-end (cook mode + wakelock + serving slider)
7. Register all 5 in `templates.py` with `_RULES_<KEY>`, `_SVG_<KEY>`, `Template(...)` entries
8. Update `templates.html` + `projects.html` for FEATURED_KEYS expansion + sub-grouping + `PREVIEW_VER="5"` bump
9. Write static + Playwright tests
10. Capture preview PNGs via extended `_tplpng/capture-local-templates.py`
11. SCP + docker compose build + verify on production

---

**End of spec.**
