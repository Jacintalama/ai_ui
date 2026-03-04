# Alert Tuning, Discord Notifications & Slack Suppression — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Tune Grafana alerts to eliminate false positives, create Discord webhook for alert delivery, suppress Slack errors, and verify all Discord commands work end-to-end.

**Architecture:** All changes are config/API calls on the Hetzner server (46.224.193.25) plus one small code fix in `setup-alerts.sh`. Discord webhook is created via Discord API, then registered as a Grafana contact point. No new containers or services.

**Tech Stack:** Grafana provisioning API, Discord REST API, Loki LogQL, bash

---

### Task 1: Tune "Container Crash Detected" Alert Rule

**Files:**
- Modify: `grafana/setup-alerts.sh:166-212` (update LogQL query)
- Server: Update live alert rule via Grafana API

**Step 1: Update the alert rule on the live server**

SSH to root@46.224.193.25 and update the "Container Crash Detected" rule (UID: `dfeidzr3ov56oa`) via Grafana provisioning API. The new LogQL excludes `grafana|loki` and removes `fatal` from the regex:

```bash
curl -s -X PUT \
  -u admin:$GRAFANA_ADMIN_PASSWORD \
  -H "Content-Type: application/json" \
  -d '{
    "folderUID": "error-alerts",
    "ruleGroup": "error-alerts",
    "title": "Container Crash Detected",
    "condition": "C",
    "data": [
      {
        "refId": "A",
        "datasourceUid": "P8E80F9AEF21F6940",
        "model": {
          "expr": "count_over_time({container_name=~\".+\", container_name!~\"grafana|loki\"} |~ \"(?i)(OOMKilled|exit code [1-9]|container died|segfault)\" [5m])",
          "queryType": "range",
          "editorMode": "code"
        },
        "relativeTimeRange": {"from": 300, "to": 0}
      },
      {
        "refId": "B",
        "datasourceUid": "__expr__",
        "model": {
          "type": "reduce",
          "reducer": "last",
          "expression": "A"
        },
        "relativeTimeRange": {"from": 0, "to": 0}
      },
      {
        "refId": "C",
        "datasourceUid": "__expr__",
        "model": {
          "type": "threshold",
          "expression": "B",
          "conditions": [{"evaluator": {"type": "gt", "params": [0]}}]
        },
        "relativeTimeRange": {"from": 0, "to": 0}
      }
    ],
    "for": "0s",
    "labels": {"severity": "critical"},
    "annotations": {
      "summary": "Container crash or OOM kill detected",
      "description": "A container has crashed, been OOM killed, or exited with a non-zero code"
    },
    "noDataState": "OK",
    "execErrState": "OK"
  }' \
  http://172.22.0.21:3000/api/v1/provisioning/alert-rules/dfeidzr3ov56oa
```

Expected: HTTP 200 with updated rule JSON.

**Step 2: Verify all alerts are Normal**

```bash
curl -s -u admin:$GRAFANA_ADMIN_PASSWORD \
  http://172.22.0.21:3000/api/prometheus/grafana/api/v1/alerts | python3 -m json.tool
```

Expected: All alerts in `Normal` or `Normal (NoData)` state. No `Alerting` state.

**Step 3: Update setup-alerts.sh to match**

Edit `grafana/setup-alerts.sh` locally:
- Line 6: Change `AUTH="Authorization: Basic YWRtaW46YWRtaW4="` to use env var
- Line 178: Update LogQL to new query (exclude grafana|loki, remove fatal)

New line 6:
```bash
AUTH="Authorization: Basic $(echo -n "admin:${GRAFANA_ADMIN_PASSWORD:-admin}" | base64)"
```

New line 178 LogQL:
```
count_over_time({container_name=~\".+\", container_name!~\"grafana|loki\"} |~ \"(?i)(OOMKilled|exit code [1-9]|container died|segfault)\" [5m])
```

**Step 4: Commit**

```bash
git add grafana/setup-alerts.sh
git commit -m "fix: tune container crash alert — remove 'fatal', exclude grafana/loki"
```

---

### Task 2: Create Discord Webhook + Grafana Contact Point

**Files:**
- Server-only: Discord API + Grafana API calls

**Step 1: Get available text channels in the Discord guild**

```bash
curl -s -H "Authorization: Bot $DISCORD_BOT_TOKEN" \
  https://discord.com/api/v10/guilds/1475498065518661794/channels | python3 -m json.tool
```

Pick the first text channel (type=0). Note its ID.

**Step 2: Create a webhook in that channel**

```bash
curl -s -X POST \
  -H "Authorization: Bot $DISCORD_BOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Grafana Alerts"}' \
  https://discord.com/api/v10/channels/<CHANNEL_ID>/webhooks
```

