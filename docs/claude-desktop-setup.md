# Claude Desktop Setup — AIUI MCP Tools

## 1. Install Claude Desktop

Download from: https://claude.ai/download

Available for macOS, Windows, and Linux.

## 2. Get Your API Key

Ask Jacint for your personal API key. It looks like: `sk-xxxxxxxxxxxxx`

## 3. Configure MCP Connection

### macOS
Open: `~/Library/Application Support/Claude/claude_desktop_config.json`

### Windows
Open: `%APPDATA%\Claude\claude_desktop_config.json`

### Linux
Open: `~/.config/Claude/claude_desktop_config.json`

Add this configuration:

```json
{
  "mcpServers": {
    "aiui": {
      "type": "streamableHttp",
      "url": "https://ai-ui.coolestdomain.win/mcp-remote/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY_HERE"
      }
    }
  }
}
```

Replace `YOUR_API_KEY_HERE` with the API key Jacint gave you.

## 4. Restart Claude Desktop

Close and reopen Claude Desktop. You should see "aiui" in your MCP connections.

## Available Tools

Once connected, you can use these tools directly in Claude Desktop chat:

### Communication
- **Gmail** — search, read, send emails (via aiui.teams@gmail.com)
- **Google Calendar** — create events, send meeting invites, list schedule

### Development
- **GitHub** — repositories, issues, PRs, code search
- **Web Search** — search the internet, save results to Knowledge Base

### Files & Data
- **Google Drive** — browse, search, read files
- **Filesystem** — read/write files on the server
- **Excel Creator** — generate Excel spreadsheets

### Automation
- **n8n Workflows** — trigger and manage automation workflows
- **Scheduler** — create cron jobs for recurring tasks
- **Executive Dashboard** — generate KPI dashboards

## Example Commands

Try these in Claude Desktop:

**Calendar:**
- "Create a standup meeting for tomorrow at 9:30 PM and invite the team"
- "What's on the calendar this week?"
- "Schedule a weekly Friday report meeting at 3 PM"

**Gmail:**
- "Check my inbox for unread emails"
- "Send an email to lukas@straightforwardllc.us about the deployment"

**Web Search:**
- "Search for AI voice bot best practices and save to Knowledge Base"

**GitHub:**
- "List open issues on the ai_ui repository"
- "What were the latest commits?"

## Team Emails

For calendar invites, use these addresses:
- Lukas: lukas@straightforwardllc.us
- Ralph: ralphbenitez30@gmail.com
- Jacint: alamajacintg04@gmail.com
- Clarenz: clidebacalla@gmail.com

## Troubleshooting

**"MCP connection failed"** — Check your API key is correct and the URL has no typos.

**"Tool not found"** — Make sure you restarted Claude Desktop after adding the config.

**"Calendar/Gmail not connected"** — The shared Google account needs OAuth. Ask Jacint to connect it at: `https://ai-ui.coolestdomain.win/calendar/auth/google/start?user_email=aiui.teams@gmail.com`
