"""Canonical template definitions for the AIUI App Builder.

This is the single source of truth for build templates. The frontend fetches
this list via GET /api/templates and only sends `template_key` when creating
a project — the rules text is looked up server-side, NOT trusted from the
browser. Closes a prompt-injection vector.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    key: str
    label: str
    emoji: str
    description: str
    placeholder: str
    rules: str
    # Either "supabase" (template needs a DB to be useful) or "none"
    # (purely static / localStorage). Used by the chat-driven Supabase
    # connect flow to decide whether to gate the build on a DB link.
    storage: str = "none"
    # Short role tag shown in the gallery banner (e.g. "Auth + CRUD"). Empty
    # string means the gallery falls back to `label`.
    role_tag: str = ""
    # 3 short feature bullets shown on the gallery card body. Surfaces what
    # the template actually delivers so users can pick without guessing.
    # Tuple keeps the dataclass frozen-friendly.
    feature_bullets: tuple[str, ...] = ()
    # Stylized SVG mockup (string) shown as the card visual in the gallery.
    # Hand-crafted preview that depicts the template's layout — bypasses the
    # service-worker / live-iframe issues. Empty string falls back to the
    # gradient placeholder.
    svg_mockup: str = ""

    @property
    def display(self) -> str:
        return f"{self.emoji} {self.label} — {self.description}"


# Strict, always-on tech rules — these apply whether the agent is generating
# from scratch OR customizing a pre-built base app.
_BASE_RULES: str = "\n".join([
    "RULES (strict):",
    "• Tech: static HTML + Tailwind CDN + Alpine.js + vanilla ES modules. No build step (no webpack/rollup/vite). No npm install.",
    "• Semantic HTML5: use <header>, <main>, <section>, <footer>. One <h1> per page.",
    "• Responsive: mobile-first, must work from 320px up. Test header/nav collapse at <768px.",
    "• Accessibility: alt text on all images, labels on form fields, visible focus states, contrast ≥4.5:1 for body text.",
    "• Performance: keep critical CSS small, lazy-load images below the fold.",
    "• Whitelisted CDNs only: cdn.tailwindcss.com, fonts.googleapis.com, cdn.jsdelivr.net, unpkg.com. No random script tags.",
    "",
    "CONTENT FILL — NON-NEGOTIABLE:",
    "• Every visible section MUST contain substantive body content. A heading alone is NOT a section. Empty <section> bodies, sections with only an <h2> and no paragraph/list/grid/cards beneath it, are treated as a build failure even if the file structure is correct.",
    "• Forbidden in shipped output: 'Lorem ipsum', 'TODO', 'Coming soon', 'Add content here', 'Your bio goes here', or any other placeholder string. Comments like <!-- TODO --> are also forbidden.",
    "• If the user described the section topic but did NOT hand you the exact text (bios, project descriptions, skill lists, taglines, hero copy, About paragraphs), you MUST GENERATE realistic, polished, finished copy yourself in a voice appropriate to the role. Don't ask — generate.",
    "• Concrete fill targets per section type: About = 2-3 real paragraphs. Skills = a populated grid of at least 8-12 items grouped sensibly. Projects = at least 3-4 fully-described cards (title + 1-2 sentence description + tech tags + link). Hero = name + tagline + CTA. Contact = real-looking email + relevant social links.",
    "• Self-check before COMPLETED: scroll the rendered page mentally — does every section show real text, lists, or cards to a first-time visitor? If a section would render as empty whitespace below its heading, you are NOT done.",
])


# Layout/structure block used when generating an app from scratch (no
# pre-built template app on disk). The CUSTOMIZE directive replaces this
# block when a base app is being copied in.
_GENERATION_LAYOUT: str = "\n".join([
    "FILE LAYOUT (MANDATORY — create the project folder first, then the subfolders, then files):",
    "  apps/<slug>/                    ← project root, always created first",
    "    index.html                    # ~30 lines: <head>, mount target, CDN scripts, link to main.css + main.js",
    "    README.md                     # 1-paragraph description of what was built + how to run",
    "    styles/",
    "      main.css                    # project-specific CSS overrides (Tailwind handles 95%)",
    "    src/",
    "      main.js                     # bootstraps Alpine + initializes things",
    "      components/                 # one file per Alpine x-data component (e.g. LoginForm.js, DashboardTable.js)",
    "      lib/",
    "        supabase.js               # createClient(...) — ONLY for storage=\"supabase\" templates",
    "        api.js                    # thin fetch wrappers for REST/RPC calls — ONLY for storage=\"supabase\"",
    "    schema.sql                    # Supabase tables + RLS — ONLY for storage=\"supabase\" templates",
    "    public/                       # static assets (favicon, images); keep tiny — empty is fine",
    "",
    "INDEX.HTML CDN BLOCK (in <head>, in this EXACT order — order matters,",
    "do not rearrange):",
    "    <script src=\"https://cdn.tailwindcss.com\"></script>",
    "    <link rel=\"stylesheet\" href=\"styles/main.css\">",
    "    <script src=\"https://unpkg.com/lucide@latest/dist/umd/lucide.min.js\"></script>  <!-- icons; optional -->",
    "    <script type=\"module\" src=\"src/main.js\"></script>",
    "    <script defer src=\"https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js\"></script>",
    "  For Supabase apps, also load BEFORE main.js (so the Supabase global",
    "  is ready when main.js imports run):",
    "    <script src=\"https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js\"></script>",
    "",
    "  WHY main.js MUST come BEFORE alpinejs: Alpine fires its `alpine:init`",
    "  event during its own boot. main.js's job is to register Alpine.data()",
    "  components — if main.js runs AFTER alpinejs, Alpine has already",
    "  initialized and its event has already fired, so x-data=\"myComponent\"",
    "  bindings never resolve and every <template x-for> renders nothing",
    "  (sections look empty even though HTML + factory data are both correct).",
    "",
    "ALPINE.JS USAGE (your reactivity layer):",
    "• Components live in src/components/<Name>.js as ES modules exporting an Alpine x-data factory:",
    "      export function loginForm() { return { email: '', password: '', async submit() { /* ... */ } }; }",
    "• Register them in src/main.js:",
    "      import { loginForm } from './components/LoginForm.js';",
    "      document.addEventListener('alpine:init', () => { Alpine.data('loginForm', loginForm); });",
    "• In HTML: <form x-data=\"loginForm\" @submit.prevent=\"submit\"> … </form>",
    "• Prefer x-data, x-show, x-if, x-on, x-bind for reactivity. Don't write addEventListener spaghetti.",
    "",
    "• index.html MUST be a thin entry — markup skeleton only. NO inline <style> blocks beyond a tiny <style> for the initial loading screen if needed. NO inline app logic.",
    "• src/main.js uses native ES modules: `import { Foo } from './components/Foo.js';`. The browser resolves these directly — no bundler. Every component file must be a valid ES module.",
    "• styles/main.css holds project-specific overrides. Tailwind utility classes handle most styling.",
    "• Static-only templates (landing/portfolio/docs/blog/form-builder/etc.) DO NOT include src/lib/supabase.js, src/lib/api.js, or schema.sql. Everything else stays.",
    "• Do NOT cram everything into a single index.html. The single-file pattern is FORBIDDEN. Components MUST be separate files in src/components/.",
])


# Customize-mode directive — replaces _GENERATION_LAYOUT when a pre-built
# base app exists for this template key on disk. Tells the agent to PERSONALIZE
# the already-copied base app rather than regenerating it from scratch.
_CUSTOMIZE_DIRECTIVE: str = "\n".join([
    "CUSTOMIZE MODE — DO NOT REGENERATE FROM SCRATCH",
    "",
    "A working base app already exists at apps/<slug>/. It uses our standard stack",
    "(HTML + Tailwind CDN + Alpine.js + ES modules; Supabase CDN for dynamic apps).",
    "Your job is to PERSONALIZE this base app per the user's description below.",
    "You may:",
    "  • Edit the copy / wording in HTML to match the user's brand and use case.",
    "  • Update the color palette via Tailwind utility class swaps and styles/main.css.",
    "  • Replace placeholder names, taglines, sample data, sample categories.",
    "  • Add small features the user specifically mentions (a new page, a new field).",
    "  • If the user wants a feature outside the base app's scope, ADD it — but",
    "    keep the base structure intact (don't move files, don't rename existing",
    "    components, don't change the CDN block in index.html).",
    "You may NOT:",
    "  • Delete and recreate index.html, src/main.js, or schema.sql from scratch.",
    "  • Switch to a different framework (no React, no Vue, no build step).",
    "  • Remove Alpine.js or replace it with addEventListener spaghetti.",
    "",
    "The base app's README.md describes what it does and how it's structured.",
    "Read that first. Then read index.html and src/main.js. Then make targeted",
    "edits using the Edit tool — not Write — for files that already exist.",
    "",
    "When done, run a quick mental check: does index.html still load main.css +",
    "main.js? Are all imports in main.js still valid (i.e. did you delete a",
    "component file without removing its import)? If so, you broke the app —",
    "fix it before claiming completion.",
])


# Backwards-compatible alias. Some external imports / tests still reference
# UNIVERSAL_RULES; preserve the old "base + generation layout" concatenation
# they expect. Newer code should use _BASE_RULES / _GENERATION_LAYOUT directly
# via build_rules_for().
UNIVERSAL_RULES: str = _BASE_RULES + "\n\n" + _GENERATION_LAYOUT


# Cache for `_has_template_app` — the filesystem doesn't change at runtime,
# so we look up each key at most once.
_TEMPLATE_APP_CACHE: dict[str, bool] = {}


def _has_template_app(key: str) -> bool:
    """Return True iff a pre-built base app exists at template_apps/<key>/index.html.

    Path is resolved relative to this module's location (the templates.py
    file). Result is cached per-key in a module-level dict.
    """
    if key in _TEMPLATE_APP_CACHE:
        return _TEMPLATE_APP_CACHE[key]
    here = os.path.dirname(os.path.abspath(__file__))
    index_path = os.path.join(here, "template_apps", key, "index.html")
    exists = os.path.isfile(index_path)
    _TEMPLATE_APP_CACHE[key] = exists
    return exists


_RULES_LANDING = "\n".join([
    "PURPOSE: Marketing / product landing page. Convert visitors. Optimise for clarity above the fold and a strong CTA.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. No frameworks, no build step. Fonts via Google Fonts CDN. Optional Lucide icons via CDN.",
    "MUST INCLUDE — sections in this order, each in its own <section>:",
    "  1. Sticky <header> with logo + 4-6 nav links + primary CTA button on the right.",
    "  2. Hero: large H1 (2-3 short lines), one-paragraph subhead, primary CTA + secondary 'See how it works' link, supporting visual on the right or below (image, illustration, or a styled mock).",
    "  3. Trust strip: a row of customer logos / press mentions / review badges (or a tasteful skeleton if none implied).",
    "  4. Three-to-six 'Features' or 'Benefits' tiles with icon + heading + 1-2 line description. Use a 3-column grid that collapses to 1 column on mobile.",
    "  5. 'How it works' or 'Use cases' — alternating 50/50 image+text rows, max 3.",
    "  6. Social proof: 2-3 testimonial cards with avatar, name, role, company, and a short quote.",
    "  7. Pricing or product detail (if hinted at in the description).",
    "  8. FAQ — 5-8 questions in an accessible accordion (proper aria-expanded).",
    "  9. Final CTA band: full-width gradient/solid section, big H2, primary CTA.",
    " 10. Footer with 3-4 link columns + small print + social icons.",
    "MUST NOT INCLUDE: Dashboards, data tables, CRUD forms, login UI (unless explicitly requested), or any persistence — this is a brochure page.",
    "LAYOUT: One accent color + one neutral grey ramp (Tailwind zinc/slate). One headline font + one body font (Plus Jakarta Sans + Inter, or similar). Soft shadows, rounded-2xl cards. Smooth-scroll on internal #anchor links. Above-the-fold must paint without scrolling on a 1366x768 laptop. Lazy-load images below the hero.",
    "SUPABASE SCHEMA: N/A — static, no DB needed.",
    "WITHOUT SUPABASE: All copy/content hard-coded in HTML. Contact form (if present) posts to a `mailto:` link or shows a 'Thanks!' state and logs to console — no backend.",
])

_RULES_DASHBOARD = "\n".join([
    "PURPOSE: Operational analytics view. Surface key metrics and let users drill in. Density-first.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. Chart.js v4 from jsDelivr for visuals. Optional Supabase for real data; otherwise seed with realistic mock data.",
    "MUST INCLUDE: App shell with (a) top bar 56px tall with brand + global search + user menu, (b) left sidebar 240px with grouped nav sections (icons + labels), (c) main area scrollable with breadcrumbs + page title.",
    "  1. Header strip: page title + date-range picker + 'Refresh' button.",
    "  2. KPI row: 4-6 stat cards (one per metric) — large number, trend % vs previous period, sparkline. Use a 2/3/6 column responsive grid.",
    "  3. Primary chart (~480px tall) — line / area / bar depending on metric.",
    "  4. Two-up secondary view: data table (sortable, paginated 25/page) on the left, supporting chart or breakdown list on the right.",
    "  5. Activity feed at bottom (optional) — recent events with relative timestamps.",
    "  6. Keyboard shortcuts (`/` focuses search, `g h` to home, `?` shows help). Skeleton loaders. Empty/error states for every chart and table. Charts scale on window resize.",
    "MUST NOT INCLUDE: Marketing copy, big CTAs, pricing sections. No auto-refresh more than once per minute. No real-time websocket streams (charts redraw on date-range change only).",
    "LAYOUT: Dark mode default with toggle in user menu (persist in localStorage). Monospace font for numbers (JetBrains Mono / SF Mono). Cool, restrained palette — accent color reserved for actionable elements only.",
    "SUPABASE SCHEMA (if connected): `metrics(id uuid pk default gen_random_uuid(), name text, value numeric, recorded_at timestamptz default now())` + `events(id uuid pk default gen_random_uuid(), kind text, message text, occurred_at timestamptz default now())`. RLS + anon-allow.",
    "WITHOUT SUPABASE: Seed in-memory mock data (60 days of metrics + 20 recent events) so all charts/tables render realistically. Persist date-range + dark-mode preference to localStorage `aiui_dashboard_prefs`.",
])

_RULES_CRUD = "\n".join([
    "PURPOSE: Manage one main entity (and possibly a nested one). Prioritise speed of editing and discoverability of records.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. Lucide icons via CDN. Optional Supabase for persistence.",
    "MUST INCLUDE:",
    "  1. Top bar: app title, search input, primary 'New <Entity>' button.",
    "  2. Main view = table (default) or card grid, with column sort, filter chips, and a bulk-select checkbox column.",
    "  3. Row click → side drawer (640px wide) opens with the record's full detail in edit mode. ESC or X closes.",
    "  4. 'New' button opens the same drawer with empty fields.",
    "  5. Inline actions per row: pencil (edit) and trash (delete). Delete prompts a confirm modal naming the record.",
    "  6. Optimistic UI — apply add/edit immediately, revert on server failure with a toast. Empty state with illustration + 'Add your first <entity>' CTA. Inline validation (under each input). Required-field markers (red asterisk).",
    "MUST NOT INCLUDE: Extra entities the user didn't mention. No analytics dashboard. No marketing copy. No bulk-import tooling unless requested.",
    "LAYOUT: Clean, neutral palette. Borders for separation rather than shadows. Compact row height (44-48px) by default with a 'comfortable' toggle for 60-64px.",
    "SUPABASE SCHEMA (if connected): one table named after the entity, e.g. `items(id uuid pk default gen_random_uuid(), <fields based on user spec>, created_at timestamptz default now(), updated_at timestamptz default now())`. RLS scoped to `auth.uid() = user_id` if multi-user implied; otherwise anon-allow.",
    "WITHOUT SUPABASE: localStorage under a versioned key like `aiui_crud_v1_<entity>`. Seed 3-5 example rows so the UI is browsable.",
])

_RULES_CRM = "\n".join([
    "PURPOSE: A salesperson manages contacts and tracks deals through a pipeline. Three core entities: Contact, Deal, Activity.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. Native HTML5 drag-drop for the Kanban. Lucide icons. Strongly prefers Supabase.",
    "MUST INCLUDE: App shell similar to Dashboard with 4 distinct top-level views in the left sidebar nav:",
    "  1. **Pipeline** (default): Kanban board with a column per deal stage (Lead -> Qualified -> Proposal -> Won / Lost). Cards show contact name + deal value + close-date badge. Drag-and-drop between columns.",
    "  2. **Contacts**: searchable, sortable table with name / company / email / phone / last-contacted. Row click opens detail drawer.",
    "  3. **Deals**: same pattern as Contacts but with stage / value / probability / close-date columns.",
    "  4. **Activities**: timeline of calls / emails / meetings, filterable by contact or deal.",
    "  5. Clicking a Deal card on the Pipeline board opens a side panel with the linked Contact, recent Activities, and inline edit. Drag-drop stage changes persist immediately and auto-create an Activity 'Stage changed: Lead -> Qualified'.",
    "MUST NOT INCLUDE: Marketing landing page. No 'Sign up' CTA in the main UI (the user IS the salesperson — they're already in). No email-sending or VOIP integrations.",
    "LAYOUT: Corporate-friendly — Tailwind's slate or stone neutrals + one distinguishing accent (blue or emerald). Avatar circles with initials. Currency formatted ($X,XXX). Date-times relative (e.g. '3 days ago').",
    "SUPABASE SCHEMA: `contacts(id uuid pk default gen_random_uuid(), name text, email text, phone text, company text, role text, owner uuid, notes text, created_at timestamptz default now(), last_contacted_at timestamptz)` + `deals(id uuid pk default gen_random_uuid(), contact_id uuid references contacts(id) on delete cascade, title text, value numeric, stage text, probability int, expected_close_date date, owner uuid, notes text)` + `activities(id uuid pk default gen_random_uuid(), type text check (type in ('call','email','meeting')), subject text, contact_id uuid references contacts(id), deal_id uuid references deals(id), happened_at timestamptz default now(), notes text)`. RLS: `owner = auth.uid()` when auth is set up; otherwise anon-allow.",
    "WITHOUT SUPABASE: localStorage `aiui_crm_contacts`, `aiui_crm_deals`, `aiui_crm_activities`. Show a yellow banner: 'Connect Supabase to share this CRM across devices and team members.'",
])

_RULES_PORTFOLIO = "\n".join([
    "PURPOSE: Personal site for a designer / dev / writer / creative. Showcase the person and their work. Strong identity, fast-loading, scannable.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. Google Fonts for the chosen serif. Lucide for icons. No DB.",
    "MUST INCLUDE — single-page scroll, sections in order:",
    "  1. Minimal header: name (or monogram) on the left, 4 nav anchors on the right (Work / About / Writing / Contact).",
    "  2. Hero: large name H1, one-sentence elevator pitch, optional avatar/photo on the right, social links (GitHub/LinkedIn/Twitter/Email).",
    "  3. Selected work: a 2- or 3-column grid of project cards. Each card = thumbnail + title + 1-line role + tags. Cards link to a /work/<slug> detail page (or in-page anchor).",
    "  4. Project detail (if multi-page): header image, problem, approach, outcome, role + timeline, screenshots.",
    "  5. About: 2-paragraph bio + skill tags + 'Currently' line ('Currently building X at Y').",
    "  6. Writing/Blog (optional): list of recent posts with date + reading time.",
    "  7. Contact: email + booking link or simple form.",
    "  8. Footer with copyright + 'Last updated' line.",
    "  9. Keyboard nav (j/k between sections). Smooth-scroll. External links open in new tab.",
    "MUST NOT INCLUDE: CMS UI, login, comments, or analytics dashboards. No data persistence — content is hard-coded by the user editing the source.",
    "LAYOUT: Strong opinion. Either ultra-minimal (white/black with one accent) OR expressive (custom illustration, varied type sizes, asymmetric grid). Use a serif for headings (Fraunces, Playfair, EB Garamond). Pick ONE direction and commit.",
    "SUPABASE SCHEMA: N/A — static, no DB needed.",
    "WITHOUT SUPABASE: All projects/bio/links hard-coded in the HTML. Contact form posts via `mailto:` or shows a 'Thanks!' confirmation only.",
])

_RULES_DOCS = "\n".join([
    "PURPOSE: Technical documentation site. Developers find an answer in <30 seconds. Search-first, links-everywhere.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. highlight.js via CDN for code-block syntax highlighting. Lucide for icons. No DB.",
    "MUST INCLUDE: 3-column layout when >=1280px wide, 2-column at 768-1279, single-column on mobile.",
    "  1. Top bar: brand + global search (cmd+K) + version selector + GitHub link.",
    "  2. Left sidebar (240px): nav grouped by section ('Getting Started' / 'API Reference' / 'Guides' / 'Changelog'). Each leaf is a page.",
    "  3. Main content (flexible): markdown-rendered article. Semantic h1-h4. Include 'On this page' TOC on the right when there are >=3 h2s.",
    "  4. Right sidebar (200px): TOC of headings with current-section highlighted via IntersectionObserver.",
    "  5. Per-page footer: 'Was this helpful? thumbs-up/down' + 'Edit this page on GitHub' + Prev/Next links.",
    "  6. Code blocks with language label + copy button. Tabs for the same example in multiple languages. Callout boxes (note / warning / tip).",
    "  7. Keyboard search (cmd/ctrl + K opens overlay), arrow-keys to navigate results. Anchor links beside every heading on hover. URL hash sync for deep-linking.",
    "MUST NOT INCLUDE: Marketing landing-page conventions, big CTAs, pricing, or login walls. No comments/feedback persistence (the thumbs-up just shows 'Thanks!').",
    "LAYOUT: Light by default with dark toggle (system pref by default). Generous line-height (1.6+) and max-width on prose (~70 chars). Inter for body, JetBrains Mono for code. Optimize density over flash.",
    "SUPABASE SCHEMA: N/A — static, no DB needed. Pages are hard-coded HTML.",
    "WITHOUT SUPABASE: All articles hard-coded in HTML. Search uses client-side fuzzy match over an in-memory index built at page-load.",
])

_RULES_ECOMMERCE = "\n".join([
    "PURPOSE: Product catalog + cart + checkout. Visitor browses -> adds to cart -> checks out. Conversion-focused.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. Hash-routed single-page or multi-page. Optional Supabase for products/orders.",
    "MUST INCLUDE:",
    "  1. Header: brand + search + nav categories + cart icon with badge (item count).",
    "  2. Product list page: filter sidebar (categories, price range, tags) + responsive product grid (3-4 cols desktop, 2 mobile). Each card: image, name, price, quick-add button.",
    "  3. Product detail: image gallery (left), name + price + variants (size/color) + qty + 'Add to cart' (right), description below, related products at bottom.",
    "  4. Cart drawer or page: line items with thumbnail/name/qty stepper/price, subtotal, 'Checkout' CTA. Empty state with 'Continue shopping' link.",
    "  5. Checkout: 3-step form — shipping -> payment -> review. Inline validation. Order summary sticky on the right.",
    "  6. Confirmation page: 'Thanks for your order #1234' + items + total + 'Order tracking' link.",
    "  7. Quantity changes update totals immediately. Out-of-stock items disabled with reason.",
    "MUST NOT INCLUDE: Real payment processors (Stripe, PayPal, etc.) — stub with a 'Pay now (demo)' button that just confirms the order. No real shipping APIs. No tax-calculation services.",
    "LAYOUT: Clean, photo-forward. Generous product images (square or 4:5). Price in large bold. Hover state on cards. Sale prices in red, regular in default.",
    "SUPABASE SCHEMA (if connected): `products(id uuid pk default gen_random_uuid(), name text, description text, price numeric, image_url text, category text, stock int default 0, created_at timestamptz default now())` + `orders(id uuid pk default gen_random_uuid(), user_email text, total numeric, status text default 'pending', created_at timestamptz default now())` + `order_items(id uuid pk default gen_random_uuid(), order_id uuid references orders(id) on delete cascade, product_id uuid references products(id), qty int, price_at_purchase numeric)`. RLS + anon-allow.",
    "WITHOUT SUPABASE: Products hard-coded as a JS array (seed 8-12). Cart in localStorage `aiui_cart`. Orders simulated client-side and stored in `aiui_orders`.",
])

_RULES_BOOKING = "\n".join([
    "PURPOSE: Appointment scheduler (Calendly / SimplyBook style). Visitor picks a service, a date, a time slot, and books. Provider sees their schedule.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. Lucide for icons. Native date inputs + custom calendar grid. Optional Supabase for bookings + availability + auth.",
    "MUST INCLUDE — TWO USER ROLES, build both unless user requests only one:",
    "  Visitor flow:",
    "    1. Service picker: card grid of services with name, duration, price.",
    "    2. Date picker: calendar grid (current month + nav arrows). Days with slots clickable; empty days dimmed.",
    "    3. Time slot picker: available slots for the selected day, in the visitor's local timezone (show tz label).",
    "    4. Details form: name, email, phone, notes. Submit -> confirmation screen with `.ics` download.",
    "  Provider flow (if requested or implied):",
    "    1. Login (Supabase Auth if configured).",
    "    2. Dashboard with today's appointments + upcoming.",
    "    3. Availability editor: weekly recurring schedule (Mon-Sun, time ranges per day) + per-date overrides.",
    "    4. Service editor: name, duration, buffer, price, description.",
    "  Timezone-aware throughout. Disable past dates. Show 'X spots left' if capacity-limited.",
    "MUST NOT INCLUDE: Real payment processors. No real SMS or email sending — stub email confirmation as a console.log only and surface a 'We've sent a confirmation to <email> (demo)' message.",
    "LAYOUT: Friendly + trustworthy (Stripe-like). Step indicator at top of visitor flow. Confirmation screens celebratory — small green check animation.",
    "SUPABASE SCHEMA (if connected): `services(id uuid pk default gen_random_uuid(), name text, duration_minutes int, buffer_minutes int default 0, price numeric, description text)` + `availability_rules(id uuid pk default gen_random_uuid(), day_of_week int check (day_of_week between 0 and 6), start_time time, end_time time)` + `bookings(id uuid pk default gen_random_uuid(), service_id uuid references services(id), customer_name text, customer_email text, customer_phone text, notes text, starts_at timestamptz, ends_at timestamptz, status text default 'confirmed', created_at timestamptz default now())` + `blocked_dates(date date primary key, reason text)`. RLS + anon-allow for bookings; provider-only for the others.",
    "WITHOUT SUPABASE: localStorage `aiui_booking_services` (seed 3 services), `aiui_booking_availability` (Mon-Fri 9-5 default), `aiui_booking_bookings`. Show a yellow banner: 'Connect Supabase to keep bookings across devices.'",
])

_RULES_CHAT = "\n".join([
    "PURPOSE: Slack-lite messaging app with rooms or DMs. Real-time-ish conversation, multiple rooms, scroll-back, typing indicator.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. Lucide for icons. STRONGLY prefers Supabase + Realtime; without it the app is a single-user demo.",
    "MUST INCLUDE:",
    "  1. Left sidebar (240px): user avatar at top, list of rooms / DMs with unread count badges, '+ New room' button at bottom.",
    "  2. Main area: room header (room name + member count + settings cog), message list (newest at bottom, auto-scroll), typing indicator, message input with send button + emoji picker.",
    "  3. Right panel (collapsible): room members list with online indicator dots.",
    "  4. Message bubble: avatar + name + timestamp on hover, body, hover actions (react / reply / edit / delete for own messages).",
    "  5. With Supabase: Realtime channels (`supabase.channel('room:...').on('postgres_changes', ...)`). Fall back to polling every 3s if realtime fails.",
    "  6. Scroll position preserved per room (in memory). Markdown rendering (bold/italic/code). @mention auto-complete. Press `/` for command palette.",
    "MUST NOT INCLUDE: Voice or video calls. File uploads (mention as future feature). No external integrations (Slack-import, Discord-bridge, etc.).",
    "LAYOUT: Dark mode default. Compact bubble style (no avatar repeated for same author within 60s). Subtle 'NEW' separator line at last-read marker.",
    "SUPABASE SCHEMA: `users(id uuid pk default gen_random_uuid(), handle text unique, display_name text, avatar_url text)` + `rooms(id uuid pk default gen_random_uuid(), name text, is_dm boolean default false, created_at timestamptz default now())` + `room_members(room_id uuid references rooms(id) on delete cascade, user_id uuid references users(id), joined_at timestamptz default now(), primary key(room_id, user_id))` + `messages(id uuid pk default gen_random_uuid(), room_id uuid references rooms(id) on delete cascade, author_id uuid references users(id), body text, created_at timestamptz default now(), edited_at timestamptz)`. RLS: members can read room messages; only `auth.uid() = author_id` can write/edit/delete.",
    "WITHOUT SUPABASE: localStorage `aiui_chat_rooms` + `aiui_chat_messages`. Seed 3 default rooms (#general, #random, #dev) and 5 sample messages. Show a yellow banner: 'Connect Supabase + enable Realtime for true multi-user chat — this is currently single-user demo mode.'",
])

_RULES_AUTH = "\n".join([
    "PURPOSE: Login wall + protected pages. A small app that gates content behind login. The user describes 'what's behind the wall' separately.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. Supabase Auth required (email+password default; OAuth providers if requested).",
    "MUST INCLUDE:",
    "  1. Public pages: marketing-style home + login + signup + forgot-password.",
    "  2. Protected app (after login): app-shell with top bar + main content + user menu (logout).",
    "  3. Profile page: edit name/avatar/email; change password; delete account.",
    "  4. Auth flow: `supabase.auth.signInWithPassword(...)` or `supabase.auth.signInWithOAuth({provider: '...'})` if requested.",
    "  5. Every protected route checks `supabase.auth.getSession()` on mount; redirects to /login if absent. Show a 'Loading...' state during the check.",
    "  6. 'Remember me' persists session for 30 days. Clear error states ('Email not confirmed', 'Wrong password' — match Supabase error codes). Email-confirmation pending state with 'Resend' button.",
    "MUST NOT INCLUDE: The full app behind the auth wall — that's a separate request. Place a placeholder inside that says 'You're logged in as <email>. Build the protected app via a follow-up enhancement.' No third-party identity providers beyond what Supabase Auth supports.",
    "LAYOUT: Marketing pages use the LANDING template's conventions; protected pages use clean app-shell styling (top bar + main).",
    "SUPABASE SCHEMA: Auth uses Supabase's built-in `auth.users` table. Add `profiles(id uuid pk references auth.users(id) on delete cascade, display_name text, avatar_url text, updated_at timestamptz default now())` for editable profile fields. RLS: `auth.uid() = id`.",
    "WITHOUT SUPABASE: This template REQUIRES Supabase. If not connected, show a full-page message: 'Auth-gated apps require Supabase. Open the Database tab to connect a project.' Do NOT attempt a localStorage fake-auth.",
])

_RULES_BLOG = "\n".join([
    "PURPOSE: Article-publishing site. A writer publishes posts; visitors read. Reading-first layout.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. highlight.js via CDN for code-block syntax highlighting. marked.js (or similar) via CDN for markdown rendering. Optional Supabase.",
    "MUST INCLUDE:",
    "  1. Header: blog name + nav (Latest / Tags / About / RSS).",
    "  2. Home: list of post previews (title + excerpt + date + tag). Newest first.",
    "  3. Post detail: title (large H1), date + reading time, optional cover image, body (markdown-rendered), tags at bottom, prev/next post links.",
    "  4. Tag pages: posts filtered by a tag.",
    "  5. About: 2-paragraph bio + photo + social links.",
    "  6. RSS feed at /rss.xml (generated from posts).",
    "  7. Code blocks have copy button + syntax highlighting. Internal links same tab; external new tab. URL slugs from titles.",
    "MUST NOT INCLUDE: A CMS UI in the same project unless requested — assume the writer edits markdown / Supabase rows directly. No comments section by default (mention as a future feature). No paywalls or subscription gates.",
    "LAYOUT: Serif body font (Charter / Lora / Source Serif), comfortable line-height (1.65+), max-width 680px on prose. Clear visual hierarchy. Photos full-bleed on post detail.",
    "SUPABASE SCHEMA (if connected): `posts(id uuid pk default gen_random_uuid(), slug text unique, title text, excerpt text, body_markdown text, tags text[] default '{}', cover_image_url text, published_at timestamptz, created_at timestamptz default now())`. RLS: read-all; write requires auth.",
    "WITHOUT SUPABASE: Posts hard-coded as a JS array of `{slug, title, excerpt, body_markdown, tags, cover_image_url, published_at}`. Seed 3-5 sample posts. RSS rendered client-side from the same array.",
])

_RULES_BLANK = "\n".join([
    "PURPOSE: Free-form / custom build where exact requirements are unclear. The agent must clarify before coding.",
    "TECH: Static HTML + Tailwind CDN + vanilla JS. Other tech only if explicitly approved by the user during clarification.",
    "MUST INCLUDE — clarification flow BEFORE any code:",
    "  1. Switch to the Chat panel and ask the user 3-5 clarifying questions:",
    "     - Who's the primary user (admin? customer? specific role)?",
    "     - What's the SINGLE most important thing the app must do well?",
    "     - Visual style: minimal / playful / corporate / dark / something specific?",
    "     - Persistence: none / localStorage / Supabase tables?",
    "     - Out-of-scope: what should the app explicitly NOT do?",
    "  2. Once answers are in, write a one-paragraph spec, confirm with the user, THEN start building.",
    "  3. If the user's original description is already detailed enough (>200 chars AND mentions UI sections + behaviour), skip clarification and proceed with a Plan step before Execute.",
    "MUST NOT INCLUDE: Anything not surfaced in the clarification answers. Don't invent scope. Don't pick a tech stack the user didn't agree to.",
    "LAYOUT: Determined by clarification answers. Default to a clean app-shell or single-page scroll until told otherwise.",
    "SUPABASE SCHEMA: Determined by clarification — only design schema after the user picks 'Supabase tables' for persistence.",
    "WITHOUT SUPABASE: Default to localStorage if persistence is wanted but Supabase isn't connected. If 'no persistence' is chosen, keep state in memory only.",
])

_RULES_INVOICE = "\n".join([
    "PURPOSE: A single-page invoice editor for freelancers / small businesses. Left side = form fields. Right side = live A4 preview that prints cleanly via `window.print()`.",
    "TECH: Vanilla HTML/JS. Tailwind for styling. Lucide for icons. NO frameworks. Optional Supabase if connected.",
    "MUST INCLUDE: Client info (name, email, address) at top. Line-item table with description, quantity, unit price, line total. Add/remove line buttons. Auto-calculated subtotal. Editable tax rate input (default 0%). Auto-calculated tax amount and grand total. Currency picker (USD, EUR, GBP, PHP, JPY, AUD — via simple `<select>`, NO live conversion API). Date issued + due date pickers. Status badges (draft / sent / paid / overdue). Invoice number that auto-increments (max(existing)+1, default 1001). 'Print' and 'Duplicate as new' buttons.",
    "MUST NOT INCLUDE: Real payment processing (Stripe, PayPal, etc.). Email-sending. Multi-currency conversion APIs. PDF generation libraries (use print-to-PDF instead).",
    "LAYOUT: Two-column flex split. Left form panel scrolls; right preview is sticky/fixed. On mobile, stack vertically.",
    "SUPABASE SCHEMA (if connected): `invoices(id uuid pk default gen_random_uuid(), number int, client_name text, client_email text, client_address text, line_items jsonb, tax_rate numeric, currency text, issued_at date, due_at date, status text, created_at timestamptz default now(), paid_at timestamptz)`. Enable RLS, anon-allow policy.",
    "WITHOUT SUPABASE: persist to `localStorage` keyed `aiui_invoices`.",
])

_RULES_PROJECT_TRACKER = "\n".join([
    "PURPOSE: A dual-view task tracker — Kanban for daily work, Timeline for at-a-glance scheduling.",
    "TECH: Vanilla HTML/JS, native HTML5 drag-drop (no Sortable.js). Tailwind. Lucide. Optional Supabase.",
    "MUST INCLUDE: Kanban board with 4 columns (Backlog / In Progress / Review / Done). Native drag-drop between columns. Card displays title, assignee chip, due date, priority dot (red/yellow/green). Click card to open right-side drawer with full details (description, comments-as-static-list, label tags). Toggle button (top-right) to switch to Timeline view. Timeline view: horizontal time axis (7 days, 14 days, 30 days), tasks rendered as horizontal bars by start/end date. Filter chips for assignee + label. 'Completed in last 7 days' sparkline at top.",
    "MUST NOT INCLUDE: Subtasks, dependency arrows, time-tracking, integrations (GitHub, Slack).",
    "LAYOUT: Top bar (filters + view toggle), main area (Kanban OR Timeline). Drawer slides in from right.",
    "SUPABASE SCHEMA: `tasks(id uuid pk default gen_random_uuid(), title text, description text, status text default 'backlog', assignee_email text, due_date date, priority text default 'medium', labels text[] default '{}', position int default 0, created_at timestamptz default now())`. RLS + anon-allow.",
    "WITHOUT SUPABASE: localStorage `aiui_pt_tasks`.",
])

_RULES_AI_CHATBOT = "\n".join([
    "PURPOSE: Embed-ready or standalone chatbot that streams responses, with a paste-in knowledge base injected into the system prompt.",
    "TECH: Vanilla HTML/JS. Tailwind. Calls our existing `/api/chat-proxy` endpoint (NEVER directly calls Anthropic — that endpoint keeps the API key server-side). Uses Server-Sent Events for streaming. Optional Supabase for conversation persistence.",
    "MUST INCLUDE: Chat UI (Slack-lite). Settings panel (gear icon) with: System prompt textarea, knowledge-base textarea (paste any text, gets prepended to the system prompt as `<knowledge>...</knowledge>`), persona picker (Helpful Assistant / Friendly / Concise / Expert — these tweak the system prompt). Per-message: copy button, regenerate button. Conversation list sidebar (new chat, switch chat, delete chat). Streaming responses character-by-character.",
    "MUST NOT INCLUDE: Direct API key paste (security risk), file upload (just paste text), multi-user, billing, model selection (the proxy decides).",
    "IMPORTANT: The system prompt sent to `/api/chat-proxy` MUST be the concatenation of: persona prefix + user-provided system prompt + `<knowledge>` block + `<conversation_history>` block. The agent is the proxy; the user is the chatbot's end-user.",
    "LAYOUT: Left sidebar (conversation list, ~250px). Right (chat area + composer at bottom). Settings drawer slides from right.",
    "SUPABASE SCHEMA: `conversations(id uuid pk default gen_random_uuid(), title text, system_prompt text, knowledge text, persona text default 'helpful', created_at timestamptz default now())` + `messages(id uuid pk default gen_random_uuid(), conversation_id uuid references conversations(id) on delete cascade, role text check (role in ('user', 'assistant')), content text, created_at timestamptz default now())`. RLS + anon-allow.",
    "WITHOUT SUPABASE: localStorage `aiui_chatbot_convos`.",
])

_RULES_EXPENSE_TRACKER = "\n".join([
    "PURPOSE: Personal/small-team expense tracker with categories, monthly budgets, and visual trends.",
    "TECH: Vanilla HTML/JS. Tailwind. Lucide. Chart.js loaded via CDN (`https://cdn.jsdelivr.net/npm/chart.js`). Optional Supabase.",
    "MUST INCLUDE: Quick-add form at top (amount, category dropdown, note, date — defaults to today). Categories panel (manage list — add/remove/rename, default categories: Food, Transport, Housing, Entertainment, Health, Other). Charts: pie chart of category breakdown for current month, bar chart of monthly totals (last 6 months). Monthly budget setting per category — when total in a category exceeds budget, show red warning chip. Transaction list (filterable by category, date range), inline edit + delete. CSV export button (downloads `expenses-YYYY-MM.csv`).",
    "MUST NOT INCLUDE: Bank/Plaid integrations, multi-currency, receipt OCR, recurring expenses (keep it simple).",
    "LAYOUT: Top section (quick-add + summary cards: this-month total, vs-last-month delta, top category). Middle (charts side-by-side). Bottom (transaction list).",
    "SUPABASE SCHEMA: `expenses(id uuid pk default gen_random_uuid(), amount numeric not null, category text, note text, occurred_at date default current_date, created_at timestamptz default now())` + `budgets(category text primary key, monthly_limit numeric)`. RLS + anon-allow.",
    "WITHOUT SUPABASE: localStorage `aiui_expenses`.",
])

_RULES_FORM_BUILDER = "\n".join([
    "PURPOSE: Drag-and-drop form builder + a public form-fill page + a responses table.",
    "TECH: Vanilla HTML/JS. Tailwind. Native HTML5 drag-drop. Optional Supabase.",
    "MUST INCLUDE: Three views toggleable in the top nav: Builder / Preview / Responses. Builder: left palette of field types (Short text, Long text, Single choice, Multiple choice, Number, Date, Email, URL), right canvas (drop fields, click to edit label / placeholder / required-toggle / options for choice fields). Drag to reorder fields on the canvas. Preview: renders the form as the public-facing version. Responses: table with one row per submission, columns matching the form fields, CSV export. Shareable public URL (use the slug-based published-app URL we already have, or a sub-route like `?form=<form_id>`). Form schema stored as JSON.",
    "MUST NOT INCLUDE: Conditional logic (skip — too complex for first version), payment fields, Slack/Zapier integrations, multi-page forms.",
    "LAYOUT: Top tab bar (Builder / Preview / Responses). Builder shows palette + canvas. Preview shows the rendered form. Responses shows table.",
    "SUPABASE SCHEMA: `forms(id uuid pk default gen_random_uuid(), title text, schema jsonb, created_at timestamptz default now())` + `responses(id uuid pk default gen_random_uuid(), form_id uuid references forms(id) on delete cascade, answers jsonb, submitted_at timestamptz default now())`. RLS + anon-allow.",
    "WITHOUT SUPABASE: localStorage `aiui_forms` and `aiui_responses` keyed by form_id.",
])

_RULES_SOCIAL_FEED = "\n".join([
    "PURPOSE: A single-column microblog feed for a small community.",
    "TECH: Vanilla HTML/JS. Tailwind. Lucide. Optional Supabase + Realtime for live updates.",
    "MUST INCLUDE: Top: post composer (280-char limit shown as countdown, optional image-URL paste). Feed: posts in reverse chronological order showing author handle, time-ago, content, optional image, like button (with count), comment button (toggles thread of comments below the post), share button (copies URL to clipboard). Profile page (click handle) showing user's posts, follower/following counts, bio. Follow/Unfollow button. Compose dialog opens via floating action button.",
    "MUST NOT INCLUDE: Direct messages, push notifications, content moderation tooling, image upload (just URL paste).",
    "LAYOUT: Single column max-width 600px centered. FAB at bottom-right.",
    "SUPABASE SCHEMA: `profiles(id uuid pk default gen_random_uuid(), handle text unique, display_name text, bio text, avatar_url text, created_at timestamptz default now())` + `posts(id uuid pk default gen_random_uuid(), author_id uuid references profiles(id), content text check (char_length(content) <= 280), image_url text, created_at timestamptz default now())` + `likes(post_id uuid references posts(id) on delete cascade, user_id uuid references profiles(id), primary key(post_id, user_id))` + `comments(id uuid pk default gen_random_uuid(), post_id uuid references posts(id) on delete cascade, author_id uuid references profiles(id), content text, created_at timestamptz default now())` + `follows(follower_id uuid references profiles(id), followee_id uuid references profiles(id), primary key(follower_id, followee_id))`. RLS: read-all for posts/profiles/comments/likes; write requires `auth.uid() = author_id`.",
    "WITHOUT SUPABASE: localStorage with mock data — agent should pre-seed 5 fake posts + 3 fake users so the UI is browsable, AND show a one-line yellow banner: 'Connect Supabase + enable Auth for real multi-user sharing — this is currently a demo with mock data.'",
])


# Storage instructions appended after the template rules block. Mirrors the
# previous client-side STORAGE_INSTRUCTIONS dict.
STORAGE_INSTRUCTIONS: dict[str, str] = {
    "none": "• Storage: NO persistence. The app is stateless / UI-only.",
    "supabase": (
        "• Storage: a Supabase project will be attached after creation. "
        "Read URL/key from `window.SUPABASE_URL` / `window.SUPABASE_ANON_KEY` "
        "(injected by the host). Use `supabase-js` v2 from jsDelivr. Enable "
        "RLS on any table you create. Document your schema in `schema.sql` "
        "at the app root."
    ),
}


# Hand-crafted SVG mockups shown in the templates gallery. Each one is a
# stylized depiction of the template's layout — header bars, content blocks,
# accent-colored interactive elements. ViewBox 0 0 320 180 (16:9-ish).
_SVG_LANDING = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="lbg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1e1b4b"/><stop offset="1" stop-color="#0a0a0b"/></linearGradient></defs><rect width="320" height="180" fill="url(#lbg)"/><rect x="0" y="0" width="320" height="14" fill="#000" opacity="0.4"/><rect x="14" y="5" width="34" height="4" rx="1" fill="#a78bfa"/><circle cx="248" cy="7" r="1.5" fill="#fff" opacity="0.4"/><circle cx="258" cy="7" r="1.5" fill="#fff" opacity="0.4"/><circle cx="268" cy="7" r="1.5" fill="#fff" opacity="0.4"/><rect x="278" y="3" width="28" height="8" rx="2" fill="#a78bfa"/><rect x="14" y="38" width="170" height="9" rx="2" fill="#fff" opacity="0.85"/><rect x="14" y="52" width="120" height="6" rx="1" fill="#fff" opacity="0.55"/><rect x="14" y="66" width="140" height="4" rx="1" fill="#fff" opacity="0.3"/><rect x="14" y="84" width="50" height="14" rx="3" fill="#a78bfa"/><rect x="70" y="84" width="50" height="14" rx="3" fill="none" stroke="#a78bfa" stroke-width="1"/><rect x="208" y="32" width="98" height="64" rx="6" fill="#a78bfa" opacity="0.18"/><rect x="222" y="46" width="56" height="3" rx="1" fill="#a78bfa" opacity="0.7"/><rect x="222" y="55" width="40" height="3" rx="1" fill="#a78bfa" opacity="0.5"/><rect x="222" y="68" width="56" height="14" rx="2" fill="#a78bfa" opacity="0.4"/><rect x="14" y="118" width="92" height="46" rx="4" fill="#fff" opacity="0.06"/><rect x="114" y="118" width="92" height="46" rx="4" fill="#fff" opacity="0.06"/><rect x="214" y="118" width="92" height="46" rx="4" fill="#fff" opacity="0.06"/><circle cx="26" cy="130" r="4" fill="#a78bfa"/><rect x="36" y="128" width="40" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="20" y="142" width="78" height="2" rx="1" fill="#fff" opacity="0.3"/><rect x="20" y="148" width="60" height="2" rx="1" fill="#fff" opacity="0.3"/><circle cx="126" cy="130" r="4" fill="#a78bfa"/><rect x="136" y="128" width="40" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="120" y="142" width="78" height="2" rx="1" fill="#fff" opacity="0.3"/><rect x="120" y="148" width="60" height="2" rx="1" fill="#fff" opacity="0.3"/><circle cx="226" cy="130" r="4" fill="#a78bfa"/><rect x="236" y="128" width="40" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="220" y="142" width="78" height="2" rx="1" fill="#fff" opacity="0.3"/><rect x="220" y="148" width="60" height="2" rx="1" fill="#fff" opacity="0.3"/></svg>"""

