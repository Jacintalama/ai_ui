# Alert Tuning, Discord Notifications & Slack Suppression — Design

**Date:** 2026-03-04
**Status:** Approved
**Origin:** Lukas standup (2026-03-03) — "finish setting up Grafana/Loki, balance logging, set up Discord webhook"

---

## Summary

| # | Task | Scope |
|---|------|-------|
| 1 | Tune Grafana alert rules | Fix false positives in "Container Crash Detected" |
| 2 | Create Discord webhook + Grafana contact point | Auto-create via Discord API, wire to Grafana |
| 3 | Suppress Slack `not_authed` errors | Guard Slack calls when no token configured |
| 4 | Test all Discord `/aiui` commands | End-to-end verification of all 7 subcommands |
| 5 | Fix `setup-alerts.sh` password | Use env var instead of hardcoded `admin:admin` |

n8n upgrade (v2.6.4 → v2.9.0) is assigned to Ralph — not in scope here.

---

## Task 1: Grafana Alert Tuning

### Problem
"Container Crash Detected" alert is firing for `grafana` and `loki` containers. The regex `(?i)(OOMKilled|exit code [1-9]|container died|fatal|segfault)` matches the word "fatal" in normal info-level log lines.

### Solution
1. **Remove `fatal` from regex** — too broad, matches normal log output
2. **Exclude noisy containers** — change container filter from `{container_name=~".+"}` to exclude `grafana|loki`
3. **Updated LogQL:**
   ```
   count_over_time({container_name=~".+", container_name!~"grafana|loki"} |~ "(?i)(OOMKilled|exit code [1-9]|container died|segfault)" [5m])
   ```

### Verification
- All 4 alerts should show `Normal` state after update
- No false positives firing

---

## Task 2: Discord Webhook + Grafana Contact Point

### Architecture
```
Grafana Alert → Notification Policy → Discord Contact Point → Discord Channel Webhook → #alerts channel
```

### Steps
1. **Find a text channel** in "aiui's server" (guild `1475498065518661794`) via Discord API
2. **Create a webhook** in that channel using the bot token
3. **Add Discord contact point** to Grafana via provisioning API
4. **Update notification policy** to route alerts to Discord instead of the dummy email receiver
5. **Send test notification** to verify delivery

### Grafana Contact Point Config
```json
{
  "name": "discord-alerts",
  "type": "discord",
  "settings": {
    "url": "<created-webhook-url>",
    "message": "{{ template \"default.message\" . }}"
  }
}
```

---

## Task 3: Suppress Slack Errors

### Problem
`webhook-handler/handlers/commands.py` line 298 calls `self._slack_client.post_message()` in `_handle_report` without checking if Slack is configured. This produces `not_authed` errors.

### Solution
Add guard: only post to Slack if both `_slack_client` is initialized AND `settings.slack_bot_token` (or equivalent) is non-empty. The existing check `if settings.report_slack_channel and self._slack_client:` isn't sufficient because the client object may exist even without a valid token.

### Files
- `webhook-handler/handlers/commands.py` — add token check in `_handle_report`
- `webhook-handler/config.py` — verify `slack_bot_token` field exists

---

## Task 4: Test Discord Commands

### Test Matrix
| Command | Expected Result |
|---------|----------------|
| `/aiui help` | Shows all available commands |
| `/aiui status` | Shows health of 4 services |
| `/aiui workflows` | Lists 5 active + 5 inactive workflows |
| `/aiui report` | Generates daily report (no Slack error) |
| `/aiui workflow PR Review Automation` | Triggers via webhook path `pr-review`, returns 200 |
| `/aiui ask what is MCP` | Returns AI response from Open WebUI |
| `/aiui pr-review 10` | Fetches PR #10 diff and returns AI review |

### Verification
- All 7 commands return valid responses in Discord
- No errors in webhook-handler logs
- No `not_authed` Slack errors

---

## Task 5: Fix setup-alerts.sh

### Problem
Script has `admin:admin` hardcoded as Basic Auth. Actual password is `$GRAFANA_ADMIN_PASSWORD`.

### Solution
Replace hardcoded password with `${GRAFANA_ADMIN_PASSWORD:-admin}` so it reads from env with fallback.

---

## Out of Scope
- n8n upgrade (Ralph's task — needs Hostinger VPS credentials from Lukas)
- Slack workspace setup (no workspace exists)
- Grafana dashboards (future task)
- New alert rules beyond tuning existing 4
