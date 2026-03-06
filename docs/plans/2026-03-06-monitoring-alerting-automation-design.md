# Monitoring & Alerting Automation - Design

**Date:** 2026-03-06
**Status:** Approved

## Problem

Grafana alerts notify Discord that something is wrong, but don't explain why or suggest a fix. Team has to SSH in and read logs manually.

## Solution

When a Grafana alert fires, automatically query Loki for recent error logs, send them to Open WebUI AI for diagnosis, and post the analysis to Discord alongside the alert. Also add an on-demand `/aiui diagnose` command.

## Automatic Flow

```
Grafana alert fires (FIRING status)
  -> POST /webhook/grafana-alerts (already exists)
  -> Extract container_name from alert labels
  -> Query Loki API: last 5 min error logs for that container
  -> Send logs to Open WebUI AI: "Diagnose these errors, suggest a fix"
  -> Post to Discord: original alert + AI diagnosis below it
```

## On-Demand Flow

```
User types: /aiui diagnose [container_name]
  -> Query Loki: last 5 min error logs for that container
  -> If no container specified, query error logs from all containers
  -> Send logs to Open WebUI AI for diagnosis
  -> Post diagnosis back to Discord
```

## Changes

### New: `webhook-handler/clients/loki.py`
- LokiClient class with `query_error_logs(container_name, minutes=5)` method
- Hits `http://loki:3100/loki/api/v1/query_range` with LogQL query
- Query: `{container_name="X"} |~ "(?i)(error|exception|fatal|panic|traceback)"`
- Returns list of log lines (max 50 to keep token usage reasonable)

### Modify: `webhook-handler/config.py`
- Add `loki_url: str = "http://loki:3100"` to Settings

### Modify: `webhook-handler/main.py`
- In `/webhook/grafana-alerts` endpoint, after posting alert to Discord:
  - If status is FIRING, extract container_name from alert labels
  - Call LokiClient to fetch error logs
  - Call OpenWebUIClient to analyze the logs
  - Post AI diagnosis as a follow-up Discord message
- Initialize LokiClient in lifespan

### Modify: `webhook-handler/handlers/commands.py`
- Add "diagnose" to known_commands set
- Add `_handle_diagnose(ctx)` method
- Parse optional container_name from arguments
- Query Loki, run AI analysis, respond with diagnosis

## Loki Query Details

LogQL query for specific container:
```
{container_name="open-webui"} |~ "(?i)(error|exception|fatal|panic|traceback)"
```

LogQL query for all containers:
```
{container_name=~".+"} |~ "(?i)(error|exception|fatal|panic|traceback)"
```

Time range: last 5 minutes
Limit: 50 log lines
Direction: backward (newest first)

## AI Prompt

System: "You are a DevOps diagnostic assistant. Analyze these container error logs and provide: 1) What went wrong (root cause), 2) Impact (what's affected), 3) Suggested fix (specific commands or config changes). Be concise."

User: "Container: {name}\nError logs (last 5 minutes):\n{logs}"

## Discord Output Format

Automatic (after alert):
```
[alert message as before]

AI Diagnosis:
[Root cause]: [explanation]
[Impact]: [what's affected]
[Fix]: [specific suggestion]
```

On-demand:
```
Diagnosis for {container} (last 5 min):
[N errors found]
[Root cause]: [explanation]
[Impact]: [what's affected]
[Fix]: [specific suggestion]
```

## Error Handling

- If Loki is unreachable, skip AI diagnosis, still send the alert
- If no error logs found, post "No recent errors found for {container}"
- If Open WebUI is down, post "AI diagnosis unavailable" with raw log snippet
- If container_name not in alert labels, skip diagnosis for that alert