_SVG_PORTFOLIO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="pbg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4c1d4a"/><stop offset="1" stop-color="#0a0a0b"/></linearGradient></defs><rect width="320" height="180" fill="url(#pbg)"/><rect x="0" y="0" width="320" height="14" fill="#000" opacity="0.4"/><circle cx="22" cy="7" r="3.5" fill="#ec4899"/><rect x="248" y="5" width="20" height="4" rx="1" fill="#fff" opacity="0.4"/><rect x="272" y="5" width="20" height="4" rx="1" fill="#fff" opacity="0.4"/><rect x="296" y="5" width="14" height="4" rx="1" fill="#fff" opacity="0.4"/><rect x="14" y="32" width="200" height="11" rx="2" fill="#fff" opacity="0.9"/><rect x="14" y="48" width="120" height="6" rx="1" fill="#ec4899" opacity="0.8"/><rect x="14" y="62" width="180" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="14" y="68" width="160" height="3" rx="1" fill="#fff" opacity="0.4"/><circle cx="20" cy="84" r="3" fill="#ec4899"/><circle cx="32" cy="84" r="3" fill="#ec4899" opacity="0.7"/><circle cx="44" cy="84" r="3" fill="#ec4899" opacity="0.4"/><rect x="14" y="100" width="92" height="60" rx="5" fill="#ec4899" opacity="0.18"/><rect x="14" y="100" width="92" height="44" rx="5" fill="#ec4899" opacity="0.32"/><rect x="20" y="148" width="50" height="3" rx="1" fill="#fff" opacity="0.85"/><rect x="20" y="154" width="36" height="2" rx="1" fill="#fff" opacity="0.4"/><rect x="114" y="100" width="92" height="60" rx="5" fill="#ec4899" opacity="0.16"/><rect x="114" y="100" width="92" height="44" rx="5" fill="#fff" opacity="0.18"/><rect x="120" y="148" width="50" height="3" rx="1" fill="#fff" opacity="0.85"/><rect x="120" y="154" width="42" height="2" rx="1" fill="#fff" opacity="0.4"/><rect x="214" y="100" width="92" height="60" rx="5" fill="#ec4899" opacity="0.18"/><rect x="214" y="100" width="92" height="44" rx="5" fill="#ec4899" opacity="0.42"/><rect x="220" y="148" width="50" height="3" rx="1" fill="#fff" opacity="0.85"/><rect x="220" y="154" width="38" height="2" rx="1" fill="#fff" opacity="0.4"/></svg>"""

_SVG_CRUD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="cbg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#064e3b"/><stop offset="1" stop-color="#0a0a0b"/></linearGradient></defs><rect width="320" height="180" fill="url(#cbg)"/><rect x="0" y="0" width="320" height="18" fill="#000" opacity="0.45"/><circle cx="22" cy="9" r="4" fill="#10b981"/><rect x="32" y="7" width="40" height="4" rx="1" fill="#fff" opacity="0.7"/><rect x="248" y="4" width="58" height="10" rx="3" fill="#10b981"/><rect x="258" y="7" width="38" height="4" rx="1" fill="#fff" opacity="0.9"/><rect x="14" y="32" width="60" height="6" rx="1" fill="#fff" opacity="0.6"/><rect x="14" y="42" width="40" height="3" rx="1" fill="#fff" opacity="0.3"/><rect x="14" y="56" width="292" height="22" rx="4" fill="#fff" opacity="0.06"/><rect x="22" y="64" width="6" height="6" rx="1" fill="#10b981"/><rect x="34" y="65" width="100" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="34" y="71" width="60" height="2" rx="1" fill="#fff" opacity="0.3"/><circle cx="290" cy="67" r="2" fill="#fff" opacity="0.4"/><rect x="14" y="82" width="292" height="22" rx="4" fill="#fff" opacity="0.06"/><rect x="22" y="90" width="6" height="6" rx="1" fill="#10b981" opacity="0.5"/><rect x="34" y="91" width="120" height="3" rx="1" fill="#fff" opacity="0.55"/><rect x="34" y="97" width="50" height="2" rx="1" fill="#fff" opacity="0.3"/><circle cx="290" cy="93" r="2" fill="#fff" opacity="0.4"/><rect x="14" y="108" width="292" height="22" rx="4" fill="#fff" opacity="0.06"/><rect x="22" y="116" width="6" height="6" rx="1" fill="#10b981"/><rect x="34" y="117" width="80" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="34" y="123" width="70" height="2" rx="1" fill="#fff" opacity="0.3"/><circle cx="290" cy="119" r="2" fill="#fff" opacity="0.4"/><rect x="14" y="134" width="292" height="22" rx="4" fill="#fff" opacity="0.06"/><rect x="22" y="142" width="6" height="6" rx="1" fill="#fff" opacity="0.18" stroke="#10b981" stroke-width="0.6"/><rect x="34" y="143" width="110" height="3" rx="1" fill="#fff" opacity="0.55"/><rect x="34" y="149" width="40" height="2" rx="1" fill="#fff" opacity="0.3"/><circle cx="290" cy="145" r="2" fill="#fff" opacity="0.4"/><rect x="14" y="160" width="100" height="14" rx="3" fill="#10b981" opacity="0.3"/><rect x="118" y="160" width="60" height="14" rx="3" fill="#fff" opacity="0.06"/><rect x="182" y="160" width="76" height="14" rx="3" fill="#fff" opacity="0.06"/></svg>"""

