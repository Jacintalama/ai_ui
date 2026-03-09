# n8n Gmail & Google Sheets OAuth Setup Guide

> **Who:** Any developer with access to the n8n server and the team Gmail account
> **Time:** ~15 minutes
> **Prereq:** Access to `admin@coolestdomain.win` Gmail and n8n server

---

## What This Enables

Once configured, these Discord/Slack commands will work:

- `/aiui email` — Fetches the 10 most recent unread emails, returns AI-formatted summary
- `/aiui sheets daily` — Writes a daily activity report to a Google Sheet
- `/aiui sheets errors` — Writes an error report to a Google Sheet

Right now they fail because **Google OAuth credentials are not connected** in n8n.

---

## Part 1: Create a Google Cloud OAuth App

You only need to do this once. Both Gmail and Sheets will use the same OAuth app.

### Step 1: Go to Google Cloud Console

1. Open https://console.cloud.google.com
2. Sign in with `admin@coolestdomain.win`

### Step 2: Create a Project (if you don't have one)

1. Click the project dropdown (top bar) → **New Project**
2. Name it: `AIUI Automation`
3. Click **Create**
4. Select the new project from the dropdown

### Step 3: Enable APIs

1. Go to **APIs & Services** → **Library** (left sidebar)
2. Search for **Gmail API** → Click it → Click **Enable**
3. Go back to Library
4. Search for **Google Sheets API** → Click it → Click **Enable**

### Step 4: Create OAuth Credentials

1. Go to **APIs & Services** → **Credentials** (left sidebar)
2. Click **+ Create Credentials** → **OAuth client ID**
3. If prompted to configure consent screen:
   - Choose **External** (or Internal if using Google Workspace)
   - App name: `AIUI Automation`
   - User support email: `admin@coolestdomain.win`
   - Authorized domains: `coolestdomain.win`
   - Developer contact: `admin@coolestdomain.win`
   - Click **Save and Continue** through scopes (skip for now)
   - Add test user: `admin@coolestdomain.win`
   - Click **Save and Continue** → **Back to Dashboard**
4. Now create the credential:
   - Go to **Credentials** → **+ Create Credentials** → **OAuth client ID**
   - Application type: **Web application**
   - Name: `n8n OAuth`
   - Authorized redirect URIs: Add this exact URL:
     ```
     https://n8n.srv1041674.hstgr.cloud/rest/oauth2-credential/callback
     ```
   - Click **Create**
5. **Copy the Client ID and Client Secret** — you'll need them in n8n

---

## Part 2: Set Up Gmail Credential in n8n

### Step 1: Open n8n

1. Go to https://n8n.srv1041674.hstgr.cloud
2. Login: `admin@coolestdomain.win` / `N8nAdmin2026`

### Step 2: Create Gmail OAuth Credential

1. Click **Credentials** in the left sidebar (key icon)
2. Click **+ Add Credential**
3. Search for **Gmail OAuth2 API** → Select it
4. Fill in:
   - **Credential Name:** `Gmail - admin@coolestdomain.win`
   - **Client ID:** (paste from Google Cloud Console)
   - **Client Secret:** (paste from Google Cloud Console)
5. Click **Sign in with Google**
6. A Google popup will appear — sign in with `admin@coolestdomain.win`
7. Grant permission to read emails
8. You should see "Connected" or a green checkmark
9. Click **Save**

### Step 3: Connect Credential to Workflow

1. Go to **Workflows** in the left sidebar
2. Open **gmail-inbox-summary**
3. Click the **Gmail** node (blue email icon)
4. Under **Credential to connect with**, select `Gmail - admin@coolestdomain.win`
5. Click **Save** (on the node)
6. Click **Save** (top right, save the workflow)
7. Make sure the workflow is **Active** (toggle in top right)

### Step 4: Test It

1. In Discord, type: `/aiui email`
2. You should get a summary of the 10 most recent unread emails
3. If it fails, check the n8n execution log (click **Executions** in left sidebar)

