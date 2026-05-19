# App Builder — Design-Forward Templates (5 new) — Spec

**Date:** 2026-05-08
**Status:** Draft for review
**Owner:** alamajacintg04@gmail.com
**Scope:** Add 5 new fully-scaffolded "design-forward" templates to the App Builder gallery.

## Problem

The App Builder gallery has 5 fully-scaffolded templates today (`landing`, `portfolio`, `crud`, `dashboard`, `invoice`) and 14 rules-only placeholder keys (`crm`, `docs`, `ecommerce`, `booking`, `chat`, `auth`, `blog`, `project-tracker`, `ai-chatbot`, `expense-tracker`, `form-builder`, `social-feed`, `blank`, `custom`). The 5 scaffolded ones skew utility/business — there is no template that is genuinely *image-led, animation-rich, design-forward*. Users picking from the gallery to build a brochure-style site (agency, restaurant, photography, event, real estate) currently start from `landing` or `blank` and hand-build the visual treatment.

This spec adds 5 new design-forward templates with built-in animations and image placement, so a user can pick one and get a polished, finished-looking site that the agent can then re-skin for their specific business.

## Goals

- Add 5 new fully-scaffolded templates: `agency`, `restaurant`, `photography`, `event`, `real-estate`.
- Each ships with substantive, finished-looking demo content (no Lorem ipsum, no TODOs).
- Each ships with a coherent animation vocabulary that respects `prefers-reduced-motion`.
- Each uses image URLs from the existing whitelist (`images.unsplash.com` + `picsum.photos`) — no bundled image assets.
- Each surfaces in the gallery as a "featured" tier card (preview PNG + feature bullets + role tag) on first deploy.
- Each is `storage="none"` (no Supabase) so builds are simple and deterministic.
- Build flow uses the existing static-template path (FastAPI tasks → Caddy → browser).

## Non-goals

- Stripe / actual payment links on event tickets and real-estate viewings (forms simulate-submit).
- Real Supabase RSVP / listing tables (covered by Q5: A — all static).
- Custom domains per template (separate feature, already exists).
- i18n / multi-language variants.
- Themed sub-variants of each template (3 in the gallery is enough; bloats UX otherwise).
- Deprecating any of the existing 14 unfeatured rules-only templates (separate workstream).
- Adding any new third-party JS library (no GSAP, Motion One, AOS, etc.) — animations stay inside the existing baseline.

## Architecture

The system already has a working scaffolded-template flow — this spec adds new instances, not new mechanisms. No changes to `templates.html` UI code, the `/api/templates` endpoint, the `template-preview` route, or the build executor.

```
┌─────────────────────────────────────────────────────────┐
│  templates.py (canonical TEMPLATES list)                │
│  • +5 Template(...) entries (key, label, role_tag,      │
│    feature_bullets, svg_mockup, rules)                  │
│  • +5 _RULES_<KEY> constants                            │
│  • +5 _SVG_<KEY> constants                              │
└────────────────┬────────────────────────────────────────┘
                 │ on import
                 ▼
┌─────────────────────────────────────────────────────────┐
│  GET /api/templates  →  serializes TEMPLATES list       │
│  templates.html      →  renders gallery cards           │
│                         (featured tier = has bullets    │
│                          AND has preview.png OR mockup) │
└────────────────┬────────────────────────────────────────┘
                 │ user picks <key>
                 ▼
┌─────────────────────────────────────────────────────────┐
│  Build executor copies template_apps/<key>/* into       │
│  apps/<slug>/* and applies user description as the      │
│  customization layer via _RULES_<KEY>.                  │
└─────────────────────────────────────────────────────────┘
```

**Mental model:** templates are pure data + static files. The 5 new templates plug into the existing pipeline at exactly two points — the `TEMPLATES` list in `templates.py` and the `template_apps/<key>/` folder on disk. Everything downstream (gallery render, build, preview, deploy) already works.

## Per-template file layout

Identical to `landing/` and `portfolio/`:

```
mcp-servers/tasks/template_apps/<key>/
  index.html          # 200–500 lines, semantic HTML5, Alpine-attributed
                      # (event + real-estate run longer due to section count)
  styles/main.css     # template-specific keyframes, palette tokens, custom CSS
  src/main.js         # Alpine.start() + IntersectionObserver scroll-reveal
  src/components/*.js # Alpine x-data components, one per major section
  public/             # empty (favicon optional; images come from Unsplash)
  README.md           # 1-paragraph description
  preview.png         # 1280×800 Playwright screenshot, ~25–80 KB
```

