#!/bin/bash
# Grafana Alert Rules Setup
# Run inside grafana container: docker exec grafana sh /etc/grafana/provisioning/setup-alerts.sh

GRAFANA_URL="http://localhost:3000"
AUTH="Authorization: Basic YWRtaW46YWRtaW4="
CT="Content-Type: application/json"

# Helper function
post() {
  wget -q -O- --header="$AUTH" --header="$CT" --post-data="$1" "$GRAFANA_URL$2"
}

echo "=== Creating Alert Rules ==="

# Rule 1: HTTP 500 Errors (Critical)
post '{
  "folderUID": "error-alerts",
  "ruleGroup": "error-alerts",
  "title": "HTTP 500 Errors Detected",
  "condition": "C",
  "data": [
    {
      "refId": "A",
      "datasourceUid": "P8E80F9AEF21F6940",
      "model": {
        "expr": "count_over_time({container_name=\"api-gateway\"} |~ \"status[=: ]5[0-9]{2}\" [5m])",
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
        "conditions": [{"evaluator": {"type": "gt", "params": [5]}}]
      },
      "relativeTimeRange": {"from": 0, "to": 0}
    }
  ],
  "for": "1m",
  "labels": {"severity": "critical"},
  "annotations": {
    "summary": "API Gateway returning HTTP 500 errors",
    "description": "More than 5 HTTP 500 errors detected in the last 5 minutes"
  },
  "noDataState": "OK",
  "execErrState": "OK"
}' "/api/v1/provisioning/alert-rules"

echo ""

# Rule 2: High Error Rate (Warning)
post '{
  "folderUID": "error-alerts",
  "ruleGroup": "error-alerts",
  "title": "High Error Rate",
  "condition": "C",
  "data": [
    {
      "refId": "A",
      "datasourceUid": "P8E80F9AEF21F6940",
      "model": {
        "expr": "count_over_time({container_name=~\".+\"} |~ \"(?i)(error|exception|traceback|panic)\" [5m])",
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
        "conditions": [{"evaluator": {"type": "gt", "params": [20]}}]
      },
      "relativeTimeRange": {"from": 0, "to": 0}
    }
  ],
  "for": "2m",
  "labels": {"severity": "warning"},
  "annotations": {
    "summary": "High error rate across services",
    "description": "More than 20 error-level log entries in the last 5 minutes"
  },
  "noDataState": "OK",
  "execErrState": "OK"
}' "/api/v1/provisioning/alert-rules"

echo ""

# Rule 3: Auth Failure Spike (Warning)
post '{
  "folderUID": "error-alerts",
  "ruleGroup": "error-alerts",
  "title": "Auth Failure Spike",
  "condition": "C",
  "data": [
    {
      "refId": "A",
      "datasourceUid": "P8E80F9AEF21F6940",
      "model": {
        "expr": "count_over_time({container_name=~\"api-gateway|open-webui\"} |~ \"(?i)(unauthorized|forbidden|401|403)\" [5m])",
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
        "conditions": [{"evaluator": {"type": "gt", "params": [10]}}]
      },
      "relativeTimeRange": {"from": 0, "to": 0}
    }
  ],
  "for": "2m",
  "labels": {"severity": "warning"},
  "annotations": {
    "summary": "Authentication failure spike detected",
    "description": "More than 10 auth failures (401/403) in the last 5 minutes"
  },
  "noDataState": "OK",
  "execErrState": "OK"
}' "/api/v1/provisioning/alert-rules"

echo ""

# Rule 4: Container Crash (Critical)
post '{
  "folderUID": "error-alerts",
  "ruleGroup": "error-alerts",
  "title": "Container Crash Detected",
  "condition": "C",
  "data": [
    {
      "refId": "A",
      "datasourceUid": "P8E80F9AEF21F6940",
      "model": {
        "expr": "count_over_time({container_name=~\".+\"} |~ \"(?i)(OOMKilled|exit code [1-9]|container died|fatal|segfault)\" [5m])",
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
}' "/api/v1/provisioning/alert-rules"

echo ""
echo "=== Alert Rules Created ==="
