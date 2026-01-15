# MCP Group Header Forwarding - Test Guide

**Date:** January 15, 2026
**Feature:** Forward user groups from Open WebUI to MCP Proxy

---

## Prerequisites

1. Modified Open WebUI deployed (with headers.py and middleware.py changes)
2. `ENABLE_FORWARD_USER_INFO_HEADERS=true` in Open WebUI environment
3. MCP Proxy running with current auth.py and tenants.py

---

## Test Cases

### Test 1: Verify Headers Are Sent

**Steps:**
1. Login to Open WebUI as a user with Entra ID groups
2. Open browser DevTools → Network tab
3. Start a chat that uses an MCP tool (e.g., GitHub tool)
4. Find the request to MCP Proxy
5. Check request headers

**Expected Headers:**
```
X-OpenWebUI-User-Name: Steve
X-OpenWebUI-User-Id: abc123
X-OpenWebUI-User-Email: steve@highspring.com
X-OpenWebUI-User-Role: user
X-OpenWebUI-User-Groups: Tenant-Google,Tenant-AcmeCorp
```

**Status:** [ ] PASS / [ ] FAIL

---

### Test 2: Verify MCP Proxy Receives Groups

**Steps:**
1. Check MCP Proxy logs:
   ```bash
   kubectl logs -f deployment/mcp-proxy -n open-webui
   ```
2. Look for group-based access messages:
   ```
   [GROUP-BASED] steve@highspring.com groups=['Tenant-Google', 'Tenant-AcmeCorp'] -> github: True
   ```

**Expected:** Groups from header are logged and used for filtering

**Status:** [ ] PASS / [ ] FAIL

---

### Test 3: Single Tenant Access

**User:** User with only `Tenant-Google` group

**Steps:**
1. Login as user with single tenant group
2. Check available MCP tools
3. Verify only Google-related tools are visible

**Expected:** Only tools mapped to `MCP-Google` group are available

**Status:** [ ] PASS / [ ] FAIL

---

### Test 4: Multi-Tenant Access

**User:** User with `Tenant-Google` AND `Tenant-AcmeCorp` groups

**Steps:**
1. Login as user with multiple tenant groups
2. Check available MCP tools
3. Verify tools from both tenants are visible

**Expected:** Tools from both mapped groups are available

**Status:** [ ] PASS / [ ] FAIL

---

### Test 5: Admin Access

**User:** User with `MCP-Admin` group

**Steps:**
1. Login as admin user
2. Check available MCP tools
3. Verify all tools are visible

**Expected:** All MCP tools are available (admin bypass)

**Status:** [ ] PASS / [ ] FAIL

---

### Test 6: No Groups (Fallback)

**User:** User without any Entra ID groups

**Steps:**
1. Login as user without groups
2. Check if fallback to email-based access works
3. Check MCP Proxy logs for `[HARDCODED]` messages

**Expected:** Falls back to USER_TENANT_ACCESS mapping

**Status:** [ ] PASS / [ ] FAIL

---

## Verification Commands

### Check Open WebUI Logs
```bash
kubectl logs -f statefulset/open-webui -n open-webui | grep -i "groups\|mcp"
```

### Check MCP Proxy Logs
```bash
kubectl logs -f deployment/mcp-proxy -n open-webui | grep -i "groups\|access"
```

### Curl Test (Direct MCP Proxy)
```bash
# Test with groups header
curl -H "X-OpenWebUI-User-Email: steve@highspring.com" \
     -H "X-OpenWebUI-User-Groups: Tenant-Google,Tenant-AcmeCorp" \
     http://localhost:30800/tools
```

---

## Test Results Summary

| Test | Description | Result |
|------|-------------|--------|
| 1 | Headers sent from Open WebUI | [ ] |
| 2 | MCP Proxy receives groups | [ ] |
| 3 | Single tenant filtering | [ ] |
| 4 | Multi-tenant access | [ ] |
| 5 | Admin bypass | [ ] |
| 6 | No groups fallback | [ ] |

---

## Troubleshooting

### Headers Not Appearing
- Check `ENABLE_FORWARD_USER_INFO_HEADERS=true` is set
- Verify modified Open WebUI is deployed (not original image)
- Check middleware.py has the new group forwarding code

### Groups Not Filtering
- Verify group names in header match `ENTRA_GROUP_TENANT_MAPPING` keys
- Check MCP Proxy logs for access decisions
- Ensure auth.py reads `X-OpenWebUI-User-Groups` header

### Fallback Not Working
- Check USER_TENANT_ACCESS in tenants.py has user's email
- Verify email case matches (lowercase comparison)

---

*Created: January 15, 2026*