## The 5 templates

### 1. Agency *(`agency`, 🪐, "Studio site")*

**Identity:** Bold, dark-by-default studio site. Charcoal `#0a0a0b` background, off-white text, lime-electric accent (`#c1ff00`). Inter for body, Space Grotesk for display.

**Feature bullets** (gallery card):
- "Bold scroll-driven hero with marquee work strip"
- "Case-study grid with hover image reveals"
- "Animated client logo carousel + sticky section labels"

**Sections (in order):**

| # | Section          | Notes                                                                                              |
|---|------------------|----------------------------------------------------------------------------------------------------|
| 1 | Sticky nav       | Logo + 4 anchor links + "Let's talk" CTA. Becomes solid + shadow on scroll past hero.              |
| 2 | Hero             | Full-bleed Unsplash image. Massive headline w/ animated gradient text. Mouse-follow accent dot.    |
| 3 | Services marquee | Infinite-scroll strip: "Brand · Web · Motion · Strategy ·" (CSS keyframes, doubled list).          |
| 4 | Selected work    | 6 case-study cards in a 2-col grid. Hover zooms image (`.zoom-card`) and reveals tags.             |
| 5 | Stats strip      | 4 count-up numbers (Years, Projects, Clients, Awards) triggered by `IntersectionObserver`.         |
| 6 | Capability cards | 4 cards (Strategy / Brand / Web / Content) w/ icon, heading, paragraph.                            |
| 7 | Logo strip       | 8–10 client SVG marks (decorative wordmarks).                                                       |
| 8 | Testimonial      | One large pull-quote, client photo + name + role.                                                   |
| 9 | Contact CTA      | Full-bleed "Let's work together" + email link + simulated contact form.                            |
| 10| Footer           | Minimal: copyright, social links.                                                                   |

**Animation highlights:** mouse-follow accent dot (rAF-throttled), animated gradient hero headline, marquee infinite scroll, hover image zoom on cards, count-up stats, sticky section labels.

---

### 2. Restaurant *(`restaurant`, 🍽️, "Restaurant / cafe")*

**Identity:** Warm and atmospheric. Cream `#faf6ef` bg, espresso text (`#2a1f17`), terracotta accent (`#c46a4f`). Playfair Display for headings, Inter for body.

**Feature bullets:**
- "Parallax food-photography hero"
- "Tabbed menu with image cards + prices"
- "Hours, map placeholder, and reservation form"

**Sections:** sticky nav → parallax hero w/ restaurant name + Reserve CTA → 2-paragraph story w/ chef portrait → tabbed menu (Brunch/Lunch/Dinner/Drinks) w/ food cards → 8-image masonry photo strip → hours table + map placeholder (gradient block w/ pin) → reservation form (simulated submit) → footer.

**Animation highlights:** parallax hero (scrollY × 0.4 on transform), Alpine `x-show` menu tab transitions, hover zoom on food cards, scroll-reveal section fades.

---

### 3. Photography *(`photography`, 📸, "Photographer site")*

**Identity:** Pure black bg, white text, no accent color, wide letter-spacing — image-led, minimal chrome. Inter for everything.

**Feature bullets:**
- "Full-bleed image gallery with masonry layout"
- "Lightbox overlay with keyboard navigation"
- "Scroll-triggered fades, minimal chrome"

**Sections:** floating nav → full-screen hero w/ photographer name + pulsing scroll indicator → 3 featured series w/ 3-image collages each → 12–15 image masonry grid (click → lightbox) → about section w/ portrait + bio + selected clients list → minimal contact (email + Instagram) → footer.

**Animation highlights:** scroll-fade on every section, hero scroll-down indicator pulse animation, image hover zoom on grid, full-featured Alpine lightbox (arrow keys, Escape, backdrop click).

---

### 4. Event *(`event`, 🎤, "Conference / festival")*

**Identity:** Deep navy bg (`#0a1230`), neon cyan accent (`#22d3ee`), Space Grotesk for everything. Bold and modern.

**Feature bullets:**
- "Live countdown to event date"
- "Speaker grid with photos + hover bio"
- "Agenda timeline, sponsor tiers, and FAQ accordion"

