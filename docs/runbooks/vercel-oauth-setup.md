# Vercel one-click Connect: server setup runbook

The code for one-click "Connect with Vercel" (OAuth) is fully deployed and
dormant. Until the env vars below exist, the UI automatically falls back to
paste-an-access-token, which works today. Do the steps below once and every
user gets the one-click flow with zero code changes.

## 1. Register the Integration (Vercel dashboard, one time)

1. vercel.com dashboard -> pick your team/account -> **Integrations** (sidebar)
   -> **Integrations Console** -> **Create**.
2. Fill the form (this is a "connectable account" integration):
   - Name: `AIUI Deploy` (any name)
   - URL Slug: e.g. `aiui-deploy`  <- remember this value
   - Redirect URL: `https://ai-ui.coolestdomain.win/api/tasks/vercel/oauth/callback`
   - API Scopes:
     - `user` = Read (verify who connected)
     - `deployment` = Read/Write (create deployments)
     - `project` = Read/Write (deployments auto-create projects)
     - optional for later: `project-env-vars` = Read/Write
   - The rest (logo, descriptions, EULA/privacy URLs) as you like; a
     Community integration does NOT need marketplace approval to be
     installable via its URL.
3. After creating, open the integration's settings -> **Credentials** section:
   copy the **Client ID** and **Client Secret**.

## 2. Server env (host .env, tasks service)

Append to `/root/proxy-server/.env` (never commit this file):

```
VERCEL_CLIENT_ID=<client id from the console>
VERCEL_CLIENT_SECRET=<client secret from the console>
VERCEL_INTEGRATION_SLUG=<your URL slug, e.g. aiui-deploy>
```

Then recreate the tasks container so it picks the env up:

```
cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --force-recreate tasks
```

## 3. Verify

- `GET /api/tasks/vercel/oauth/config` (signed in) returns `{"oauth": true}`.
- Click Deploy on any app while disconnected: a Vercel install popup opens
  instead of the token field; after Install, the popup closes itself and the
  deploy runs.

## How the flow works (for reference)

start -> `https://vercel.com/integrations/<slug>/new?state=<csrf>` ->
user installs -> Vercel redirects the popup to our Redirect URL with
`code`, `state`, `teamId`, `configurationId`, `next` -> server exchanges the
one-shot code (valid 30 min) at `POST https://api.vercel.com/v2/oauth/access_token`
(form-encoded: client_id, client_secret, code, redirect_uri) -> long-lived
access token stored Fernet-encrypted per user with team_id + configuration_id
-> all deploys use it (teamId appended automatically when present).
