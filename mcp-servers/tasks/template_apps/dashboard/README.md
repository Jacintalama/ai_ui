# <%= APP_NAME %> — Analytics Dashboard

An operational analytics dashboard with KPI cards, sparklines, a line chart, a top-events bar chart, and a paginated event log.

## Tables required

- `events` — see `schema.sql`. RLS limits each user to their own events.

## Pages

- **Overview** — KPI cards, sessions-over-time line chart, recent events table (sortable, paginated 25/page), top-events bar chart
- **Reports** — placeholder
- **Users** — placeholder
- **Settings** — theme toggle

## Structure

```
index.html              Single-page shell with sidebar + topbar
schema.sql              Postgres + RLS policies
styles/main.css
src/main.js             Alpine bootstrap
src/lib/
  supabase.js           Client init
  api.js                fetchEvents() + KPI / chart-series helpers; mock generator when not connected
src/components/
  AppShell.js           Auth, theme, navigation, sparkline canvas helper
  LoginForm.js
  OverviewPage.js       Page logic — Chart.js line + horizontal bar, sortable + paginated table
```

## Customizing

- Range options: edit the `<select>` in `index.html` (and the values respect any positive integer of days).
- Add KPIs: extend `summarize()` in `api.js` and the `kpis` getter in `OverviewPage.js`.
- Real-time: add `supabase.channel('events').on('postgres_changes', …)` in `OverviewPage.init()` to push new rows.
- Recording events: insert into `events` with `event_type` and a `details` JSONB blob from your app code.