_SVG_INVOICE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="ibg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#422006"/><stop offset="1" stop-color="#0a0a0b"/></linearGradient></defs><rect width="320" height="180" fill="url(#ibg)"/><rect x="0" y="0" width="56" height="180" fill="#000" opacity="0.45"/><rect x="56" y="0" width="264" height="18" fill="#000" opacity="0.35"/><circle cx="14" cy="14" r="4" fill="#f59e0b"/><rect x="8" y="32" width="40" height="3" rx="1" fill="#f59e0b" opacity="0.55"/><rect x="8" y="42" width="40" height="2" rx="1" fill="#fff" opacity="0.35"/><rect x="8" y="50" width="40" height="2" rx="1" fill="#fff" opacity="0.35"/><rect x="8" y="58" width="40" height="2" rx="1" fill="#fff" opacity="0.35"/><rect x="8" y="66" width="40" height="2" rx="1" fill="#fff" opacity="0.7"/><rect x="8" y="74" width="40" height="2" rx="1" fill="#fff" opacity="0.35"/><rect x="64" y="6" width="60" height="6" rx="1" fill="#fff" opacity="0.7"/><rect x="240" y="4" width="70" height="10" rx="3" fill="#f59e0b"/><rect x="64" y="30" width="100" height="6" rx="1" fill="#fff" opacity="0.85"/><rect x="64" y="40" width="40" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="64" y="58" width="244" height="14" rx="2" fill="#fff" opacity="0.08"/><rect x="70" y="63" width="60" height="3" rx="1" fill="#fff" opacity="0.55"/><rect x="160" y="63" width="40" height="3" rx="1" fill="#fff" opacity="0.55"/><rect x="220" y="63" width="40" height="3" rx="1" fill="#fff" opacity="0.55"/><rect x="280" y="63" width="22" height="3" rx="1" fill="#fff" opacity="0.55"/><rect x="64" y="76" width="244" height="14" rx="2" fill="#fff" opacity="0.05"/><rect x="70" y="81" width="80" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="160" y="81" width="20" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="220" y="81" width="30" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="280" y="81" width="22" height="3" rx="1" fill="#f59e0b" opacity="0.85"/><rect x="64" y="92" width="244" height="14" rx="2" fill="#fff" opacity="0.05"/><rect x="70" y="97" width="100" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="160" y="97" width="20" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="220" y="97" width="30" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="280" y="97" width="22" height="3" rx="1" fill="#f59e0b" opacity="0.85"/><rect x="64" y="108" width="244" height="14" rx="2" fill="#fff" opacity="0.05"/><rect x="70" y="113" width="70" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="160" y="113" width="20" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="220" y="113" width="30" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="280" y="113" width="22" height="3" rx="1" fill="#f59e0b" opacity="0.85"/><rect x="200" y="138" width="108" height="32" rx="4" fill="#f59e0b" opacity="0.18"/><rect x="208" y="146" width="40" height="3" rx="1" fill="#fff" opacity="0.6"/><rect x="208" y="155" width="60" height="6" rx="1" fill="#f59e0b"/><rect x="74" y="148" width="50" height="14" rx="3" fill="#f59e0b" opacity="0.6"/><rect x="78" y="153" width="42" height="4" rx="1" fill="#fff" opacity="0.85"/></svg>"""

_SVG_DASHBOARD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="dbg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1e3a8a"/><stop offset="1" stop-color="#0a0a0b"/></linearGradient></defs><rect width="320" height="180" fill="url(#dbg)"/><rect x="0" y="0" width="320" height="16" fill="#000" opacity="0.45"/><circle cx="14" cy="8" r="3.5" fill="#3b82f6"/><rect x="22" y="6" width="36" height="4" rx="1" fill="#fff" opacity="0.7"/><rect x="120" y="4" width="80" height="8" rx="2" fill="#fff" opacity="0.08"/><circle cx="296" cy="8" r="3" fill="#3b82f6" opacity="0.6"/><circle cx="306" cy="8" r="3" fill="#fff" opacity="0.3"/><rect x="0" y="16" width="48" height="164" fill="#000" opacity="0.35"/><rect x="6" y="26" width="36" height="6" rx="2" fill="#3b82f6"/><rect x="6" y="38" width="30" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="6" y="48" width="30" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="6" y="58" width="30" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="6" y="68" width="30" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="56" y="26" width="62" height="38" rx="4" fill="#fff" opacity="0.07"/><rect x="62" y="32" width="32" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="62" y="40" width="22" height="8" rx="1" fill="#fff" opacity="0.85"/><polyline points="62,58 70,52 78,55 86,46 94,50 102,42 110,46" stroke="#3b82f6" stroke-width="1.4" fill="none"/><rect x="124" y="26" width="62" height="38" rx="4" fill="#fff" opacity="0.07"/><rect x="130" y="32" width="32" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="130" y="40" width="22" height="8" rx="1" fill="#fff" opacity="0.85"/><polyline points="130,58 138,55 146,50 154,52 162,45 170,48 178,42" stroke="#3b82f6" stroke-width="1.4" fill="none"/><rect x="192" y="26" width="62" height="38" rx="4" fill="#fff" opacity="0.07"/><rect x="198" y="32" width="32" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="198" y="40" width="22" height="8" rx="1" fill="#fff" opacity="0.85"/><polyline points="198,52 206,55 214,50 222,54 230,48 238,52 246,46" stroke="#3b82f6" stroke-width="1.4" fill="none"/><rect x="260" y="26" width="50" height="38" rx="4" fill="#fff" opacity="0.07"/><rect x="266" y="32" width="32" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="266" y="40" width="22" height="8" rx="1" fill="#fff" opacity="0.85"/><polyline points="266,58 273,52 280,55 287,46 294,50 301,46" stroke="#3b82f6" stroke-width="1.4" fill="none"/><rect x="56" y="72" width="254" height="58" rx="4" fill="#fff" opacity="0.05"/><polyline points="62,118 80,108 100,112 120,98 140,104 160,90 180,96 200,82 220,88 240,80 260,76 280,68 300,72" stroke="#3b82f6" stroke-width="1.6" fill="none"/><polyline points="62,118 80,108 100,112 120,98 140,104 160,90 180,96 200,82 220,88 240,80 260,76 280,68 300,72 300,128 62,128 Z" fill="#3b82f6" opacity="0.18" stroke="none"/><rect x="56" y="138" width="254" height="36" rx="4" fill="#fff" opacity="0.05"/><rect x="64" y="146" width="60" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="138" y="146" width="40" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="190" y="146" width="50" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="252" y="146" width="50" height="3" rx="1" fill="#fff" opacity="0.4"/><rect x="64" y="156" width="80" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="148" y="156" width="30" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="190" y="156" width="40" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="252" y="156" width="50" height="3" rx="1" fill="#3b82f6" opacity="0.85"/><rect x="64" y="164" width="70" height="3" rx="1" fill="#fff" opacity="0.7"/><rect x="148" y="164" width="30" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="190" y="164" width="40" height="3" rx="1" fill="#fff" opacity="0.5"/><rect x="252" y="164" width="50" height="3" rx="1" fill="#fff" opacity="0.5"/></svg>"""


