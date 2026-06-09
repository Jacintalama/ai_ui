# Recruiting Outreach — Operator Setup Guide

**Last Updated:** 2026-06-09

One-time setup required before the recruiting outreach agent can run. The agent lives in the **tasks** container and fans out to n8n for email delivery and Google Sheets logging.

---

## 1. GitHub Personal Access Token

The agent calls the GitHub REST API to search for candidate profiles. Without a token the rate limit is 60 req/hr; with one it rises to 5,000 req/hr.

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens) and click **Generate new token (classic)**.
2. Give it a descriptive name (e.g. `io-recruiting-outreach`).
3. **No scopes needed** for public user search — leave all boxes unchecked and click **Generate token**.
4. Copy the token (shown only once).
5. SSH into the server and append it to `.env`:

   ```bash
   ssh root@46.224.193.25
   echo 'GITHUB_TOKEN=ghp_yourTokenHere' >> /root/proxy-server/.env
   ```

   > **Never commit `.env`.** The server's `.env` is the only authoritative copy of production secrets.

6. Redeploy the tasks service to pick up the new variable:

   ```bash
   ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --no-deps tasks"
   ```

The token is inherited by the Claude subprocess the tasks container spawns, so no further wiring is needed **on the default `local` agent backend**.

> **If `AGENT_BACKEND=remote`:** the agent runs on a separate VM and only `AIUI_AGENT_EFFORT` / `IO_USER_JWT` are forwarded over SSH (`SendEnv`) — `GITHUB_TOKEN` is **not**. In that case also add `GITHUB_TOKEN=...` to the **agent VM's** `~/.env`, or the GitHub calls fall back to the unauthenticated 60 req/hr limit and will likely be throttled mid-run. On the default `local` backend (no `AGENT_BACKEND` override) this does not apply.

---

## 2. n8n Workflow

The tasks service POSTs candidate batches to the n8n webhook at:

```
https://n8n.srv1041674.hstgr.cloud/webhook/recruiting-outreach
```

Override this default with `N8N_WEBHOOK_BASE` in `.env` if the n8n host changes.

### Import and configure the workflow

1. Open the n8n UI and go to **Workflows → Import from file**.
2. Import `n8n-workflows/recruiting-outreach.json` from this repo.
3. **Gmail credential** — open the workflow and click the Gmail node. Bind the OAuth credential for the recruiting sender account. If it doesn't exist yet, create it under **Credentials → Add credential → Gmail OAuth2**.
4. **Google Sheets credential** — click each Google Sheets node (there are two: one reads, one appends). Bind the same Google Sheets OAuth2 credential to both. If it doesn't exist, create it under **Credentials → Add credential → Google Sheets OAuth2**.
5. **Target spreadsheet** — in both Google Sheets nodes set:
   - `documentId`: the ID from your spreadsheet URL (`https://docs.google.com/spreadsheets/d/<ID>/edit`)
   - Sheet/tab name: `Outreach`
6. **Respond node** — set the `sheet_url` parameter to the full URL of the spreadsheet (shown to operators after a run completes).
7. Click **Activate** (toggle in the top-right corner). The workflow must be active for the webhook to accept POSTs.

---

## 3. Google Sheet

1. Create a new Google Sheet (or reuse an existing one).
2. Add a header row in the first row with these exact columns (order matters):

   ```
   date | name | github_url | email | status | job_title
   ```

3. Name the tab `Outreach` (must match the sheet name set in the n8n nodes above).
4. Share the sheet with the Google account used for the n8n Google Sheets OAuth credential (Editor access).

---

## 4. Discord / Slack Channel Panel (optional)

Once the workflow is running, the recruiting panel can be posted to a Discord `#recruiting` channel (or equivalent Slack channel). This is wired up by a setup script in Task 11. To enable it, set `RECRUITING_CHANNEL_ID` in `.env` to the target Discord channel ID and redeploy webhook-handler:

```bash
echo 'RECRUITING_CHANNEL_ID=123456789012345678' >> /root/proxy-server/.env
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml up -d --no-deps webhook-handler"
```

---

## Verification

After completing steps 1–3, trigger a test run from the tasks panel UI or via the API and confirm:

- The n8n execution log shows the webhook received the payload.
- A new row appears in the `Outreach` tab of the Google Sheet.
- The recruiting sender Gmail account shows the outreach email in **Sent**.