Expected: Returns JSON with `url` field — save this URL.

**Step 3: Add Discord contact point to Grafana**

```bash
curl -s -X POST \
  -u admin:$GRAFANA_ADMIN_PASSWORD \
  -H "Content-Type: application/json" \
  -d '{
    "name": "discord-alerts",
    "type": "discord",
    "settings": {
      "url": "<WEBHOOK_URL_FROM_STEP_2>",
      "use_discord_username": true
    },
    "disableResolveMessage": false
  }' \
  http://172.22.0.21:3000/api/v1/provisioning/contact-points
```

Expected: HTTP 202 with UID.

**Step 4: Update notification policy to use Discord**

```bash
curl -s -X PUT \
  -u admin:$GRAFANA_ADMIN_PASSWORD \
  -H "Content-Type: application/json" \
  -d '{
    "receiver": "discord-alerts",
    "group_by": ["alertname"],
    "group_wait": "30s",
    "group_interval": "5m",
    "repeat_interval": "1h"
  }' \
  http://172.22.0.21:3000/api/v1/provisioning/policies
```

**Step 5: Send a test notification**

```bash
curl -s -X POST \
  -u admin:$GRAFANA_ADMIN_PASSWORD \
  -H "Content-Type: application/json" \
  -d '{
    "receivers": [{"name": "discord-alerts", "grafana_managed_receiver_configs": [{"uid": "<UID_FROM_STEP_3>"}]}],
    "alert": {
      "annotations": {"summary": "Test alert from Grafana"},
      "labels": {"alertname": "TestAlert", "severity": "info"}
    }
  }' \
  http://172.22.0.21:3000/api/v1/provisioning/contact-points/<UID>/test
```

Expected: Test message appears in Discord channel.

---

### Task 3: Verify Slack Error Suppression

**Files:** None — existing guards are already correct.

**Step 1: Verify the guards in code**

The `not_authed` error seen by the user comes from inside the **n8n PR Review Automation workflow** (its Slack node has no token), NOT from our webhook-handler code. Our code has proper guards:

- `webhook-handler/main.py:114` — `if settings.slack_bot_token:` before creating SlackClient
- `webhook-handler/handlers/commands.py:372` — `if settings.report_slack_channel and self._slack_client:` before posting
- `webhook-handler/scheduler.py:169` — `if slack_client and slack_channel:` before posting

No code changes needed. The error in the n8n workflow is Ralph's domain (n8n config).

**Step 2: Confirm no Slack errors in webhook-handler logs**

```bash
docker logs webhook-handler 2>&1 | grep -i 'slack\|not_authed' | tail -10
```

Expected: No `not_authed` errors from webhook-handler itself.

---

### Task 4: Test All Discord Slash Commands

**Step 1: Test `/aiui help`**

Type in Discord: `/aiui command:help`
Expected: List of all 8 commands.

**Step 2: Test `/aiui status`**

Type in Discord: `/aiui command:status`
Expected: 4 services listed with healthy/unhealthy status.

**Step 3: Test `/aiui workflows`**

Type in Discord: `/aiui command:workflows`
Expected: 10 workflows listed (5 active, 5 inactive).

**Step 4: Test `/aiui report`**

Type in Discord: `/aiui command:report`
Expected: Daily report with GitHub commits, n8n executions, service health. No `not_authed` error from our code.

**Step 5: Test `/aiui workflow PR Review Automation`**

Type in Discord: `/aiui command:workflow PR Review Automation`
Expected: "Workflow PR Review Automation triggered successfully" with response from n8n.

**Step 6: Test `/aiui ask what is MCP`**

Type in Discord: `/aiui command:ask what is MCP`
Expected: AI response explaining MCP.

**Step 7: Test `/aiui pr-review 10`**

Type in Discord: `/aiui command:pr-review 10`
Expected: AI review of PR #10 with diff analysis.

**Step 8: Verify logs**

```bash
docker logs webhook-handler 2>&1 | grep -i 'discord command' | tail -10
```

Expected: All 7 commands logged with 200 OK responses.

---

### Task 5: Deploy Updated setup-alerts.sh

**Step 1: SCP the updated file to server**

```bash
scp grafana/setup-alerts.sh root@46.224.193.25:/root/proxy-server/grafana/setup-alerts.sh
```

**Step 2: Commit all changes**

```bash
git add grafana/setup-alerts.sh
git commit -m "fix: tune Grafana alerts, add Discord webhook notifications"
```

**Step 3: Push to PR**

```bash
git push proxy-server fix/mcp-network-split
```