**Sections:** sticky nav → bold hero w/ event name + dates + live countdown + Buy CTA → 3 stat cards (talks/speakers/attendees) → 12-speaker grid w/ hover-reveal bio → Day 1 / Day 2 schedule tabs w/ session timeline → tiered sponsor logo grid (Platinum/Gold/Silver) → venue (address + map placeholder + photos) → 3 ticket-tier cards → FAQ accordion (Alpine `x-show`) → footer.

**Animation highlights:** live countdown (`setInterval` on Alpine state, 1 Hz), speaker card hover bio reveal (Alpine `x-transition`), schedule tab transitions, sponsor strip subtle scroll, scroll-fade.

---

### 5. Real estate *(`real-estate`, 🏡, "Property listing")*

**Identity:** Cream bg (`#faf7f2`), slate text (`#1f2937`), warm gold accent (`#b08a3e`). Cormorant Garamond for headings, Inter for body. Editorial feel.

**Feature bullets:**
- "Property image carousel with auto-advance + lightbox"
- "Animated stat counters (beds, baths, sqft, price)"
- "Map placeholder, agent profile, and viewing-request form"

**Sections:** nav → hero w/ image carousel (3–5 images, auto-advance + manual) + address overlay + price tag → animated stats strip (beds/baths/sqft/lot) → 2-paragraph description + amenities checklist → 9-image gallery w/ lightbox → map placeholder + neighborhood blurb → "more from agent" 3-card row → agent profile w/ schedule-a-viewing form → footer.

**Animation highlights:** hero carousel (Alpine `x-data` with timer + manual prev/next), count-up stats, gallery lightbox shared with photography template, scroll-fade.

---

## Animation primitives

A small toolkit reused across all 5 templates. Every primitive is implementable in vanilla CSS + Alpine.js + `IntersectionObserver` with no extra library.

| # | Primitive            | Where used                                         | Implementation                                                                                                                                  |
|---|----------------------|----------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------|
| 1 | `.reveal` scroll-fade| All 5                                              | Element starts `opacity:0; translateY(20px)`. `IntersectionObserver` (one per page, threshold 0.2) adds `.is-visible` → CSS transitions in. One-shot. |
| 2 | Hover image zoom     | Agency, restaurant, real-estate                    | `.zoom-card img { transition: transform 600ms }` + `:hover { transform: scale(1.05) }`. Pure CSS.                                                |
| 3 | Count-up numbers     | Agency, event, real-estate                         | Alpine `x-data="{ n: 0, target: N }"` + `requestAnimationFrame` tween from 0 → target, kicked off by `IntersectionObserver`.                     |
| 4 | Marquee infinite scroll | Agency (services), event (sponsors)             | `@keyframes marquee` translating `0 → -50%` on a doubled child list. Pure CSS.                                                                  |
| 5 | Lightbox             | Photography, real-estate                           | Alpine `x-data="{ open: false, src: '', idx: 0 }"` overlay. Backdrop click + Escape + arrow keys.                                               |
| 6 | Live countdown       | Event hero only                                    | Alpine `x-data="{ now: Date.now(), target: <ms> }"` + `setInterval(() => now = Date.now(), 1000)`. When `now >= target`, displays "Event in progress" instead of `00:00:00:00`. |
| 7 | Mouse-follow accent  | Agency hero only                                   | Fixed `<div>`, `mousemove` listener updates `transform: translate(x,y)`, throttled with `rAF`.                                                  |
| 8 | Parallax hero        | Restaurant, real-estate                            | `transform: translateY(scrollY * 0.4)` on hero image, `rAF`-throttled.                                                                          |
| 9 | Sticky section labels| Agency only                                        | `position: sticky; top: 80px` on section heading. Pure CSS.                                                                                     |
| 10| Alpine `x-transition`| Menus, FAQs, schedule tabs, lightbox open/close    | Built into Alpine. No new code.                                                                                                                 |

**Performance budget per template:**
- ≤3 active scroll listeners (all `rAF`-throttled).
- ≤1 `setInterval` (countdown only — event template).
- All animations respect `prefers-reduced-motion: reduce` via a top-of-CSS media query that disables transitions/animations and a top-of-JS guard that exits scroll/parallax listeners early.

## Image conventions

| Slot                | URL pattern                                                                                          |
|---------------------|------------------------------------------------------------------------------------------------------|
| Hero (1600w)        | `images.unsplash.com/photo-<id>?auto=format&fit=crop&w=1600&q=80`                                    |
| Gallery thumbs      | `images.unsplash.com/photo-<id>?auto=format&fit=crop&w=600&q=80`                                     |
| Avatars / faces     | `images.unsplash.com/photo-<id>?auto=format&fit=crop&w=200&q=80&crop=faces`                          |
| Filler / decorative | `picsum.photos/seed/<word>/600/400`                                                                  |