# Order matters — controls dropdown order in the UI.
TEMPLATES: list[Template] = [
    Template(
        key="landing",
        label="Landing page",
        emoji="🌐",
        description="marketing / product page",
        placeholder="e.g. Landing page for a coffee shop called 'Bean There'. Include hero with logo and tagline, menu with 6 drinks, opening hours, and a contact form. Warm earthy palette (browns + cream), one body font.",
        rules=_RULES_LANDING,
        role_tag="Marketing site",
        feature_bullets=(
            "Hero, features, testimonials, pricing, FAQ",
            "Smooth-scroll anchors and Alpine accordion",
            "Mobile-ready in one file — no backend needed",
        ),
        svg_mockup=_SVG_LANDING,
    ),
    Template(
        key="dashboard",
        label="Dashboard",
        emoji="📊",
        description="metrics + charts",
        placeholder="e.g. Team activity dashboard. KPIs: tasks completed this week, average cycle time, deploys, error rate. Burndown chart, recent activity feed, dark mode default.",
        rules=_RULES_DASHBOARD,
        storage="supabase",
        role_tag="Analytics",
        feature_bullets=(
            "KPI cards with sparklines and trend %",
            "Chart.js line chart + sortable events table",
            "Top bar + sidebar shell, dark-mode default",
        ),
        svg_mockup=_SVG_DASHBOARD,
    ),
    Template(
        key="crud",
        label="CRUD app",
        emoji="📝",
        description="manage records",
        placeholder="e.g. Recipe manager — add, edit, delete recipes with name, ingredients (multi-line), prep time, difficulty (easy/medium/hard), and an optional photo URL.",
        rules=_RULES_CRUD,
        storage="supabase",
        role_tag="Auth + CRUD",
        feature_bullets=(
            "Supabase email login and signup, RLS-scoped",
            "Add / edit / delete with realtime sync",
            "Filter tabs and a single `todos` table",
        ),
        svg_mockup=_SVG_CRUD,
    ),
    Template(
        key="crm",
        label="CRM",
        emoji="🤝",
        description="contacts + deals",
        placeholder="e.g. CRM for a small consulting firm. Pipeline: Lead → Discovery → Proposal → Closed Won / Lost. Contacts have company, role, last-call-date. Deals show value + expected close.",
        rules=_RULES_CRM,
        storage="supabase",
    ),
    Template(
        key="portfolio",
        label="Portfolio",
        emoji="🎨",
        description="personal showcase",
        placeholder="e.g. Portfolio site for a UX designer named Maya. 4 case-study projects, About section, link to her writing on Medium. Clean serif headers, off-white background.",
        rules=_RULES_PORTFOLIO,
        role_tag="Personal site",
        feature_bullets=(
            "Hero, project grid with category filter",
            "About, skills, contact form (simulated submit)",
            "Light / dark theme toggle, persisted",
        ),
        svg_mockup=_SVG_PORTFOLIO,
    ),
    Template(
        key="docs",
        label="Docs site",
        emoji="📚",
        description="technical documentation",
        placeholder="e.g. Docs site for a JavaScript library called 'snapdb'. Sections: Getting Started, API Reference, Recipes, Migration. Code samples in JS and TypeScript tabs.",
        rules=_RULES_DOCS,
    ),
    Template(
        key="ecommerce",
        label="E-commerce",
        emoji="🛒",
        description="catalog + cart",
        placeholder="e.g. Plant shop with 12 sample plants. Filters: indoor/outdoor, light needs, price. Cart drawer. Demo checkout (no real payment). Earthy green palette.",
        rules=_RULES_ECOMMERCE,
        storage="supabase",
    ),
    Template(
        key="booking",
        label="Booking",
        emoji="📅",
        description="appointment scheduler",
        placeholder="e.g. Booking page for a yoga instructor. 3 services (60-min private, 90-min couples, 75-min group). Mon/Wed/Fri 8am–6pm available. Calendar picker → time slots → confirm.",
        rules=_RULES_BOOKING,
        storage="supabase",
    ),
    Template(
        key="chat",
        label="Chat",
        emoji="💬",
        description="messaging app",
        placeholder="e.g. Team chat with 3 default rooms (#general, #random, #dev). Messages, typing indicator, online dot, emoji reactions. Supabase Realtime for live updates.",
        rules=_RULES_CHAT,
        storage="supabase",
    ),
    Template(
        key="auth",
        label="Auth-gated app",
        emoji="🔐",
        description="login + protected pages",
        placeholder="e.g. A members-only journal app. Email+password sign up, email confirmation, login, forgot-password. After login, simple journal-entry editor. Use Supabase Auth.",
        rules=_RULES_AUTH,
        storage="supabase",
    ),
    Template(
        key="blog",
        label="Blog",
        emoji="✍️",
        description="article publishing",
        placeholder="e.g. Personal blog with 5 sample posts about indie game dev. Tags: design, code, postmortem. RSS feed. About page with photo + Twitter link. Serif body font.",
        rules=_RULES_BLOG,
        storage="supabase",
    ),
    Template(
        key="blank",
        label="Blank / custom",
        emoji="✨",
        description="agent will clarify first",
        placeholder="Describe what you want the AIUI Agent to build. Don't worry if it's vague — the agent will ask follow-up questions in chat before writing code.",
        rules=_RULES_BLANK,
    ),
    Template(
        key="invoice",
        label="Invoice / Quote",
        emoji="🧾",
        description="invoice editor + print",
        placeholder="e.g. Invoice editor for a freelance designer. USD default, 12% tax, fields for client name/email/address, 5 line-item rows by default, status badges (draft/sent/paid). Print-ready A4 preview on the right.",
        rules=_RULES_INVOICE,
        storage="supabase",
        role_tag="Billing",
        feature_bullets=(
            "Customers, invoices, line items — 4 tables with RLS",
            "Auth-gated dashboard with KPI cards",
            "Printable invoice detail view, status badges",
        ),
        svg_mockup=_SVG_INVOICE,
    ),
    Template(
        key="project-tracker",
        label="Project tracker",
        emoji="📋",
        description="Kanban + timeline",
        placeholder="e.g. Tracker for a 4-person dev team. Backlog/In Progress/Review/Done columns. Cards show title, assignee, due date, priority. Toggle to a 14-day timeline view. Filter by assignee.",
        rules=_RULES_PROJECT_TRACKER,
        storage="supabase",
    ),
    Template(
        key="ai-chatbot",
        label="AI chatbot",
        emoji="🤖",
        description="streaming chat + KB",
        placeholder="e.g. Customer-support bot for 'Acme Plants'. System prompt: friendly, concise, plant-care expert. Knowledge base: paste in our care guide. Persona: Friendly. Streams responses.",
        rules=_RULES_AI_CHATBOT,
        storage="supabase",
    ),
    Template(
        key="expense-tracker",
        label="Expense tracker",
        emoji="💸",
        description="categories + budgets",
        placeholder="e.g. Personal expense tracker. Default categories: Food, Transport, Housing, Entertainment, Health, Other. Pie chart for the month, 6-month bar chart, $1000 budget on Food.",
        rules=_RULES_EXPENSE_TRACKER,
        storage="supabase",
    ),
    Template(
        key="form-builder",
        label="Form builder",
        emoji="📥",
        description="drag-drop forms + responses",
        placeholder="e.g. Customer feedback form: name, email, rating (1-5), 'How did you hear about us?' (single choice), comments (long text). Share via public URL, view responses in a table.",
        rules=_RULES_FORM_BUILDER,
        storage="supabase",
    ),
    Template(
        key="social-feed",
        label="Social feed",
        emoji="📣",
        description="microblog + likes + follows",
        placeholder="e.g. Microblog for a small writers' community. 280-char posts, optional image URL, likes, threaded comments, follow other handles. Single 600px column.",
        rules=_RULES_SOCIAL_FEED,
        storage="supabase",
    ),
    Template(
        key="custom",
        label="Custom",
        emoji="✨",
        description="Build from your description — no template",
        placeholder="Describe your app: what it does, who it's for, the look and feel, any specific sections or features.",
        rules="",  # No template-specific guidance — baseline (BASE_RULES + GENERATION_LAYOUT) is enough.
        storage="none",
        role_tag="From scratch",
        feature_bullets=(
            "Skip the template gallery — describe what you want",
            "Static HTML + Tailwind + Alpine baseline still applied",
            "Agent builds the file layout for you",
        ),
        svg_mockup="",  # Frontend renders a dashed-border + glyph card instead of an SVG mockup.
    ),
]


