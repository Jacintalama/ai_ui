"""Canonical template definitions for the AIUI App Builder.

This is the single source of truth for build templates. The frontend fetches
this list via GET /api/templates and only sends `template_key` when creating
a project — the rules text is looked up server-side, NOT trusted from the
browser. Closes a prompt-injection vector.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    key: str
    label: str
    emoji: str
    description: str
    placeholder: str
    rules: str

    @property
    def display(self) -> str:
        return f"{self.emoji} {self.label} — {self.description}"


# Universal rules prefix prepended to every template's rules block before
# being sent to the agent. Kept short — the agent's PROMPT_TEMPLATE already
# knows the broad strokes.
UNIVERSAL_RULES: str = "\n".join([
    "RULES (strict):",
    "• Tech: static HTML + Tailwind CDN + vanilla JS only. No build step. Single index.html unless the app genuinely needs multiple pages.",
    "• Semantic HTML5: use <header>, <main>, <section>, <footer>. One <h1> per page.",
    "• Responsive: mobile-first, must work from 320px up. Test header/nav collapse at <768px.",
    "• Accessibility: alt text on all images, labels on form fields, visible focus states, contrast ≥4.5:1 for body text.",
    "• Performance: inline critical CSS in <style>, no JS frameworks, lazy-load images below the fold.",
    "• Whitelisted CDNs only: cdn.tailwindcss.com, fonts.googleapis.com, cdn.jsdelivr.net, unpkg.com. No random script tags.",
    "• No placeholder copy like 'Lorem ipsum' — write real, plausible copy based on the user's description.",
])


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


# Order matters — controls dropdown order in the UI.
TEMPLATES: list[Template] = [
    Template(
        key="landing",
        label="Landing page",
        emoji="🌐",
        description="marketing / product page",
        placeholder="e.g. Landing page for a coffee shop called 'Bean There'. Include hero with logo and tagline, menu with 6 drinks, opening hours, and a contact form. Warm earthy palette (browns + cream), one body font.",
        rules=_RULES_LANDING,
    ),
    Template(
        key="dashboard",
        label="Dashboard",
        emoji="📊",
        description="metrics + charts",
        placeholder="e.g. Team activity dashboard. KPIs: tasks completed this week, average cycle time, deploys, error rate. Burndown chart, recent activity feed, dark mode default.",
        rules=_RULES_DASHBOARD,
    ),
    Template(
        key="crud",
        label="CRUD app",
        emoji="📝",
        description="manage records",
        placeholder="e.g. Recipe manager — add, edit, delete recipes with name, ingredients (multi-line), prep time, difficulty (easy/medium/hard), and an optional photo URL.",
        rules=_RULES_CRUD,
    ),
    Template(
        key="crm",
        label="CRM",
        emoji="🤝",
        description="contacts + deals",
        placeholder="e.g. CRM for a small consulting firm. Pipeline: Lead → Discovery → Proposal → Closed Won / Lost. Contacts have company, role, last-call-date. Deals show value + expected close.",
        rules=_RULES_CRM,
    ),
    Template(
        key="portfolio",
        label="Portfolio",
        emoji="🎨",
        description="personal showcase",
        placeholder="e.g. Portfolio site for a UX designer named Maya. 4 case-study projects, About section, link to her writing on Medium. Clean serif headers, off-white background.",
        rules=_RULES_PORTFOLIO,
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
    ),
    Template(
        key="booking",
        label="Booking",
        emoji="📅",
        description="appointment scheduler",
        placeholder="e.g. Booking page for a yoga instructor. 3 services (60-min private, 90-min couples, 75-min group). Mon/Wed/Fri 8am–6pm available. Calendar picker → time slots → confirm.",
        rules=_RULES_BOOKING,
    ),
    Template(
        key="chat",
        label="Chat",
        emoji="💬",
        description="messaging app",
        placeholder="e.g. Team chat with 3 default rooms (#general, #random, #dev). Messages, typing indicator, online dot, emoji reactions. Supabase Realtime for live updates.",
        rules=_RULES_CHAT,
    ),
    Template(
        key="auth",
        label="Auth-gated app",
        emoji="🔐",
        description="login + protected pages",
        placeholder="e.g. A members-only journal app. Email+password sign up, email confirmation, login, forgot-password. After login, simple journal-entry editor. Use Supabase Auth.",
        rules=_RULES_AUTH,
    ),
    Template(
        key="blog",
        label="Blog",
        emoji="✍️",
        description="article publishing",
        placeholder="e.g. Personal blog with 5 sample posts about indie game dev. Tags: design, code, postmortem. RSS feed. About page with photo + Twitter link. Serif body font.",
        rules=_RULES_BLOG,
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
    ),
    Template(
        key="project-tracker",
        label="Project tracker",
        emoji="📋",
        description="Kanban + timeline",
        placeholder="e.g. Tracker for a 4-person dev team. Backlog/In Progress/Review/Done columns. Cards show title, assignee, due date, priority. Toggle to a 14-day timeline view. Filter by assignee.",
        rules=_RULES_PROJECT_TRACKER,
    ),
    Template(
        key="ai-chatbot",
        label="AI chatbot",
        emoji="🤖",
        description="streaming chat + KB",
        placeholder="e.g. Customer-support bot for 'Acme Plants'. System prompt: friendly, concise, plant-care expert. Knowledge base: paste in our care guide. Persona: Friendly. Streams responses.",
        rules=_RULES_AI_CHATBOT,
    ),
    Template(
        key="expense-tracker",
        label="Expense tracker",
        emoji="💸",
        description="categories + budgets",
        placeholder="e.g. Personal expense tracker. Default categories: Food, Transport, Housing, Entertainment, Health, Other. Pie chart for the month, 6-month bar chart, $1000 budget on Food.",
        rules=_RULES_EXPENSE_TRACKER,
    ),
    Template(
        key="form-builder",
        label="Form builder",
        emoji="📥",
        description="drag-drop forms + responses",
        placeholder="e.g. Customer feedback form: name, email, rating (1-5), 'How did you hear about us?' (single choice), comments (long text). Share via public URL, view responses in a table.",
        rules=_RULES_FORM_BUILDER,
    ),
    Template(
        key="social-feed",
        label="Social feed",
        emoji="📣",
        description="microblog + likes + follows",
        placeholder="e.g. Microblog for a small writers' community. 280-char posts, optional image URL, likes, threaded comments, follow other handles. Single 600px column.",
        rules=_RULES_SOCIAL_FEED,
    ),
]


_BY_KEY: dict[str, Template] = {t.key: t for t in TEMPLATES}


def get_template(key: str) -> Template | None:
    return _BY_KEY.get(key)


def is_valid_key(key: str) -> bool:
    return key in _BY_KEY


def build_rules_for(key: str, storage: str | None = None) -> str:
    """Return the universal rules + the template's rules + optional storage block.

    Returns an empty string for unknown keys — the caller should validate
    the key before calling this if you want stricter behavior.
    """
    t = _BY_KEY.get(key)
    if t is None:
        return ""
    parts = [UNIVERSAL_RULES.strip(), t.rules.strip()]
    if storage and storage in STORAGE_INSTRUCTIONS:
        parts.append(STORAGE_INSTRUCTIONS[storage].strip())
    return "\n\n".join(parts)
