# App Builder — 5 Design-Forward Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 5 new fully-scaffolded "design-forward" templates (`agency`, `restaurant`, `photography`, `event`, `real-estate`) to the App Builder gallery, each with built-in animations, image placement, and finished-looking demo content.

**Spec:** `docs/superpowers/specs/2026-05-08-app-builder-design-templates.md`

**Architecture:** Pure additive change to existing scaffolded-template pipeline. Each template is a self-contained folder under `mcp-servers/tasks/template_apps/<key>/` mirroring the `landing/` and `portfolio/` pattern. Registration in `templates.py` (rules + SVG mockup + `Template(...)` entry) makes them surface in the gallery. Zero changes to gallery UI code, build executor, or routing.

**Tech Stack:** Static HTML5 + Tailwind CDN + Alpine.js + vanilla ES modules + `IntersectionObserver`. No new libraries. Images from `images.unsplash.com` and `picsum.photos`. Tests: `pytest` against the FastAPI tasks service.

---

## File Structure

### Files to create (per-template, 5× repeated)

```
mcp-servers/tasks/template_apps/<key>/
  index.html                       # 200–500 lines, semantic HTML5, Alpine
  styles/main.css                  # palette tokens, animation keyframes, custom CSS
  src/main.js                      # Alpine.start() + IntersectionObserver + reduced-motion guard
  src/components/<component>.js    # 1–3 Alpine x-data factories per template
  README.md                        # 1-paragraph description + photo-ID provenance
  public/.gitkeep                  # empty placeholder so the dir exists
  preview.png                      # 1280×800 Playwright screenshot, captured in Task 8
```

### Files to modify

- `mcp-servers/tasks/templates.py` — append `_RULES_<KEY>`, `_SVG_<KEY>`, `Template(...)` entries (×5)
- `mcp-servers/tasks/tests/test_templates.py` — update expected count + key set + API field set
- `mcp-servers/tasks/static/templates.html` — bump `PREVIEW_VER` from `"2"` to `"3"`
- `_tplpng/screenshot-templates.js` — append the 5 new keys to the `TEMPLATES` array

### Files to create (tests + tooling)

- `mcp-servers/tasks/tests/test_template_apps_static.py` — parametrized static-HTML checks for the 5 new templates
- `mcp-servers/tasks/tests/test_template_apps_animations.py` — Playwright positive-path test for count-up

### Spec deviations (intentional)

The spec mentions updating `tests/test_supabase_inject.py` and `tests/test_routes_graph.py`, but **this plan deliberately does not touch them**:
- `test_routes_graph.py` tests the per-project file-dependency graph (`/api/projects/<slug>/graph`) — unrelated to the template catalog.
- `test_supabase_inject.py` tests runtime HTML injection on **published** apps without iterating template keys — its assertions are key-agnostic, so adding 5 new `storage="none"` templates doesn't change the contract it covers.

Both omissions are correct judgment calls; flag in PR description so reviewers don't expect those file changes.

### Reusable code blocks (used by multiple tasks)

These appear inline in their first usage (Task 4: agency) and are referenced by later tasks.

#### Block A: `src/main.js` skeleton (every template)

```js
// src/main.js — boots Alpine + scroll-reveal observer.
// All 5 design templates share this exact file (only the imported
// components below differ per template).
import "./components/<componentName>.js"; // template-specific factories

// Respect prefers-reduced-motion: skip ALL transitions, parallax, count-ups.
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

document.addEventListener("alpine:init", () => {
  // Per-template Alpine.data() registrations are imported via the
  // component file above; nothing else to do here.
});

// Scroll-reveal: any element with class `reveal` fades in once on enter.
if (!REDUCED && "IntersectionObserver" in window) {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        e.target.classList.add("is-visible");
        io.unobserve(e.target);
      }
    }
  }, { threshold: 0.2 });
  document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
} else {
  // Reduced motion (or no IO support): show everything immediately.
  document.querySelectorAll(".reveal").forEach((el) =>
    el.classList.add("is-visible"));
}
```

#### Block B: shared CSS primitives (every template's `styles/main.css` includes these)

```css
/* ---- Reduced-motion guard: must be at the TOP of every styles file ---- */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}

/* ---- Scroll reveal ---- */
.reveal {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity 600ms ease-out, transform 600ms ease-out;
}
.reveal.is-visible { opacity: 1; transform: translateY(0); }

/* ---- Hover image zoom (used inside .zoom-card) ---- */
.zoom-card { overflow: hidden; }
.zoom-card img {
  transition: transform 600ms ease-out;
}
.zoom-card:hover img { transform: scale(1.05); }

/* ---- Marquee infinite scroll ---- */
@keyframes marquee {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}
.marquee {
  display: flex;
  gap: 3rem;
  width: max-content;
  animation: marquee 30s linear infinite;
}
.marquee:hover { animation-play-state: paused; }
```

#### Block C: count-up Alpine factory (used by agency, event, real-estate)

```js
// src/components/countUp.js
export const countUp = (target) => ({
  n: 0,
  target,
  done: false,
  start() {
    if (this.done) return;
    this.done = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      this.n = this.target;
      return;
    }
    const t0 = performance.now();
    const dur = 1500;
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - k, 3);
      this.n = Math.round(this.target * eased);
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  },
});

// Usage in HTML:
//   <div x-data="countUp(247)" x-intersect="start()">
//     <span x-text="n"></span>+
//   </div>
// (Alpine's x-intersect plugin not in baseline — use IntersectionObserver
//  in src/main.js instead, calling el.__x.$data.start() on visible.)
```

> **Note:** `x-intersect` is not loaded by default. The plan uses the existing `IntersectionObserver` in `src/main.js` to also kick off count-up: `if (e.target.matches(".count-up")) e.target._x_dataStack[0].start();`. This is shown in Task 4 (agency) and reused.

#### Block D: lightbox Alpine factory (used by photography, real-estate)

```js
// src/components/lightbox.js
export const lightbox = () => ({
  open: false,
  src: "",
  alt: "",
  idx: 0,
  images: [], // populated from x-init by gathering data-img-slot="gallery"
  init() {
    this.images = Array.from(document.querySelectorAll('[data-img-slot="gallery"]'))
      .map((img) => ({ src: img.dataset.full || img.src, alt: img.alt }));
    document.addEventListener("keydown", (e) => {
      if (!this.open) return;
      if (e.key === "Escape") this.open = false;
      if (e.key === "ArrowRight") this.next();
      if (e.key === "ArrowLeft") this.prev();
    });
  },
  show(i) {
    this.idx = i;
    this.src = this.images[i].src;
    this.alt = this.images[i].alt;
    this.open = true;
  },
  next() { this.show((this.idx + 1) % this.images.length); },
  prev() { this.show((this.idx - 1 + this.images.length) % this.images.length); },
});
```

---

## Tasks

### Task 1: Catalog wiring — register 5 templates in `templates.py` and update tests

**Files:**
- Modify: `mcp-servers/tasks/templates.py:475-685` (append entries to `TEMPLATES` list, add `_RULES_*`, `_SVG_*` constants)
- Modify: `mcp-servers/tasks/tests/test_templates.py:15-20`, `:43-45`, `:114`, `:115`

