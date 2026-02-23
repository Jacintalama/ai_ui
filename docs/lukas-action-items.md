# Action Items for Lukas — Credentials Needed

**Last Updated:** 2026-02-20

---

## 1. Discord — Need 2 Items

Bot Token is already saved. Just need:

| Item | Where to find it |
|------|-----------------|
| **Application ID** | discord.com/developers → AIUI app → General Information |
| **Public Key** | Same page, right below Application ID |

Also set **Interactions Endpoint URL** to: `https://ai-ui.coolestdomain.win/webhook/discord` and click Save.

---

## 2. Slack App Setup

Go to **https://api.slack.com/apps** → Create New App → name it `AIUI`

### a) Slash Command
- Slash Commands → Create New Command
  - Command: `/aiui`
  - Request URL: `https://ai-ui.coolestdomain.win/webhook/slack/commands`
  - Short Description: `AI assistant and workflow trigger`
  - Usage Hint: `[ask|pr-review|mcp|workflow|status|report|help] [text]`

### b) OAuth & Permissions
- Bot Token Scopes: `commands`, `chat:write`, `incoming-webhook`
- Install to Workspace → Authorize

### c) Incoming Webhooks
- Toggle ON → Add New Webhook to Workspace → select channel for reports

### d) What to send me:

| Item | Where you found it |
|------|-------------------|
| **Bot User OAuth Token** | OAuth & Permissions page (`xoxb-...`) |
| **Signing Secret** | Basic Information → App Credentials |
| **Webhook URL** | Incoming Webhooks page |
| **Report Channel ID** | Right-click channel → View channel details → bottom |

---

## 3. Email IMAP Credentials

For the email-to-Google Sheets automation.

| Item | Details |
|------|---------|
| **Email provider** | Gmail, Outlook, or other? |
| **Email address** | The inbox to monitor |
| **App Password** | Gmail: myaccount.google.com/apppasswords / Outlook: account.microsoft.com/security |
| **Subject filter keywords** | What triggers the automation? (e.g. `[INVOICE]`, `deployment`) |

---

## 4. Google Sheets Access

1. Create a Google Sheet for email logging
2. Share it with the service account (I'll provide the email)
3. Send me the **spreadsheet URL or ID**

---

## How to Send Credentials Safely

- **WhatsApp** (end-to-end encrypted) — send directly to Jacint
- **1Password / Bitwarden shared vault**
- **Encrypted zip** — send file + password separately