_BY_KEY: dict[str, Template] = {t.key: t for t in TEMPLATES}


def get_template(key: str) -> Template | None:
    return _BY_KEY.get(key)


def is_valid_key(key: str) -> bool:
    return key in _BY_KEY


def storage_for(key: str) -> str:
    """Return the template's `storage` field ("supabase" or "none").

    Returns "none" for unknown keys — callers that care should pre-validate
    via `is_valid_key`.
    """
    t = _BY_KEY.get(key)
    return t.storage if t is not None else "none"


def requires_supabase(key: str, user_storage_choice: str | None) -> bool:
    """Return True iff the template *and* the user's storage choice both
    say "supabase". Used by the create-task flow to decide whether to gate
    the build on a connected Supabase project.
    """
    return storage_for(key) == "supabase" and (user_storage_choice or "") == "supabase"


# When the agent has access to the `search_flights` MCP tool (only true on
# the dedicated agent VM where flights-mcp is registered — not on the
# orchestrator with AGENT_BACKEND=local), instruct it to fetch real Duffel
# offers for the user's route and rewrite the seed flight catalog. Harmless
# on AGENT_BACKEND=local because the tool simply isn't available — Claude
# will fall back to the seed data and emit a one-line comment noting it.
_FLIGHT_BOOKING_MCP_HINT = """## Real flight data

If you have access to a `search_flights` MCP tool, call it for the user's
requested route and dates and rewrite `src/data.js` so the `flights` named
export contains the returned offers. Preserve the existing schema fields
(`id, origin, destination, airline, price, stops, duration, departureHour,
departureBucket, departureLabel, arrivalLabel, cabin, baggage`) so
`src/main.js` continues to work. Re-derive `cities` and `airlines` from
the offers. The tool's `departure_hour` (snake_case) maps to
`departureHour` (camelCase); recompute `departureBucket` using:
  bucketize = (h) => h<6?"early":h<12?"morning":h<18?"afternoon":"evening"
If the tool isn't registered, or returns an error, or returns no offers,
leave the seed data in place and add a one-line comment noting the fallback.
"""