**Goal:** After this task, the gallery already shows the 5 new templates as featured cards (with their SVG mockups, since `preview.png` doesn't exist yet). Builds will FAIL because the template_apps/ folders don't exist — that's intentional; we wire registry first so test_templates.py drives implementation.

- [ ] **Step 1: Update `tests/test_templates.py` to expect 24 templates with the new keys.**

```python
# tests/test_templates.py — replace EXPECTED_KEYS + test_19_templates_present
EXPECTED_KEYS = {
    "landing", "dashboard", "crud", "crm", "portfolio", "docs",
    "ecommerce", "booking", "chat", "auth", "blog", "blank",
    "invoice", "project-tracker", "ai-chatbot", "expense-tracker",
    "form-builder", "social-feed", "custom",
    # New design-forward templates (2026-05-08):
    "agency", "restaurant", "photography", "event", "real-estate",
}

def test_24_templates_present():
    assert len(TEMPLATES) == 24
    assert {t.key for t in TEMPLATES} == EXPECTED_KEYS
```

Also update the API endpoint test at `:114-119`. **Note:** the existing `expected_fields` set in this test is also stale relative to `routes_templates.py:TemplateOut` (which already returns `storage`, `role_tag`, `feature_bullets`, `has_app`, `svg_mockup`) — so this isn't purely additive, it's also fixing a pre-existing test that's drifted from the API. The new expected set should match `TemplateOut`'s 10 fields exactly:

```python
async def test_get_endpoint_excludes_rules_field():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/templates", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 24
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

Expected: FAIL on `test_24_templates_present` ("`assert 19 == 24`") and on the rules-section / metadata tests for the 5 new keys (KeyError or AssertionError).

- [ ] **Step 3: Add `_RULES_<KEY>` constants to `templates.py`.**

Add these BEFORE the `TEMPLATES = [...]` list (place near the other `_RULES_*` constants). Each rules string MUST contain the four section markers (`PURPOSE:`, `TECH:`, `MUST INCLUDE:`, `LAYOUT:`) — that's the existing test contract.

```python
_RULES_AGENCY: str = "\n".join([
    "PURPOSE: A bold, image-led studio/agency website. Showcases the firm's work, capabilities, clients, and personality.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES. No build step. No npm install.",
    "MUST INCLUDE:",
    "  • Sticky top nav (logo + 4 anchor links + 'Let's talk' CTA). Solidifies on scroll past hero.",
    "  • Full-bleed hero with massive headline (animated gradient text), subhead, mouse-follow accent dot.",
    "  • Infinite-scroll services marquee strip ('Brand · Web · Motion · Strategy ·').",
    "  • Selected work grid: 6 case-study cards in 2-col layout, hover zoom on image, project name + tags reveal on hover.",
    "  • Animated stats strip with 4 count-up numbers (Years, Projects, Clients, Awards) triggered on scroll-into-view.",
    "  • 4 capability cards (Strategy / Brand / Web / Content) with icon + heading + paragraph.",
    "  • Client logo strip (8–10 SVG wordmarks).",
    "  • Bold pull-quote testimonial with client photo, name, role.",
    "  • Full-bleed contact CTA + simulated contact form (toast on submit).",
    "  • Footer with copyright + social links.",
    "LAYOUT: charcoal #0a0a0b background, off-white text, lime-electric accent #c1ff00. Inter for body, Space Grotesk for display headings. CSS custom properties --bg, --text, --accent, --serif, --sans control the palette.",
    "ANIMATIONS PRESENT: .reveal scroll-fade, .zoom-card image hover, .marquee infinite scroll, count-up stats, mouse-follow accent dot, sticky section labels.",
    "DO NOT REMOVE: the IntersectionObserver in src/main.js, the prefers-reduced-motion guard at the top of styles/main.css.",
    "SAFE TO CUSTOMIZE: all copy, image URLs (must stay on whitelist: images.unsplash.com, picsum.photos), palette CSS variables, agency name, service offerings, case-study list, client logos, testimonial.",
    "IMAGE SLOTS (data-img-slot): hero, work (case-study thumbs), avatar (testimonial), logo (client logos).",
    "TYPOGRAPHY: Inter (body) + Space Grotesk (display) loaded via fonts.googleapis.com.",
])

_RULES_RESTAURANT: str = "\n".join([
    "PURPOSE: A warm, atmospheric restaurant or cafe website. Showcases the menu, story, hours, and reservations.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES. No build step. No npm install.",
    "MUST INCLUDE:",
    "  • Sticky top nav (logo + Menu/About/Reservations/Visit links).",
    "  • Parallax hero (full-bleed food photo translates on scroll). Centered restaurant name in display serif. Reserve CTA.",
    "  • Story section: 2 paragraphs about the place + chef portrait on the right.",
    "  • Tabbed menu with 4 tabs (Brunch / Lunch / Dinner / Drinks). Each tab shows a grid of food cards (image + name + description + price).",
    "  • Photo strip: 8-image masonry grid of food and atmosphere shots.",
    "  • Hours table + map placeholder (gradient block w/ pin icon) side-by-side.",
    "  • Reservation form (date / time / party size / name / email). Simulated submit with toast.",
    "  • Footer with address, phone, social links.",
    "LAYOUT: cream #faf6ef background, espresso #2a1f17 text, terracotta #c46a4f accent. Playfair Display for headings, Inter for body. CSS custom properties --bg, --text, --accent control the palette.",
    "ANIMATIONS PRESENT: parallax hero (rAF-throttled scrollY*0.4), .reveal scroll-fade, Alpine x-show menu tab transitions, .zoom-card hover on food cards.",
    "DO NOT REMOVE: parallax rAF throttle, prefers-reduced-motion guard.",
    "SAFE TO CUSTOMIZE: all copy, restaurant name, menu items + prices, hours, address, palette CSS variables, image URLs (whitelist only).",
    "IMAGE SLOTS (data-img-slot): hero, chef-portrait, menu-item, gallery.",
    "TYPOGRAPHY: Playfair Display (display) + Inter (body) loaded via fonts.googleapis.com.",
])

_RULES_PHOTOGRAPHY: str = "\n".join([
    "PURPOSE: An image-led photographer portfolio. Minimal chrome, full-bleed gallery, lightbox for image details.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES. No build step. No npm install.",
    "MUST INCLUDE:",
    "  • Floating top nav (photographer name + Work / Series / About / Contact).",
    "  • Full-screen hero image with photographer name + tagline overlaid bottom-left. Pulsing scroll-down indicator.",
    "  • 3 featured series, each with a 3-image collage + title + 1-paragraph description.",
    "  • Masonry grid: 12–15 images, varied aspect ratios. Click → lightbox.",
    "  • Lightbox overlay: backdrop click closes, Escape closes, Arrow keys navigate.",
    "  • About section: portrait photo + 2-paragraph bio + selected publications/clients list.",
    "  • Minimal contact: email + Instagram link.",
    "  • Footer.",
    "LAYOUT: pure black #000 background, white #fff text, no accent color. Inter for everything, wide letter-spacing on display text.",
    "ANIMATIONS PRESENT: .reveal scroll-fade, hero scroll-down pulse keyframe, .zoom-card hover on grid items, Alpine lightbox open/close transition.",
    "DO NOT REMOVE: the lightbox component, the prefers-reduced-motion guard, the keyboard navigation event listener.",
    "SAFE TO CUSTOMIZE: all copy, photographer name, image URLs (whitelist only), series count and titles, gallery images.",
    "IMAGE SLOTS (data-img-slot): hero, series, gallery, portrait.",
    "TYPOGRAPHY: Inter loaded via fonts.googleapis.com.",
])

_RULES_EVENT: str = "\n".join([
    "PURPOSE: A bold, modern conference or festival landing page. Drives ticket sales and showcases speakers + agenda.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES. No build step. No npm install.",
    "MUST INCLUDE:",
    "  • Sticky top nav (logo + Speakers / Schedule / Tickets / Venue links).",
    "  • Hero with bold event name + dates + city. Live countdown to event date (days/hours/mins/secs). Buy Tickets CTA.",
    "    When countdown elapses, displays 'Event in progress' instead of 00:00:00:00.",
    "  • 3 stat cards (Talks / Speakers / Attendees) with count-up numbers.",
    "  • Speaker grid: 12 cards each with photo, name, title, company. Hover reveals brief bio.",
    "  • Schedule with Day 1 / Day 2 tabs. Each tab is a vertical timeline of sessions.",
    "  • Tiered sponsor logo grid (Platinum / Gold / Silver).",
    "  • Venue: address + map placeholder + 2-3 venue photos.",
    "  • 3 ticket-tier cards (Early Bird / Regular / VIP) with pricing + perks.",
    "  • FAQ accordion (Alpine x-show).",
    "  • Footer.",
    "LAYOUT: deep navy #0a1230 background, neon cyan #22d3ee accent, off-white text. Space Grotesk for everything.",
    "ANIMATIONS PRESENT: live countdown (1Hz setInterval), count-up stats, speaker hover bio reveal (Alpine x-transition), schedule tab transitions, .reveal scroll-fade, sponsor strip subtle scroll.",
    "DO NOT REMOVE: the countdown setInterval guard for prefers-reduced-motion (set target value once and skip ticking), the IntersectionObserver, the prefers-reduced-motion guard.",
    "SAFE TO CUSTOMIZE: event name, dates, city, speaker list, schedule sessions, sponsor logos, ticket tiers, FAQ items, palette CSS variables, image URLs (whitelist only).",
    "IMAGE SLOTS (data-img-slot): hero, speaker (avatar), venue, sponsor.",
    "TYPOGRAPHY: Space Grotesk loaded via fonts.googleapis.com.",
])

_RULES_REAL_ESTATE: str = "\n".join([
    "PURPOSE: An editorial property listing page. Showcases a single property with image gallery, stats, and agent contact.",
    "TECH: Static HTML + Tailwind CDN + Alpine.js + vanilla ES. No build step. No npm install.",
    "MUST INCLUDE:",
    "  • Top nav (agent name + Listings / About / Contact).",
    "  • Hero: property image carousel (3–5 images, auto-advance every 5s + manual prev/next + dot indicators). Address overlay + price tag.",
    "  • Animated stats strip: beds / baths / sqft / lot size, all with count-up animation.",
    "  • Description: 2 paragraphs + amenities checklist (8–12 items grouped by category).",
    "  • 9-image photo gallery with masonry layout. Click → lightbox (shared component with photography template).",
    "  • Map placeholder + neighborhood blurb (2 paragraphs about the area).",
    "  • 'More from agent' row: 3 smaller listing cards.",
    "  • Agent profile: agent photo, bio, phone, email, schedule-a-viewing form (date/time/name/email/phone). Simulated submit.",
    "  • Footer.",
    "LAYOUT: cream #faf7f2 background, slate #1f2937 text, warm gold #b08a3e accent. Cormorant Garamond for headings, Inter for body. CSS custom properties control the palette.",
    "ANIMATIONS PRESENT: hero carousel (Alpine x-data with timer), count-up stats, gallery lightbox, .reveal scroll-fade, parallax hero (rAF-throttled).",
    "DO NOT REMOVE: the lightbox component, the carousel timer cleanup, the prefers-reduced-motion guard.",
    "SAFE TO CUSTOMIZE: property address, price, stats, description, amenities, photo URLs (whitelist only), agent name + bio + photo, neighborhood blurb, palette CSS variables.",
    "IMAGE SLOTS (data-img-slot): hero, gallery, agent-portrait, neighborhood.",
    "TYPOGRAPHY: Cormorant Garamond (display) + Inter (body) loaded via fonts.googleapis.com.",
])
```

- [ ] **Step 4: Add `_SVG_<KEY>` constants to `templates.py`** (place next to existing `_SVG_*` constants).

Each is a small inline SVG (~15–25 lines) shown on the gallery card before `preview.png` loads. Pattern: stylized layout sketch using the template's palette colors. Keep the SVG simple (rectangles, lines, text) — it's a thumbnail, not a full mockup.

```python
_SVG_AGENCY = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#0a0a0b"/>
  <text x="20" y="60" fill="#ffffff" font-family="ui-sans-serif" font-size="22" font-weight="700">Studio</text>
  <text x="20" y="86" fill="#c1ff00" font-family="ui-sans-serif" font-size="14">→ work · brand · web</text>
  <rect x="20" y="110" width="130" height="60" fill="#1c1c1e" rx="4"/>
  <rect x="160" y="110" width="130" height="60" fill="#1c1c1e" rx="4"/>
</svg>"""

_SVG_RESTAURANT = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#faf6ef"/>
  <rect x="0" y="0" width="320" height="120" fill="#c46a4f" opacity="0.18"/>
  <text x="160" y="68" fill="#2a1f17" font-family="Georgia,serif" font-size="22" font-weight="700" text-anchor="middle">La Maison</text>
  <text x="160" y="92" fill="#2a1f17" font-family="ui-sans-serif" font-size="11" text-anchor="middle">— since 2014 —</text>
  <rect x="20" y="140" width="80" height="40" fill="#ffffff" stroke="#e8dccc" rx="3"/>
  <rect x="120" y="140" width="80" height="40" fill="#ffffff" stroke="#e8dccc" rx="3"/>
  <rect x="220" y="140" width="80" height="40" fill="#ffffff" stroke="#e8dccc" rx="3"/>
</svg>"""

_SVG_PHOTOGRAPHY = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#000000"/>
  <rect x="20" y="20" width="84" height="78" fill="#1a1a1a"/>
  <rect x="118" y="20" width="84" height="58" fill="#1a1a1a"/>
  <rect x="216" y="20" width="84" height="98" fill="#1a1a1a"/>
  <rect x="20" y="112" width="84" height="68" fill="#1a1a1a"/>
  <rect x="118" y="92" width="84" height="88" fill="#1a1a1a"/>
  <rect x="216" y="132" width="84" height="48" fill="#1a1a1a"/>
</svg>"""

_SVG_EVENT = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#0a1230"/>
  <text x="20" y="60" fill="#ffffff" font-family="ui-sans-serif" font-size="24" font-weight="700">DEVCON</text>
  <text x="20" y="84" fill="#22d3ee" font-family="ui-sans-serif" font-size="13">Sept 12—14 · Berlin</text>
  <rect x="20" y="110" width="56" height="48" fill="#1a2750" rx="3"/>
  <text x="48" y="140" fill="#22d3ee" font-family="ui-sans-serif" font-size="20" font-weight="700" text-anchor="middle">42</text>
  <rect x="86" y="110" width="56" height="48" fill="#1a2750" rx="3"/>
  <rect x="152" y="110" width="56" height="48" fill="#1a2750" rx="3"/>
  <rect x="218" y="110" width="56" height="48" fill="#1a2750" rx="3"/>
</svg>"""

_SVG_REAL_ESTATE = """<svg viewBox="0 0 320 200" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
  <rect width="320" height="200" fill="#faf7f2"/>
  <rect x="0" y="0" width="320" height="120" fill="#1f2937" opacity="0.08"/>
  <rect x="20" y="20" width="200" height="100" fill="#e5d9bd" rx="3"/>
  <text x="240" y="48" fill="#1f2937" font-family="Georgia,serif" font-size="14" font-weight="700">$1.2M</text>
  <text x="240" y="68" fill="#b08a3e" font-family="ui-sans-serif" font-size="10">42 Maple St</text>
  <text x="20" y="150" fill="#1f2937" font-family="ui-sans-serif" font-size="11">3 BD · 2 BA · 1,840 sqft</text>
  <rect x="20" y="170" width="280" height="14" fill="#e5d9bd" rx="2"/>
</svg>"""
```

- [ ] **Step 5: Append the 5 `Template(...)` entries to the `TEMPLATES` list** (insert before the `Template(key="custom", ...)` entry, since `custom` is the synthetic escape-hatch and should stay last).

```python
    Template(
        key="agency",
        label="Agency",
        emoji="🪐",
        description="bold studio site",
        placeholder="e.g. Studio site for a 6-person brand agency called 'Halftone'. 6 case studies, services for brand/web/motion, 2 testimonials, dark + lime-electric palette, animated hero.",
        rules=_RULES_AGENCY,
        storage="none",
        role_tag="Studio site",
        feature_bullets=(
            "Bold scroll-driven hero with marquee work strip",
            "Case-study grid with hover image reveals",
            "Animated client logo carousel + sticky section labels",
        ),
        svg_mockup=_SVG_AGENCY,
    ),
    Template(
        key="restaurant",
        label="Restaurant",
        emoji="🍽️",
        description="restaurant or cafe site",
        placeholder="e.g. Italian restaurant called 'La Maison'. Menu with 12 items across Brunch/Lunch/Dinner/Drinks. Hours 11am-10pm Tue-Sun. Warm cream + terracotta palette. Reservation form.",
        rules=_RULES_RESTAURANT,
        storage="none",
        role_tag="Restaurant / cafe",
        feature_bullets=(
            "Parallax food-photography hero",
            "Tabbed menu with image cards + prices",
            "Hours, map placeholder, and reservation form",
        ),
        svg_mockup=_SVG_RESTAURANT,
    ),
    Template(
        key="photography",
        label="Photography",
        emoji="📸",
        description="photographer portfolio",
        placeholder="e.g. Portfolio for travel photographer Mara Lin. 3 featured series (Iceland, Tokyo Streets, Coastal Light), 15-image masonry grid, About + selected clients (Conde Nast, NYT). Pure black + white palette.",
        rules=_RULES_PHOTOGRAPHY,
        storage="none",
        role_tag="Photographer site",
        feature_bullets=(
            "Full-bleed image gallery with masonry layout",
            "Lightbox overlay with keyboard navigation",
            "Scroll-triggered fades, minimal chrome",
        ),
        svg_mockup=_SVG_PHOTOGRAPHY,
    ),
    Template(
        key="event",
        label="Event",
        emoji="🎤",
        description="conference or festival",
        placeholder="e.g. 2-day developer conference 'DevCon Berlin', Sept 12-14. 12 speakers, 2-day schedule, 3 ticket tiers (Early Bird $299 / Regular $449 / VIP $899). Navy + neon cyan palette.",
        rules=_RULES_EVENT,
        storage="none",
        role_tag="Conference / festival",
        feature_bullets=(
            "Live countdown to event date",
            "Speaker grid with photos + hover bio",
            "Agenda timeline, sponsor tiers, and FAQ accordion",
        ),
        svg_mockup=_SVG_EVENT,
    ),
    Template(
        key="real-estate",
        label="Real estate",
        emoji="🏡",
        description="property listing",
        placeholder="e.g. Listing for a 3-bed Victorian at 42 Maple St, $1.2M. Carousel with 9 photos, beds/baths/sqft stats, neighborhood blurb. Agent: Sarah Mendez. Cream + warm gold palette.",
        rules=_RULES_REAL_ESTATE,
        storage="none",
        role_tag="Property listing",
        feature_bullets=(
            "Property image carousel with auto-advance + lightbox",
            "Animated stat counters (beds, baths, sqft, price)",
            "Map placeholder, agent profile, and viewing-request form",
        ),
        svg_mockup=_SVG_REAL_ESTATE,
    ),
```

- [ ] **Step 6: Run the test to verify it passes.**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_templates.py -v
```

Expected: ALL tests pass. Particularly:
- `test_24_templates_present` PASSES (24 == 24, key set matches)
- `test_each_template_has_rules` PASSES (each new template's rules > 200 chars)
- `test_each_template_has_required_sections` PASSES (each new template's rules contain `PURPOSE`, `TECH`, `MUST INCLUDE`, `LAYOUT`)
- `test_each_template_has_required_metadata` PASSES (label/emoji/description/placeholder all set)
- `test_get_endpoint_excludes_rules_field` PASSES (24 items, expected_fields match)

- [ ] **Step 7: Commit.**

```bash
git add mcp-servers/tasks/templates.py mcp-servers/tasks/tests/test_templates.py
git commit -m "feat(templates): register 5 design-forward templates (agency, restaurant, photography, event, real-estate)"
```

---

### Task 2: Static-HTML test harness — fail-first parametrized tests

**Files:**
- Create: `mcp-servers/tasks/tests/test_template_apps_static.py`

**Goal:** Define the structural contract every new template must satisfy. After this task, all 5 parametrized tests fail (because no `index.html` exists yet). Each scaffold task (3–7) will turn one of the 5 tests green.

- [ ] **Step 1: Write the failing parametrized test.**

```python
# mcp-servers/tasks/tests/test_template_apps_static.py
"""Static-HTML structural checks for the 5 design-forward templates.

Each template must:
  • have an index.html on disk under template_apps/<key>/
  • parse as HTML5 (single <h1>, no obvious malformed structure)
  • include a <link> to styles/main.css and <script type="module"> to src/main.js
  • declare every expected section via data-section="<name>" markers
  • have alt text + loading attribute + width/height on every <img>
  • NOT contain placeholder strings (Lorem ipsum, TODO, Coming soon, etc.)
  • only reference whitelisted CDNs (tailwind, alpine, fonts.googleapis,
    cdn.jsdelivr, unpkg, images.unsplash.com, picsum.photos)
"""
import re
from pathlib import Path

import pytest

TEMPLATE_APPS_DIR = Path(__file__).resolve().parents[1] / "template_apps"

# Keys -> ordered list of data-section markers expected in index.html.
EXPECTED_SECTIONS = {
    "agency":      ["nav", "hero", "marquee", "work", "stats", "capabilities", "logos", "testimonial", "cta", "footer"],
    "restaurant":  ["nav", "hero", "story", "menu", "gallery", "hours", "reservation", "footer"],
    "photography": ["nav", "hero", "series", "gallery", "about", "contact", "footer"],
    "event":       ["nav", "hero", "stats", "speakers", "schedule", "sponsors", "venue", "tickets", "faq", "footer"],
    "real-estate": ["nav", "hero", "stats", "description", "gallery", "map", "more-listings", "agent", "footer"],
}

PLACEHOLDER_FORBIDDEN = re.compile(
    r"\b(lorem ipsum|todo|coming soon|placeholder|your bio goes here|add content here)\b",
    re.IGNORECASE,
)

# Allowed external hosts. Any other src= or href= host is a failure.
ALLOWED_HOSTS = {
    "cdn.tailwindcss.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "images.unsplash.com",
    "picsum.photos",
}

EXTERNAL_URL_RE = re.compile(r'https?://([^/\s"\'<>]+)')


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_index_html_exists(key):
    p = TEMPLATE_APPS_DIR / key / "index.html"
    assert p.exists(), f"{p} missing"
    assert p.stat().st_size > 5_000, f"{p} suspiciously small ({p.stat().st_size} bytes)"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_has_required_section_markers(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    for section in EXPECTED_SECTIONS[key]:
        marker = f'data-section="{section}"'
        assert marker in html, f"{key}: missing section marker {marker!r}"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_single_h1(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    h1_count = len(re.findall(r"<h1\b", html, flags=re.IGNORECASE))
    assert h1_count == 1, f"{key}: expected exactly one <h1>, got {h1_count}"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_imgs_have_required_attrs(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    img_tags = re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE)
    assert img_tags, f"{key}: no <img> tags found (visual templates need images)"
    for tag in img_tags:
        for attr in ("alt=", "loading=", "width=", "height="):
            assert attr in tag.lower(), f"{key}: <img> missing {attr!r}: {tag[:120]}…"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_no_placeholder_strings(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    m = PLACEHOLDER_FORBIDDEN.search(html)
    assert m is None, f"{key}: placeholder string {m.group(0)!r} present"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_only_whitelisted_external_hosts(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    hosts = set(EXTERNAL_URL_RE.findall(html))
    bad = hosts - ALLOWED_HOSTS
    assert not bad, f"{key}: non-whitelisted external hosts: {sorted(bad)}"


@pytest.mark.parametrize("key", list(EXPECTED_SECTIONS.keys()))
def test_template_loads_main_js_and_css(key):
    html = (TEMPLATE_APPS_DIR / key / "index.html").read_text(encoding="utf-8")
    assert 'href="styles/main.css"' in html, f"{key}: missing styles/main.css link"
    assert 'src="src/main.js"' in html, f"{key}: missing src/main.js script"
    assert 'type="module"' in html, f"{key}: src/main.js must load as ES module"
```

- [ ] **Step 2: Run the test to verify all 5 keys fail.**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_template_apps_static.py -v
```

Expected: 35 failures (7 tests × 5 keys), all citing missing `index.html` or missing markers.

- [ ] **Step 3: Commit.**

```bash
git add mcp-servers/tasks/tests/test_template_apps_static.py
git commit -m "test(templates): static-HTML contract for 5 new design templates"
```

---

### Task 3: Scaffold the **agency** template

**Files:**
- Create: `mcp-servers/tasks/template_apps/agency/index.html`
- Create: `mcp-servers/tasks/template_apps/agency/styles/main.css`
- Create: `mcp-servers/tasks/template_apps/agency/src/main.js`
- Create: `mcp-servers/tasks/template_apps/agency/src/components/agencyComponents.js`
- Create: `mcp-servers/tasks/template_apps/agency/README.md`
- Create: `mcp-servers/tasks/template_apps/agency/public/.gitkeep`

**Goal:** Build the agency template fully — all 10 sections from the spec, animations, demo content. Tests for `key="agency"` go green. Sets the pattern for the other 4 templates (Tasks 4–7).

**Design intent:** Bold dark studio site, charcoal `#0a0a0b` bg, off-white text, lime-electric `#c1ff00` accent, Inter body + Space Grotesk display.

**Sections in order** (each wrapped in `<section data-section="<name>">…`):
nav · hero · marquee · work · stats · capabilities · logos · testimonial · cta · footer

- [ ] **Step 1: Create the public/.gitkeep and README.**

```bash
mkdir -p "mcp-servers/tasks/template_apps/agency/styles" \
         "mcp-servers/tasks/template_apps/agency/src/components" \
         "mcp-servers/tasks/template_apps/agency/public"
echo "" > "mcp-servers/tasks/template_apps/agency/public/.gitkeep"
```

```markdown
<!-- mcp-servers/tasks/template_apps/agency/README.md -->
# Agency template

Bold, dark, image-led studio site. Charcoal background, off-white text,
lime-electric accent. Inter for body, Space Grotesk for display.

Animations: scroll-fade reveal, marquee infinite scroll, hover image zoom,
count-up stats, mouse-follow accent dot. Respects `prefers-reduced-motion`.

Pinned Unsplash photo IDs (refresh if any 404):
- Hero:        `photo-1497366216548-37526070297c` (modern office interior)
- Work 1–6:    `photo-1561070791-2526d30994b8`, `photo-1542744095-291d1f67b221`,
               `photo-1558655146-9f40138edfeb`, `photo-1467232004584-a241de8bcf5d`,
               `photo-1467232004584-a241de8bcf5d`, `photo-1454165804606-c3d57bc86b40`
- Avatar:      `photo-1494790108377-be9c29b29330` (testimonial portrait)
```

- [ ] **Step 2: Create `styles/main.css` with the shared primitives plus agency-specific styles.**

```css
/* template_apps/agency/styles/main.css
   Agency template — dark, image-led studio site. */

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}

:root {
  --bg: #0a0a0b;
  --surface: #141416;
  --text: #f4f4f5;
  --muted: #71717a;
  --accent: #c1ff00;
  --serif: "Space Grotesk", system-ui, sans-serif;
  --sans: "Inter", system-ui, sans-serif;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  -webkit-font-smoothing: antialiased;
}

.font-display { font-family: var(--serif); letter-spacing: -0.02em; }

/* ---- Scroll reveal ---- */
.reveal {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity 600ms ease-out, transform 600ms ease-out;
}
.reveal.is-visible { opacity: 1; transform: translateY(0); }

/* ---- Hover image zoom ---- */
.zoom-card { overflow: hidden; }
.zoom-card img { transition: transform 600ms ease-out; }
.zoom-card:hover img { transform: scale(1.05); }

/* ---- Marquee ---- */
@keyframes marquee {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}
.marquee {
  display: flex;
  gap: 3rem;
  width: max-content;
  animation: marquee 40s linear infinite;
}
.marquee:hover { animation-play-state: paused; }

/* ---- Animated gradient hero text ---- */
@keyframes gradientShift {
  0%, 100% { background-position: 0% 50%; }
  50%      { background-position: 100% 50%; }
}
.gradient-text {
  background: linear-gradient(90deg, var(--accent), #fff, var(--accent));
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: gradientShift 8s ease-in-out infinite;
}

/* ---- Mouse-follow accent dot ---- */
.cursor-dot {
  position: fixed;
  width: 24px; height: 24px;
  border-radius: 50%;
  background: var(--accent);
  pointer-events: none;
  mix-blend-mode: difference;
  transform: translate(-50%, -50%);
  transition: transform 100ms ease-out;
  z-index: 50;
}

/* ---- Sticky section labels ---- */
.sticky-label {
  position: sticky;
  top: 96px;
  font-family: var(--serif);
  color: var(--accent);
  font-size: 0.75rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
```

- [ ] **Step 3: Create `src/components/agencyComponents.js`.**

```js
// template_apps/agency/src/components/agencyComponents.js
import { countUp } from "./countUp.js";

document.addEventListener("alpine:init", () => {
  Alpine.data("agency", () => ({
    mobileMenu: false,
    navSolid: false,
    init() {
      // Solidify nav after scrolling past the hero (~600px).
      const onScroll = () => { this.navSolid = window.scrollY > 600; };
      window.addEventListener("scroll", onScroll, { passive: true });

      // Mouse-follow accent dot.
      const dot = document.getElementById("cursor-dot");
      if (dot && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        let raf = null;
        let x = 0, y = 0;
        window.addEventListener("mousemove", (e) => {
          x = e.clientX; y = e.clientY;
          if (raf) return;
          raf = requestAnimationFrame(() => {
            dot.style.transform = `translate(${x}px, ${y}px)`;
            raf = null;
          });
        });
      }
    },
    submitContact() {
      this.$dispatch("toast", { msg: "Thanks — we'll be in touch within 24 hours.", kind: "success" });
    },
  }));

  Alpine.data("countUp", countUp);
});
```

```js
// template_apps/agency/src/components/countUp.js
// Reused unchanged in event and real-estate templates.
export const countUp = (target) => ({
  n: 0,
  target,
  done: false,
  start() {
    if (this.done) return;
    this.done = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      this.n = this.target;
      return;
    }
    const t0 = performance.now();
    const dur = 1500;
    const tick = (now) => {
      const k = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - k, 3);
      this.n = Math.round(this.target * eased);
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  },
});
```

- [ ] **Step 4: Create `src/main.js` (boots Alpine + IntersectionObserver + count-up trigger).**

```js
// template_apps/agency/src/main.js
import "./components/agencyComponents.js";

const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (!REDUCED && "IntersectionObserver" in window) {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("is-visible");
      // Kick off count-up Alpine state if this is a stat card.
      if (e.target.matches(".count-up")) {
        const stack = e.target._x_dataStack;
        if (stack && stack[0] && typeof stack[0].start === "function") {
          stack[0].start();
        }
      }
      io.unobserve(e.target);
    }
  }, { threshold: 0.2 });
  document.querySelectorAll(".reveal, .count-up").forEach((el) => io.observe(el));
} else {
  document.querySelectorAll(".reveal").forEach((el) => el.classList.add("is-visible"));
  document.querySelectorAll(".count-up").forEach((el) => {
    const stack = el._x_dataStack;
    if (stack && stack[0] && typeof stack[0].start === "function") stack[0].start();
  });
}
```

- [ ] **Step 5: Create `index.html`.**

This file is ~400 lines; the implementer should follow this section structure verbatim. Each `<section>` MUST carry `data-section="<name>"` matching `EXPECTED_SECTIONS["agency"]`. Use the demo content below verbatim as the starting point — the agent will customize per user prompt later.

Skeleton with all 10 sections (the implementer fills in Tailwind classes for layout — use the existing `landing/index.html` as the styling reference for spacing/typography). Substantive content for each section is written directly into the HTML — no placeholders.

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title><%= APP_NAME %> — Independent design studio</title>
  <meta name="description" content="<%= APP_NAME %> is an independent design studio building brands, websites, and motion for ambitious teams." />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet" />
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="styles/main.css" />
  <script type="module" src="src/main.js"></script>
  <script defer src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js"></script>
</head>
<body>
  <div id="cursor-dot" class="cursor-dot"></div>
  <div x-data="agency" x-init="init()">

    <section data-section="nav">
      <header :class="navSolid ? 'bg-[#0a0a0b]/95 border-b border-white/5' : 'bg-transparent'"
              class="fixed top-0 left-0 right-0 z-40 backdrop-blur transition">
        <!-- Logo + 4 anchor links + 'Let's talk' CTA, mobile hamburger -->
      </header>
    </section>

    <section data-section="hero" class="relative min-h-screen flex items-center px-6">
      <img data-img-slot="hero" loading="eager" fetchpriority="high"
           src="https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=1600&q=80"
           alt="Modern open-plan studio with daylight" width="1600" height="900"
           class="absolute inset-0 w-full h-full object-cover opacity-40" />
      <div class="relative max-w-5xl">
        <h1 class="font-display text-6xl md:text-8xl font-bold leading-[0.95]">
          We build brands<br/>that <span class="gradient-text">don't blend in.</span>
        </h1>
        <p class="mt-8 text-xl text-zinc-400 max-w-2xl">An independent six-person studio crafting brand systems, websites, and motion identity for ambitious teams.</p>
        <a href="#cta" class="mt-12 inline-flex items-center gap-2 px-8 py-4 bg-[var(--accent)] text-black font-semibold rounded-full">Start a project →</a>
      </div>
    </section>

    <section data-section="marquee" class="py-12 border-y border-white/5 overflow-hidden">
      <div class="marquee text-2xl md:text-4xl font-display text-zinc-500">
        <!-- Doubled list of services for infinite-scroll illusion -->
        <span>Brand identity</span><span>·</span><span>Web design</span><span>·</span>
        <span>Motion graphics</span><span>·</span><span>Strategy</span><span>·</span>
        <span>Brand identity</span><span>·</span><span>Web design</span><span>·</span>
        <span>Motion graphics</span><span>·</span><span>Strategy</span><span>·</span>
      </div>
    </section>

    <section data-section="work" class="py-32 px-6 max-w-7xl mx-auto">
      <div class="sticky-label mb-12 reveal">SELECTED WORK</div>
      <div class="grid md:grid-cols-2 gap-6">
        <!-- 6 work cards: each .zoom-card with image + project name + tags -->
        <!-- Use 6 different Unsplash photo IDs from the README provenance list -->
      </div>
    </section>

    <section data-section="stats" class="py-24 bg-[var(--surface)]">
      <div class="max-w-7xl mx-auto px-6 grid grid-cols-2 md:grid-cols-4 gap-8">
        <div class="count-up reveal" x-data="countUp(12)"><div class="text-5xl font-display"><span x-text="n"></span>+</div><div class="text-zinc-400 mt-2">Years</div></div>
        <div class="count-up reveal" x-data="countUp(247)"><div class="text-5xl font-display"><span x-text="n"></span>+</div><div class="text-zinc-400 mt-2">Projects</div></div>
        <div class="count-up reveal" x-data="countUp(89)"><div class="text-5xl font-display"><span x-text="n"></span>+</div><div class="text-zinc-400 mt-2">Clients</div></div>
        <div class="count-up reveal" x-data="countUp(34)"><div class="text-5xl font-display"><span x-text="n"></span></div><div class="text-zinc-400 mt-2">Awards</div></div>
      </div>
    </section>

    <section data-section="capabilities" class="py-32 px-6 max-w-7xl mx-auto">
      <!-- 4 capability cards: Strategy / Brand / Web / Content -->
      <!-- Each: icon (lucide SVG inline), heading, paragraph -->
    </section>

    <section data-section="logos" class="py-16 border-y border-white/5">
      <div class="max-w-7xl mx-auto px-6 grid grid-cols-3 md:grid-cols-5 gap-12 items-center opacity-60">
        <!-- 8–10 client wordmarks, each rendered as styled <span> with monospace font (no real logos to avoid trademark issues) -->
      </div>
    </section>

    <section data-section="testimonial" class="py-32 px-6 max-w-4xl mx-auto reveal">
      <blockquote class="text-3xl md:text-5xl font-display leading-tight">
        "They didn't just redesign our brand — they redesigned how we think about ourselves. Two years later we're still using their system as the north star."
      </blockquote>
      <div class="mt-8 flex items-center gap-4">
        <img data-img-slot="avatar" loading="lazy"
             src="https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=200&q=80&crop=faces"
             alt="Maya Patel, CEO of Northbeam" width="56" height="56" class="rounded-full" />
        <div><div class="font-semibold">Maya Patel</div><div class="text-zinc-400 text-sm">CEO, Northbeam</div></div>
      </div>
    </section>

    <section data-section="cta" id="cta" class="py-32 px-6 bg-[var(--surface)]">
      <div class="max-w-3xl mx-auto text-center">
        <h2 class="font-display text-5xl md:text-6xl font-bold">Let's build<br/>something great.</h2>
        <form @submit.prevent="submitContact()" class="mt-12 max-w-md mx-auto space-y-4">
          <input type="email" required placeholder="your@email.com" class="w-full px-6 py-4 bg-transparent border border-white/20 rounded-full" />
          <textarea required placeholder="Tell us about your project" rows="3" class="w-full px-6 py-4 bg-transparent border border-white/20 rounded-2xl"></textarea>
          <button type="submit" class="px-8 py-4 bg-[var(--accent)] text-black font-semibold rounded-full">Send →</button>
        </form>
      </div>
    </section>

    <section data-section="footer">
      <footer class="py-12 px-6 border-t border-white/5 text-zinc-500 text-sm">
        <div class="max-w-7xl mx-auto flex flex-col md:flex-row justify-between gap-4">
          <div>© 2026 <%= APP_NAME %>. Built with attention.</div>
          <div class="flex gap-6"><a href="#">Twitter</a><a href="#">Instagram</a><a href="#">Dribbble</a></div>
        </div>
      </footer>
    </section>

  </div>

  <!-- Toast root (listens for the `toast` event dispatched by Alpine) -->
  <div x-data="{ toasts: [] }" @toast.window="toasts.push($event.detail); setTimeout(() => toasts.shift(), 4000)"
       class="fixed bottom-6 right-6 space-y-2 z-50">
    <template x-for="t in toasts" :key="t.msg">
      <div class="bg-white text-black px-6 py-3 rounded-full shadow-lg" x-text="t.msg"></div>
    </template>
  </div>
</body>
</html>
```

The implementer fills in:
- Mobile menu detail in `data-section="nav"` (use landing/index.html as reference)
- 6 work cards in `data-section="work"` with real-looking project names + tags + Unsplash photos
- 4 capability cards in `data-section="capabilities"` with lucide-icons (load via CDN: `https://unpkg.com/lucide@latest/dist/umd/lucide.min.js`)
- 8 client wordmarks in `data-section="logos"` (made-up names like "NORTHBEAM", "HALCYON", "ATLAS", "MERIDIAN", "BLACKBIRD", "CIRRUS", "OAKWELL", "PRISM")

- [ ] **Step 6: Run the static-HTML test for `key="agency"`.**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_template_apps_static.py -v -k agency
```

Expected: All 7 parametrized tests for `agency` PASS.

- [ ] **Step 7: Visual sanity check (manual).**

Open `mcp-servers/tasks/template_apps/agency/index.html` directly in a browser using a local file URL. Verify:
- Hero loads with Unsplash image + animated gradient headline
- Marquee scrolls infinitely
- Work grid renders 6 cards with hover zoom
- Stats count up when scrolled into view
- Mouse-follow accent dot tracks cursor (desktop)
- Mobile viewport (320px) doesn't horizontally scroll

Note: the template uses `<%= APP_NAME %>` placeholders — they show as literal text in raw browser preview but get substituted at build time. That's expected.

- [ ] **Step 8: Commit.**

```bash
git add mcp-servers/tasks/template_apps/agency/
git commit -m "feat(templates): scaffold agency template — bold studio site"
```

---

### Task 4: Scaffold the **restaurant** template

**Files:**
- Create: `mcp-servers/tasks/template_apps/restaurant/{index.html, styles/main.css, src/main.js, src/components/restaurantComponents.js, README.md, public/.gitkeep}`

**Goal:** Warm, atmospheric restaurant site with parallax hero, tabbed menu, and reservation form. Tests for `key="restaurant"` go green.

**Sections** (each wrapped in `<section data-section="…">`):
nav · hero · story · menu · gallery · hours · reservation · footer

**Design intent:** cream `#faf6ef` bg, espresso `#2a1f17` text, terracotta `#c46a4f` accent, Playfair Display for headings, Inter for body.

**Animations:** parallax hero (rAF-throttled), `.reveal` scroll-fade, Alpine `x-show` for menu tabs, `.zoom-card` hover on food cards.

**Pinned Unsplash photo IDs** (write into README):
- Hero: `photo-1414235077428-338989a2e8c0` (warm restaurant interior)
- Chef portrait: `photo-1577219491135-ce391730fb2c`
- Menu items (12): `photo-1567620905732-2d1ec7ab7445`, `photo-1565958011703-44f9829ba187`,
  `photo-1546069901-ba9599a7e63c`, `photo-1551782450-a2132b4ba21d`,
  `photo-1565299624946-b28f40a0ae38`, `photo-1551183053-bf91a1d81141`,
  `photo-1432139509613-5c4255815697`, `photo-1502301197179-65228ab57f78`,
  `photo-1558030006-450675393462`, `photo-1486297678162-eb2a19b0a32d`,
  `photo-1546039907-7fa05f864c02`, `photo-1521305916504-4a1121188589`
- Gallery (8): pick 8 atmosphere shots

- [ ] **Step 1: Set up directory structure.** Same `mkdir -p` pattern as Task 3.

- [ ] **Step 2: Write `styles/main.css`.** Copy **Block B** (shared CSS primitives) verbatim into the file's top section: `prefers-reduced-motion` guard, `.reveal`, `.zoom-card`. Replace the palette `:root` CSS variables with restaurant tokens (`--bg: #faf6ef; --text: #2a1f17; --accent: #c46a4f; --serif: "Playfair Display"; --sans: "Inter";`). Skip `.marquee`, `.gradient-text`, `.cursor-dot`, `.sticky-label` (not used here). Add restaurant-specific keyframes for the chef-portrait reveal if desired.

- [ ] **Step 3: Write `src/components/restaurantComponents.js`.**

```js
import { parallax } from "./parallax.js";

document.addEventListener("alpine:init", () => {
  Alpine.data("restaurant", () => ({
    mobileMenu: false,
    activeMenu: "brunch",
    init() { parallax(document.getElementById("hero-img")); },
    submitReservation() {
      this.$dispatch("toast", { msg: "Reservation request received — we'll confirm by email within 24 hours.", kind: "success" });
    },
  }));
});
```

```js
// template_apps/restaurant/src/components/parallax.js
// Reused in real-estate template. rAF-throttled for performance.
export const parallax = (el) => {
  if (!el) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let raf = null;
  const update = () => {
    el.style.transform = `translateY(${window.scrollY * 0.4}px)`;
    raf = null;
  };
  window.addEventListener("scroll", () => {
    if (raf) return;
    raf = requestAnimationFrame(update);
  }, { passive: true });
};
```

- [ ] **Step 4: Write `src/main.js`** — copy **Block A** (shared `src/main.js` skeleton) verbatim, importing `./components/restaurantComponents.js`. Skip the `.count-up` branch in the IntersectionObserver callback (restaurant doesn't use count-up).

- [ ] **Step 5: Write `index.html`.** Implementer follows agency pattern. Per-section content:
  - **nav**: sticky, logo wordmark + Menu/About/Reservations/Visit anchor links
  - **hero**: `id="hero-img"` on the hero image so `parallax()` finds it. Restaurant name + tagline + "Reserve" CTA
  - **story**: 2-paragraph chef bio + chef portrait on the right (use the `photo-1577219491135-…` ID)
  - **menu**: Alpine `x-data` tabs (`activeMenu` = brunch/lunch/dinner/drinks). Each tab is a 2-col grid of food cards (image, name, 1-line description, price). Realistic Italian/American/seasonal items.
  - **gallery**: 8-image masonry grid (CSS `column-count: 4`)
  - **hours**: 2-col layout — left has Mon–Sun hours table, right has gradient block placeholder for map with a centered pin SVG
  - **reservation**: form with date / time / party size / name / email. `@submit.prevent="submitReservation()"`
  - **footer**: address, phone, social

- [ ] **Step 6: Run tests + visual check.**

```bash
python -m pytest tests/test_template_apps_static.py -v -k restaurant
```

- [ ] **Step 7: Commit.**

```bash
git add mcp-servers/tasks/template_apps/restaurant/
git commit -m "feat(templates): scaffold restaurant template — atmospheric cafe site"
```

---

### Task 5: Scaffold the **photography** template

**Files:**
- Create: `mcp-servers/tasks/template_apps/photography/{index.html, styles/main.css, src/main.js, src/components/photographyComponents.js, README.md, public/.gitkeep}`

**Goal:** Image-led photographer portfolio with masonry gallery + lightbox.

**Sections:** nav · hero · series · gallery · about · contact · footer

**Design intent:** pure black bg, white text, no accent color, Inter for everything, wide letter-spacing.

**Animations:** `.reveal` scroll-fade, hero scroll-down pulse keyframe, `.zoom-card` hover, Alpine lightbox.

**Pinned Unsplash photo IDs:** 18 photos total — hero (1), series collages (3 × 3 = 9), gallery (15 — but reuse some across series), portrait (1). Pick distinctive travel/landscape/portrait photos. The implementer should select photos with strong visual variety (cool/warm, vertical/horizontal) and document the IDs in the README.

- [ ] **Step 1: Set up directory structure.**

- [ ] **Step 2: Write `styles/main.css`** — shared primitives, palette tokens (`--bg: #000`, `--text: #fff`, no accent). Add hero scroll-down pulse:

```css
@keyframes pulse-down {
  0%, 100% { transform: translateY(0); opacity: 0.6; }
  50%      { transform: translateY(8px); opacity: 1; }
}
.scroll-indicator { animation: pulse-down 2s ease-in-out infinite; }

/* Lightbox overlay */
.lightbox-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.95);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.lightbox-overlay img { max-width: 95vw; max-height: 95vh; }
```

- [ ] **Step 3: Write `src/components/photographyComponents.js`** — paste **Block D** (lightbox factory) verbatim, then register `Alpine.data("photography", ...)` combining lightbox state with mobile-menu state. Register `Alpine.data("lightbox", lightbox)` so it's available globally.

- [ ] **Step 4: Write `src/main.js`** — copy **Block A** verbatim, importing `./components/photographyComponents.js`. Skip the `.count-up` branch (photography doesn't use count-up).

- [ ] **Step 5: Write `index.html`.**
  - **nav**: floating, photographer name + Work/Series/About/Contact
  - **hero**: full-screen Unsplash image, name overlaid bottom-left in display sans, pulsing scroll indicator centered bottom
  - **series**: 3 series sections, each a 3-image collage + title + 1-paragraph description
  - **gallery**: masonry of 12–15 images, all `data-img-slot="gallery"` and `@click="show($el.dataset.idx)"` triggering the lightbox component
  - **about**: portrait + 2-paragraph bio + selected clients list
  - **contact**: email + Instagram link, minimal
  - **footer**

- [ ] **Step 6: Run tests + visual check.**

- [ ] **Step 7: Commit.**

```bash
git commit -m "feat(templates): scaffold photography template — image-led portfolio"
```

---

### Task 6: Scaffold the **event** template

**Files:**
- Create: `mcp-servers/tasks/template_apps/event/{index.html, styles/main.css, src/main.js, src/components/eventComponents.js, README.md, public/.gitkeep}`

**Goal:** Bold conference/festival landing page with live countdown, speaker grid, schedule tabs, FAQ accordion.

**Sections:** nav · hero · stats · speakers · schedule · sponsors · venue · tickets · faq · footer

**Design intent:** deep navy `#0a1230` bg, neon cyan `#22d3ee` accent, Space Grotesk for everything.

**Animations:** live countdown (1Hz, "Event in progress" when elapsed), count-up stats, speaker hover-bio reveal (Alpine `x-transition`), schedule tab transitions, `.reveal`, sponsor strip subtle scroll.

**Pinned Unsplash photo IDs:** 12 speaker portraits + 3 venue photos. Pick diverse-looking professional headshots (different demographics, ages, attires).

- [ ] **Step 1–4:** Set up structure. Copy **Block B** (shared CSS primitives) into `styles/main.css` and add event-specific palette tokens + FAQ accordion styles. Components: copy **Block C** (count-up factory) into `src/components/countUp.js`, plus the new `countdown` factory shown below in Step 4. `src/main.js` is **Block A** verbatim (with the `.count-up` branch active).

```js
// template_apps/event/src/components/eventComponents.js
import { countUp } from "./countUp.js";

document.addEventListener("alpine:init", () => {
  Alpine.data("event", () => ({
    mobileMenu: false,
    activeDay: 1,
    openFaq: null,
    init() {
      // Countdown is registered as a separate Alpine.data() below.
    },
  }));

  Alpine.data("countdown", (targetIso) => ({
    target: new Date(targetIso).getTime(),
    now: Date.now(),
    timer: null,
    init() {
      if (this.now >= this.target) return; // already elapsed
      this.timer = setInterval(() => { this.now = Date.now(); }, 1000);
    },
    destroy() { if (this.timer) clearInterval(this.timer); },
    get elapsed() { return this.now >= this.target; },
    get diff() {
      const d = Math.max(0, this.target - this.now);
      return {
        days:    Math.floor(d / 86_400_000),
        hours:   Math.floor((d % 86_400_000) / 3_600_000),
        minutes: Math.floor((d % 3_600_000) / 60_000),
        seconds: Math.floor((d % 60_000) / 1_000),
      };
    },
  }));

  Alpine.data("countUp", countUp);
});
```

- [ ] **Step 5: Write `index.html`.**
  - **hero**: `<div x-data="countdown('2026-09-12T09:00:00Z')">` wraps the countdown UI. When `elapsed`, show "Event in progress"; otherwise show 4 stat boxes (days, hours, mins, secs).
  - **speakers**: 12 cards, each with photo + name + title + company. Hover (or focus) shows Alpine `x-transition` revealed bio paragraph.
  - **schedule**: 2-tab interface (`activeDay = 1 | 2`). Each tab is a vertical timeline of sessions with time + title + speaker.
  - **sponsors**: 3 tier headings (Platinum / Gold / Silver) with placeholder logos.
  - **tickets**: 3 tier cards with price + perks list + CTA.
  - **faq**: 6 questions. Each `<button @click="openFaq = openFaq === i ? null : i">`. Body has `<div x-show="openFaq === i" x-transition>`.

- [ ] **Step 6: Run tests + visual check.** Verify countdown decrements every second.

- [ ] **Step 7: Commit.**

```bash
git commit -m "feat(templates): scaffold event template — conference / festival landing"
```

---

### Task 7: Scaffold the **real-estate** template

**Files:**
- Create: `mcp-servers/tasks/template_apps/real-estate/{index.html, styles/main.css, src/main.js, src/components/realEstateComponents.js, README.md, public/.gitkeep}`

**Goal:** Editorial property listing with image carousel, animated stats, gallery lightbox, agent profile.

**Sections:** nav · hero · stats · description · gallery · map · more-listings · agent · footer

**Design intent:** cream `#faf7f2` bg, slate `#1f2937` text, warm gold `#b08a3e` accent, Cormorant Garamond display + Inter body.

**Animations:** hero carousel (timer + manual + dots), count-up stats, gallery lightbox (shared component with photography), `.reveal`, parallax on hero (rAF-throttled).

**Pinned Unsplash photo IDs:** 5 hero carousel + 9 gallery + 1 agent + 3 "more listings" thumbs + 1 neighborhood. Pick architectural/interior shots — Victorian houses, modern interiors, kitchens.

- [ ] **Step 1–4:** Set up structure. **CSS:** Block B verbatim + real-estate palette tokens. **Components:** copy `lightbox` (Block D) and `countUp` (Block C) into `src/components/`, plus the new `carousel` factory shown below. `src/main.js` is Block A verbatim (with `.count-up` branch active).

```js
// template_apps/real-estate/src/components/carousel.js
export const carousel = (count) => ({
  i: 0, count, timer: null,
  init() {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    this.timer = setInterval(() => { this.i = (this.i + 1) % this.count; }, 5000);
  },
  destroy() { if (this.timer) clearInterval(this.timer); },
  go(idx) {
    this.i = idx;
    if (this.timer) { clearInterval(this.timer); this.init(); } // restart
  },
  prev() { this.go((this.i - 1 + this.count) % this.count); },
  next() { this.go((this.i + 1) % this.count); },
});
```

- [ ] **Step 5: Write `index.html`.**
  - **hero**: `<div x-data="carousel(5)">` wraps 5 stacked images with `x-show="i === N"` + `x-transition`. Address overlay + price tag.
  - **stats**: 4 count-up cards (beds: 3, baths: 2, sqft: 1840, price: 1200000) — for price, format with $ and commas in the x-text expression.
  - **description**: 2 paragraphs + amenities checklist (8–12 items: hardwood floors, gas range, etc.).
  - **gallery**: 9 images in masonry, click → lightbox (reuse Block D).
  - **map**: gradient block w/ pin SVG + 2-paragraph neighborhood blurb.
  - **more-listings**: 3 smaller cards.
  - **agent**: agent photo + bio + phone + email + viewing-request form.

- [ ] **Step 6: Run tests + visual check.** Verify carousel auto-advances and stops on hover.

- [ ] **Step 7: Commit.**

```bash
git commit -m "feat(templates): scaffold real-estate template — property listing page"
```

---

### Task 8: Animation positive-path test (catches count-up regressions)

**Files:**
- Create: `mcp-servers/tasks/tests/test_template_apps_animations.py`

**Goal:** Verify that count-up animations actually run (not just disabled by reduced-motion). Spec: positive-path Playwright assertion on the agency stats strip.

- [ ] **Step 1: Install Playwright if not already.** Use the existing project Playwright setup (yesterday's screenshot script proves it's installed).

- [ ] **Step 2: Write the failing test.**

```python
# mcp-servers/tasks/tests/test_template_apps_animations.py
"""Positive-path animation test — verifies count-up actually fires.

This complements the reduced-motion test in test_template_apps_static.py
(which verifies animations are SKIPPED under reduced-motion). Without
this, count-up bugs that prevent the animation from completing would
go undetected.
"""
import pytest

playwright = pytest.importorskip("playwright.sync_api")


def test_agency_stats_count_up_completes(tmp_path):
    """Load agency/index.html, scroll the stats strip into view, wait 2 s,
    confirm the rendered numbers equal their target values."""
    from playwright.sync_api import sync_playwright
    from pathlib import Path

    index = Path(__file__).resolve().parents[1] / "template_apps" / "agency" / "index.html"
    url = index.as_uri()

    expected = {"12": True, "247": True, "89": True, "34": True}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.goto(url)
        # Scroll stats into view, wait for count-up to settle.
        page.evaluate("document.querySelector('[data-section=\"stats\"]').scrollIntoView()")
        page.wait_for_timeout(2200)
        # Read the rendered stat numbers.
        rendered = page.evaluate("""
          Array.from(document.querySelectorAll('[data-section="stats"] [x-text="n"]'))
            .map(el => el.textContent.trim())
        """)
        browser.close()

    for v in expected:
        assert v in rendered, f"expected count-up to render {v}, got {rendered}"
```

- [ ] **Step 3: Run.**

```bash
cd mcp-servers/tasks
python -m pytest tests/test_template_apps_animations.py -v
```

Expected: PASS (since Task 3 already shipped a working agency template). If it fails, the count-up wiring is broken — debug and fix before continuing.

- [ ] **Step 4: Commit.**

```bash
git add mcp-servers/tasks/tests/test_template_apps_animations.py
git commit -m "test(templates): positive-path count-up animation check"
```

---

### Task 9: Capture preview screenshots, bump PREVIEW_VER

**Files:**
- Modify: `_tplpng/screenshot-templates.js` (append 5 new keys)
- Create: `mcp-servers/tasks/template_apps/<key>/preview.png` × 5
- Modify: `mcp-servers/tasks/static/templates.html` (bump `PREVIEW_VER`)

**Goal:** Replace the gradient SVG-mockup fallback with real 1280×800 screenshots. Bump `PREVIEW_VER` to `"3"` to bust Cloudflare cache.

**Important — `<%= APP_NAME %>` placeholder substitution:** The template `index.html` files use `<%= APP_NAME %>` placeholders that get substituted at build time, but the screenshot pipeline loads them via `https://ai-ui.coolestdomain.win/api/template-preview/<key>/index.html`. Inspect the existing `_tplpng/screenshot-templates.js` (yesterday's file) to confirm whether the `template-preview` route does the substitution server-side, or whether the captured PNG would show literal `<%= APP_NAME %>` strings. If the latter, the script must inject a fake APP_NAME via `page.evaluate()` before screenshotting, OR the implementer should hand-replace `<%= APP_NAME %>` with a per-template demo name (e.g. "Halftone" for agency, "La Maison" for restaurant) directly in the index.html before capture. The existing landing/portfolio screenshots from yesterday prove the path works — examine them to see how the placeholders look in practice.

- [ ] **Step 1: Update `_tplpng/screenshot-templates.js`.**

```js
const TEMPLATES = ['landing', 'portfolio', 'crud', 'dashboard', 'invoice',
                   'agency', 'restaurant', 'photography', 'event', 'real-estate'];
```

- [ ] **Step 2: Run Playwright locally to capture screenshots.**

```powershell
cd "C:\Users\alama\Desktop\Lukas Work\IO\_tplpng"
node screenshot-templates.js
```

Expected: 10 PNG files in `_tplpng/`, each 1280×800, ~25–80 KB. The 5 new keys produce new files; the existing 5 may or may not be regenerated (no harm if they are).

- [ ] **Step 3: Copy the 5 new PNGs into the template_apps folders.**

```powershell
Copy-Item "_tplpng/new-agency.png" "mcp-servers/tasks/template_apps/agency/preview.png"
Copy-Item "_tplpng/new-restaurant.png" "mcp-servers/tasks/template_apps/restaurant/preview.png"
Copy-Item "_tplpng/new-photography.png" "mcp-servers/tasks/template_apps/photography/preview.png"
Copy-Item "_tplpng/new-event.png" "mcp-servers/tasks/template_apps/event/preview.png"
Copy-Item "_tplpng/new-real-estate.png" "mcp-servers/tasks/template_apps/real-estate/preview.png"
```

(Adjust filenames if `screenshot-templates.js` writes them differently — its current pattern is `new-<key>.png`.)

- [ ] **Step 4: Bump `PREVIEW_VER` in `templates.html` from `"2"` to `"3"`.**

```bash
# Find the existing constant (Task 9 from yesterday's work added it)
grep -n 'PREVIEW_VER' mcp-servers/tasks/static/templates.html
```

Edit:
```js
const PREVIEW_VER = "3";
```

- [ ] **Step 5: Commit (atomic with the artifacts it invalidates).**

```bash
git add _tplpng/screenshot-templates.js \
        mcp-servers/tasks/template_apps/agency/preview.png \
        mcp-servers/tasks/template_apps/restaurant/preview.png \
        mcp-servers/tasks/template_apps/photography/preview.png \
        mcp-servers/tasks/template_apps/event/preview.png \
        mcp-servers/tasks/template_apps/real-estate/preview.png \
        mcp-servers/tasks/static/templates.html
git commit -m "chore(templates): capture preview screenshots + bump PREVIEW_VER to 3"
```

---

### Task 10: Deploy to Hetzner and verify production

**Files:** All files modified/created in Tasks 1–9.

**Goal:** Templates live on production, gallery shows 10 featured cards.

- [ ] **Step 1: Push files to Hetzner via SCP.**

```powershell
# Templates folders (5 new directories)
foreach ($key in 'agency','restaurant','photography','event','real-estate') {
  scp -r "mcp-servers/tasks/template_apps/$key" `
      "root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/"
}

# Modified Python + frontend + tests
scp "mcp-servers/tasks/templates.py" `
    "mcp-servers/tasks/static/templates.html" `
    "mcp-servers/tasks/tests/test_templates.py" `
    "mcp-servers/tasks/tests/test_template_apps_static.py" `
    "mcp-servers/tasks/tests/test_template_apps_animations.py" `
    "root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/"
```

- [ ] **Step 2: Rebuild the tasks service.**

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --build --no-deps tasks"
```

Expected: build takes ~1m 30s, container restarts cleanly.

- [ ] **Step 3: Verify the API.**

```bash
ssh root@46.224.193.25 "curl -s http://localhost:8210/api/templates -H 'X-User-Email: alamajacintg04@gmail.com' -H 'X-User-Admin: true' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d), \"templates\"); print(sorted({t[\"key\"] for t in d}))'"
```

Expected: `24 templates` and the key list includes `agency`, `restaurant`, `photography`, `event`, `real-estate`.

- [ ] **Step 4: Verify a preview PNG serves.**

```bash
curl -I https://ai-ui.coolestdomain.win/api/template-preview/agency/preview.png
```

Expected: `HTTP/2 200`, `content-type: image/png`, `content-length` ≈ 25–80KB.

- [ ] **Step 5: Hard-refresh the gallery in a browser.**

Open `https://ai-ui.coolestdomain.win/tasks/static/templates.html` with Ctrl+Shift+R. Verify:
- 10 featured-tier cards now show (was 5)
- Each new card displays its real screenshot, role tag, and 3 feature bullets
- No console errors, no 404s on preview URLs

- [ ] **Step 6: Build a test project from each new template.**

In the App Builder UI, create one project per new template using the placeholder text as the prompt. Verify each builds and renders correctly. (This is a smoke test — don't build all 5 if time-constrained; just `agency` is enough to prove the path.)

- [ ] **Step 7: Mark task #87 complete and notify.**

---

## Rollback plan

If anything breaks production:

```bash
ssh root@46.224.193.25 "cd /root/proxy-server && git -C /root/proxy-server checkout HEAD~N -- mcp-servers/tasks/templates.py mcp-servers/tasks/static/templates.html && docker compose -f docker-compose.unified.yml up -d --build --no-deps tasks"
```

(Server has no git checkout; the rollback path is to SCP the prior `templates.py` and `templates.html` from a safe local commit and rebuild.)

The templates added by this PR are PURE additions — removing them from `TEMPLATES` removes them from the gallery instantly. The `template_apps/<key>/` folders being absent doesn't break anything; they're only referenced via `_has_template_app(key)` which returns False gracefully.

---

## Open questions / TBD during implementation

- Exact Unsplash photo IDs per template (provenance comment in each README)
- Lucide icon names for capability cards in agency template (use the icon set from `landing/index.html`)
- Whether to ship the 8 client wordmarks in agency as styled `<span>` (recommended, no trademark risk) or as inline SVG marks

## Naming note

The template key `real-estate` (with hyphen) maps to Python constants `_RULES_REAL_ESTATE` and `_SVG_REAL_ESTATE` (Python identifiers can't contain hyphens, so the underscore is intentional). Same for the directory `template_apps/real-estate/` (filesystem-friendly hyphen).
