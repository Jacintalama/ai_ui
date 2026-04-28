# Tasks Tracker

A minimal task manager backed by Supabase. Supports sign-in/sign-up with email and password, and full task CRUD (create, edit, toggle done, delete) with optional descriptions and due dates. Overdue tasks are highlighted in orange.

## How to run

Serve the app from the tasks MCP service, which injects `window.SUPABASE_URL` and `window.SUPABASE_ANON_KEY` at runtime. Open the served URL in a browser - no build step required.