---

## Part 3: Set Up Google Sheets Credential in n8n

### Step 1: Create Google Sheets OAuth Credential

1. Go to **Credentials** in n8n (left sidebar)
2. Click **+ Add Credential**
3. Search for **Google Sheets OAuth2 API** → Select it
4. Fill in:
   - **Credential Name:** `Google Sheets - admin@coolestdomain.win`
   - **Client ID:** (same Client ID from Part 1)
   - **Client Secret:** (same Client Secret from Part 1)
5. Click **Sign in with Google**
6. Grant permission to edit spreadsheets
7. Click **Save**

### Step 2: Create the Google Sheet

1. Go to https://sheets.google.com (sign in as `admin@coolestdomain.win`)
2. Click **+ Blank spreadsheet**
3. Name it: `AIUI Reports`
4. In Row 1, add these column headers:
   ```
   A1: Date    B1: Type    C1: Detail    D1: Extra
   ```
5. Copy the **Sheet ID** from the URL — it's the long string between `/d/` and `/edit`:
   ```
   https://docs.google.com/spreadsheets/d/THIS_IS_THE_SHEET_ID/edit
   ```
6. Save this ID — you need it for the next step

### Step 3: Connect Credential to Workflow

1. Go to **Workflows** in n8n
2. Open **sheets-report**
3. Click the **Google Sheets** node
4. Under **Credential to connect with**, select `Google Sheets - admin@coolestdomain.win`
5. Under **Document ID**, replace `CONFIGURE_SHEET_ID` with your actual Sheet ID
6. **Sheet Name** should be `Sheet1` (default, matches what we created)
7. Click **Save** (on the node)
8. Click **Save** (top right, save the workflow)
9. Make sure the workflow is **Active**

### Step 4: Test It

1. In Discord, type: `/aiui sheets daily`
2. Check the Google Sheet — a new row should appear with today's date
3. If it fails, check the n8n execution log

---

## Troubleshooting

### "Workflow not found" error
- Make sure the workflow is **Active** (toggle on in top right of workflow editor)
- Make sure the webhook node has the correct `webhookId` field (it should already be set)
- Try deactivating and reactivating the workflow

### "401 Unauthorized" from Google
- The OAuth token may have expired — go to Credentials, click the credential, click **Sign in with Google** again
- Make sure the Gmail/Sheets APIs are enabled in Google Cloud Console

### "CONFIGURE_SHEET_ID" error
- You forgot to replace the placeholder with the actual Google Sheet ID in the Sheets workflow

### "Test user" limitation
- If your Google OAuth app is in "Testing" mode, only users listed as test users can authenticate
- Go to Google Cloud Console → OAuth consent screen → Add `admin@coolestdomain.win` as test user
- Or publish the app (requires Google review for sensitive scopes)

### Redirect URI mismatch
- The redirect URI in Google Cloud Console must exactly match:
  ```
  https://n8n.srv1041674.hstgr.cloud/rest/oauth2-credential/callback
  ```
- No trailing slash, must be HTTPS

---

## Quick Reference

| Item | Value |
|------|-------|
| n8n URL | https://n8n.srv1041674.hstgr.cloud |
| n8n Login | `admin@coolestdomain.win` / `N8nAdmin2026` |
| Gmail account | `admin@coolestdomain.win` |
| Google Cloud Console | https://console.cloud.google.com |
| OAuth redirect URI | `https://n8n.srv1041674.hstgr.cloud/rest/oauth2-credential/callback` |
| Gmail workflow | `gmail-inbox-summary` (reads 10 unread emails) |
| Sheets workflow | `sheets-report` (appends rows to Sheet1) |
| Sheets placeholder | Replace `CONFIGURE_SHEET_ID` with real Sheet ID |
| Discord commands | `/aiui email`, `/aiui sheets daily`, `/aiui sheets errors` |
