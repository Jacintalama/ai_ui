# <%= APP_NAME %> — Todo List

A multi-user todo app powered by Supabase. Users sign up / sign in with email + password and see only their own todos. Real-time subscriptions keep multiple browser tabs in sync.

## Tables required

- `todos` — see `schema.sql`. Row-level security policies scope every row to the authenticated user.

## Structure

```
index.html              Routes by hash: #/login, #/
schema.sql              Postgres + RLS policies
styles/main.css         Project tweaks
src/main.js             Alpine bootstrap
src/lib/
  supabase.js           Supabase client (uses window.SUPABASE_URL / window.SUPABASE_ANON_KEY)
  api.js                Thin CRUD + realtime wrappers; localStorage fallback when not connected
src/components/
  AppShell.js           Routing + auth/session state
  LoginForm.js          Sign in / sign up
  TodoApp.js            Todo CRUD + filters
```

## Customizing

- Change `length(title) <= 200` in `schema.sql` to adjust max title length.
- Add a `due_date timestamptz` column + UI for deadlines.
- Add tags via a `todo_tags` join table — keep RLS pattern identical.

## Without Supabase

When `window.SUPABASE_URL` is missing, the app degrades to a localStorage-only mode so users can preview the UI before connecting a backend.