**Rules** every `<img>` follows:
- `loading="lazy"` (except the hero, which is `loading="eager" fetchpriority="high"`).
- `width` and `height` attributes set explicitly to prevent layout shift (CLS).
- Meaningful `alt` text — never empty, never "image".
- `data-img-slot="hero|grid|avatar|gallery|decoration"` so the agent's customization rules can find/replace them by slot type.

**Specific Unsplash photo IDs are pinned per template** (NOT random) so the curated demo screenshots are reproducible and the gallery preview never goes stale. The implementation plan must capture the chosen photo-ID list per template as a deliverable artifact (e.g. a comment block at the top of each `index.html` or in the per-template README) so a later contributor can refresh expired URLs without guessing.

## `_RULES_<KEY>` shape

Each template's rules string follows the same skeleton (~25–40 lines), passed to the agent via `/api/templates` so it can customize the template per the user's prompt without breaking the animation system:

```
SECTIONS PRESENT:    <ordered list with anchor IDs>
DO NOT REMOVE:       <e.g. "the IntersectionObserver in src/main.js",
                          "the Alpine lightbox component",
                          "the prefers-reduced-motion CSS guard">
SAFE TO CUSTOMIZE:   copy, image URLs (must stay on whitelist),
                     palette CSS variables, restaurant/agency name,
                     service offerings, speaker list, listings, etc.
ANIMATIONS PRESENT:  list of animation classes/components
                     (.reveal, .zoom-card, .marquee, x-data="lightbox", etc.)
PALETTE TOKENS:      list of CSS custom properties
                     (--bg, --surface, --text, --accent, --serif, --sans)
IMAGE SLOTS:         data-img-slot inventory + sizes
TYPOGRAPHY:          Google Fonts links + how to swap
```

This lets the agent reskin a template without breaking animations — palette is in CSS variables, so swapping `--accent` re-themes everything.

## `templates.py` changes

Per template, three additions to the file:

1. **A new `_RULES_<KEY>` string constant** (~30 lines).
2. **A new `_SVG_<KEY>` string constant** — small inline SVG mockup shown on the gallery card before `preview.png` loads or if it 404s. ~15–25 lines.
3. **A new `Template(...)` entry** appended to the `TEMPLATES` list with `key`, `label`, `emoji`, `description`, `placeholder`, `rules=_RULES_<KEY>`, `role_tag`, `feature_bullets=(3 strings)`, `svg_mockup=_SVG_<KEY>`, `storage="none"`.

No changes to `Template` dataclass, `get_template()`, `_BASE_RULES`, `_GENERATION_LAYOUT`, or storage helpers.

## Frontend changes

**Only one:** bump `PREVIEW_VER` in `mcp-servers/tasks/static/templates.html` from `"2"` to `"3"`. This invalidates Cloudflare's edge cache on the existing 5 preview PNGs (a no-op since they're unchanged) and ensures the 5 new ones are loaded fresh. Zero other UI changes.

## Backend changes

None. The `/api/templates` endpoint serializes `TEMPLATES` directly, so the new keys appear automatically once `templates.py` is updated. The `/api/template-preview/<key>/preview.png` route serves any file in `template_apps/<key>/` already.

## Testing & verification

### Pre-merge per-template checks

For each of the 5 new templates:

1. **Static HTML validity** — `index.html` parses as valid HTML5, one `<h1>`, `alt` on every `<img>`, no unclosed tags.
2. **Content fill audit** — `_BASE_RULES` "no Lorem ipsum / TODO / placeholder" rule applies. Manual review.
3. **CDN whitelist** — no scripts/styles outside `cdn.tailwindcss.com`, `fonts.googleapis.com`, `cdn.jsdelivr.net`, `unpkg.com`. Images only from `images.unsplash.com`, `picsum.photos`.
4. **Mobile from 320 px up** — Playwright iPhone-13 viewport screenshot, no horizontal scroll, nav collapses.
5. **`prefers-reduced-motion`** — Playwright with `reducedMotion: 'reduce'` confirms no transitions and no scroll-jacking.
6. **Animations actually fire by default** — at least one Playwright positive-path assertion: load the agency template, scroll the stats strip into view, wait 2 s, assert the rendered stat number equals its target value (catches count-up regressions, since reduced-motion-only tests can mask broken animations).
7. **Console clean** — no JS errors, no 404s.