def build_rules_for(key: str, storage: str | None = None) -> str:
    """Return the rules block for an agent BUILD prompt.

    Two modes:
      • Generation mode (default): _BASE_RULES + _GENERATION_LAYOUT + the
        template's rules. The agent creates the project from scratch.
      • Customize mode: _BASE_RULES + _CUSTOMIZE_DIRECTIVE + the template's
        rules. Activated when a pre-built base app exists on disk for this
        key (see `_has_template_app`); the agent personalizes the already-
        copied base app instead of regenerating it.

    Returns an empty string for unknown keys — the caller should validate
    the key before calling this if you want stricter behavior.
    """
    t = _BY_KEY.get(key)
    if t is None:
        return ""
    if _has_template_app(key):
        parts = [_BASE_RULES.strip(), _CUSTOMIZE_DIRECTIVE.strip(), t.rules.strip()]
    else:
        parts = [_BASE_RULES.strip(), _GENERATION_LAYOUT.strip(), t.rules.strip()]
    if storage and storage in STORAGE_INSTRUCTIONS:
        parts.append(STORAGE_INSTRUCTIONS[storage].strip())
    if key == "flight-booking":
        parts.append(_FLIGHT_BOOKING_MCP_HINT.strip())
    # Drop empty parts so a Template with rules="" (e.g. the synthetic "custom"
    # entry) doesn't leave a trailing blank section in the agent's prompt.
    return "\n\n".join(p for p in parts if p)
