# "Continue with Google" on the AIUI login page

The wiring is deployed and **dormant**. The button does not appear until the two
env vars below exist. Do these steps once and it appears for everyone, with no
code change.

This is about signing in to **the AIUI platform itself** — the page at
`https://ai-ui.coolestdomain.win/auth`, which today offers email/password and
"Continue with Microsoft".

It is NOT the same as Lukas's standup item about built apps having Google login.
That one is harder and is explained at the bottom.

## Why it is not already on

Open WebUI supports Google natively — `config.py:2621` registers the provider as
soon as a client id and secret are present. The server already has a
`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, but they belong to the Gmail and
Drive connectors, and their authorized redirect URIs do not include this login
callback. Verified against Google on 2026-08-05:

```
GET https://accounts.google.com/o/oauth2/v2/auth
      ?client_id=<the connector client>
      &redirect_uri=https://ai-ui.coolestdomain.win/oauth/google/callback
  -> redirect_uri_mismatch
```

So reusing that client would put a button on the login page that fails for
everyone who clicks it. The compose entry therefore reads
`WEBUI_GOOGLE_CLIENT_ID`, a name nothing sets yet, which keeps it dark until
someone has done step 1.

## 1. Google Cloud Console (about two minutes)

Project **AIUI - Project** (`aiui-project`, number 156374104574) already exists.

You can either add the callback to the existing OAuth client, or create a new
one. **Creating a new one is safer** — it keeps the login separate from the
Gmail and Drive connectors, so revoking one never breaks the other.

1. console.cloud.google.com, select **AIUI - Project**.
2. **APIs & Services** -> **Credentials** -> **Create credentials** ->
   **OAuth client ID**.
3. Application type: **Web application**. Name it e.g. `AIUI Login`.
4. Under **Authorized redirect URIs**, add exactly:

   ```
   https://ai-ui.coolestdomain.win/oauth/google/callback
   ```

   It must match character for character — no trailing slash.
5. Create, then copy the **Client ID** and **Client secret**.

If the consent screen has never been configured for this project, Google will
prompt for it. **External** + your app name + a support email is enough for
sign-in; no verification review is needed while users are limited to your own
Workspace or test users.

## 2. Server env

Append to `/root/proxy-server/.env` (never commit this file):

```
WEBUI_GOOGLE_CLIENT_ID=<client id from step 1>
WEBUI_GOOGLE_CLIENT_SECRET=<client secret from step 1>
```

Then recreate the container so it picks them up:

```
cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d open-webui
```

## 3. Verify

- Open `https://ai-ui.coolestdomain.win/auth` in a private window. A **Continue
  with Google** button should sit beside the Microsoft one.
- Click it. You should reach Google's account chooser, not an error page. A
  `redirect_uri_mismatch` here means step 1.4 does not match exactly.
- Sign in. `ENABLE_OAUTH_SIGNUP=true` and `OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true`
  are already set, so a Google account whose email matches an existing user
  signs into that same account rather than creating a duplicate.

## Rolling it back

Remove the two `.env` lines and recreate `open-webui`. The button disappears;
nothing else changes.

## The other Google login (Lukas's standup item)

Lukas asked for something different: an app **built by the platform** getting a
Google sign-in button for ITS users — *"it adds it to the created app"*.

That is genuinely harder, and not for lack of effort. Each built app gets its own
Supabase project with its own callback (`https://<ref>.supabase.co/auth/v1/callback`),
and **Google does not accept wildcard redirect URIs**. So every app would need a
console visit, which is the opposite of one click.

Three ways out, none free:

- **One shared Google client, callbacks added per app.** Works, but a manual
  console step per app, and Google caps redirect URIs per client.
- **A proxy callback we own.** One registered URI on our domain that forwards to
  the right project. One console step ever, but it puts us in the middle of every
  app's login and we hold the client secret.
- **Ask the app owner for their own Google client.** Honest and unlimited, but it
  is a form to fill in, not one click.

This needs a decision before it needs code. It is also blocked behind a database
existing at all — `tasks.project_supabase` had 0 rows as of 2026-08-05.