### Existing test suite touchpoints

- **`tests/test_supabase_inject.py`** — new templates have `storage="none"` so they should NOT trigger Supabase injection. Add 5 parametrized assertions.
- **`tests/test_routes_graph.py`** — verifies `/api/templates` returns the canonical list. Update the expected key list to include the 5 new ones.

### New test file

**`mcp-servers/tasks/tests/test_template_apps_static.py`** — 5 parametrized tests, one per new template:

```python
@pytest.mark.parametrize("key", ["agency", "restaurant", "photography", "event", "real-estate"])
def test_template_app_renders(key):
    # 1. template_apps/<key>/index.html exists and is non-trivial size
    # 2. parses as HTML5
    # 3. contains the expected section markers (per spec table)
    # 4. no Lorem/TODO/Coming-soon placeholders
    # 5. all <img> have alt + loading + width + height
    # 6. only whitelisted CDNs
```

### Preview screenshot pipeline

Reuse `_tplpng/screenshot-templates.js` from yesterday:

1. Add the 5 new keys to the `TEMPLATES` array in the script.
2. Run Playwright headed at 1280×800, `networkidle` + 2 s settle.
3. Save 5 PNGs to `_tplpng/new-<key>.png`.
4. Copy each into `mcp-servers/tasks/template_apps/<key>/preview.png`.
5. Deploy: SCP into Hetzner; rebuild `tasks` (since `templates.py` changed) — the rebuild bakes the PNGs into the image too.

## Rollout

**Branch:** `feat/design-templates` (or land on existing `feat/element-picker` since work-in-flight).

**Commit topology:**
1. `feat: scaffold agency template` — new files under `template_apps/agency/`
2. `feat: scaffold restaurant template`
3. `feat: scaffold photography template`
4. `feat: scaffold event template`
5. `feat: scaffold real-estate template`
6. `feat: register 5 new design templates in templates.py` — `_RULES_*`, `_SVG_*`, `TEMPLATES` entries
7. `test: add static HTML checks for new templates`
8. `chore: capture preview screenshots for new templates` — 5 PNGs + `screenshot-templates.js` update + `PREVIEW_VER` bump in `templates.html` (atomic with the artifacts it invalidates)

**Deploy:**
```
scp -r mcp-servers/tasks/template_apps/{agency,restaurant,photography,event,real-estate} \
       root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/template_apps/
scp mcp-servers/tasks/templates.py \
    mcp-servers/tasks/static/templates.html \
    root@46.224.193.25:/root/proxy-server/mcp-servers/tasks/
ssh root@46.224.193.25 "cd /root/proxy-server && \
    docker compose -f docker-compose.unified.yml up -d --build --no-deps tasks"
```

`--build` is required because Python code changed in `templates.py`. Expected build time: ~1m 30s.

**Post-deploy verification:**
- `curl https://ai-ui.coolestdomain.win/api/templates | jq '.templates | length'` → 24
- `curl https://ai-ui.coolestdomain.win/api/template-preview/agency/index.html | head` → renders
- Gallery hard-refresh → 10 featured templates instead of 5.

## Open questions

None blocking. The Unsplash photo IDs need to be picked during scaffold creation but that's an implementation choice, not a design choice.

## Risks

- **Unsplash photo deletion / hotlink change** — pinned IDs could 404 over time. Mitigation: a follow-up smoke test runs weekly against the gallery preview URLs and pages an alert if any return non-200. Not in scope for v1.
- **Cloudflare edge caching the 5 new preview PNGs as 404s** — if a deploy is interrupted between SCP'ing PNGs and the rebuild finishing, Cloudflare could cache misses. Mitigation: bump `PREVIEW_VER` to `"3"` in `templates.html` (already in the rollout), and verify `?v=3` query string is present on every gallery `<img>` after deploy.
- **Gallery becomes harder to scan at 24 templates** — 10 featured cards plus 14 unfeatured rules-only ones. Out of scope per Q5: A. Follow-up: collapsing-section UI for the unfeatured tier.
- **Animation regression on slow devices** — fixed budget (≤3 scroll listeners, ≤1 interval, all `rAF`-throttled, `prefers-reduced-motion` respected) plus mobile-viewport tests should catch this; if a real device regresses, the JS guard can be tightened to bail on `navigator.deviceMemory < 4`.
