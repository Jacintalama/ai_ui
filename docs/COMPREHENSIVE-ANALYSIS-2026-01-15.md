# Comprehensive Analysis: Multi-Tenant MCP Authentication System

**Date:** January 15, 2026
**Analyst:** Claude Code
**Scope:** Full review of documentation, code, and meeting recaps

---

## What's Working Well

### 1. Core Authentication Flow - VERIFIED TODAY
- `__oauth_token__` approach (Lukas's preference) is working
- Database-backed access control functioning correctly
- Admin sees 3 servers, Microsoft user sees 2 servers (as configured)

### 2. Architecture Alignment
- Simple design per Lukas's requirements
- PostgreSQL single database (no sharding complexity)
- Functions over Tool Servers (proper auth forwarding)

### 3. Security Model
- JWT validation in auth.py
- X-Auth-Source header indicates authentication method
- Database lookup provides server-side access control

---

## What's Lacking / Gaps Identified

### 1. MCP Server Coverage: 18/70 (26%)

```
Current:  atlassian, github, filesystem + ~15 disabled
Missing:  52 servers (74%)
Blockers: API keys not configured
```

- Lukas mentioned wanting Datadog, Grafana, Snyk integration
- Many servers disabled waiting for API credentials

### 2. Entra ID Group Configuration - NOT DONE

```
Required in Azure Portal:
├── Create groups: MCP-GitHub, MCP-Filesystem, MCP-Admin, etc.
├── Assign users to groups
├── Configure token claims to include groups
└── Handle "groups overage" (>200 groups → Graph API)
```

- Current testing uses direct database entries, not actual Entra groups
- `kimcalicoy24@gmail.com` is personal Microsoft account (no Entra groups)

### 3. Groups Overage Handling - NOT IMPLEMENTED

```python
# mcp_entra_token_auth.py line 47-52 shows the gap:
if "_claim_sources" in token_data:
    # Groups overage - need to fetch from Graph API
    # This is NOT implemented yet
    pass
```

- Enterprise with 15,000 employees likely has >200 groups
- Need Microsoft Graph API integration

### 4. Production CORS - Still `*`

```python
# main.py currently has:
allow_origins=["*"]  # TODO: Production should be specific domain
```

### 5. Observability/Logging - Minimal

- Lukas said: "Useful first, observability later"
- Current: Basic `[DB]`, `[AUTH]`, `[TENANTS]` print statements
- Future: Needs structured logging, metrics

---

## Potential Issues

### Issue 1: Personal Microsoft Accounts Don't Have Entra Groups

```
kimcalicoy24@gmail.com → Personal account
                       → No 'groups' claim in token
                       → Falls back to email-based DB lookup only
```

- This works for testing but won't represent enterprise scenario
- Need test accounts from actual Entra ID tenant

### Issue 2: Token Decoding Without Verification

```python
# mcp_entra_token_auth.py:
def decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload WITHOUT verification -
    Open WebUI already validated the token"""
```

- Relies on Open WebUI having validated the token
- If someone bypasses Open WebUI, tokens aren't verified at MCP Proxy
- Current mitigation: X-Auth-Source header + JWT validation in auth.py

### Issue 3: Database Schema Dependencies

```sql
-- Required tables (from db.py):
user_tenant_access (user_email, tenant_id, access_level)
group_tenant_mapping (group_name, tenant_id)
```

- These tables must exist in PostgreSQL
- No migration scripts documented
- Manual setup required

### Issue 4: MCP-Admin Group Logic Inconsistency

```python
# tenants.py line 155-165:
if "MCP-Admin" in user.entra_groups:
    return list(ALL_SERVERS.keys())  # Returns ALL servers

# But ENABLED_SERVERS might have servers disabled
```

- MCP-Admin bypasses enabled/disabled check
- Could expose disabled servers to admins

### Issue 5: Race Condition in Connection Pool

```python
# db.py:
async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:  # Not thread-safe
        _pool = await asyncpg.create_pool(...)
```

- Multiple concurrent requests could create multiple pools
- Should use asyncio.Lock

### Issue 6: Error Handling in Function

```python
# mcp_entra_token_auth.py - Many places have:
except Exception as e:
    return f"Error: {str(e)}"
```

- Exposes internal errors to users
- Should have sanitized error messages for production

---

## Priority Action Items

| Priority | Item | Effort |
|----------|------|--------|
| HIGH | Create Entra ID groups in Azure Portal | Low |
| HIGH | Get test accounts from actual Entra tenant | Low |
| MEDIUM | Implement groups overage (Graph API) | Medium |
| MEDIUM | Add database migration scripts | Low |
| MEDIUM | Configure remaining 52 MCP servers | High (API keys) |
| LOW | Update CORS for production | Low |
| LOW | Add structured logging | Medium |
| LOW | Fix connection pool race condition | Low |

---

## Alignment with Lukas's Requirements

From meeting-recap-2026-01-15.md:

| Requirement | Status | Notes |
|-------------|--------|-------|
| "Use `__oauth_token__`" | DONE | Implemented today |
| "Keep it simple" | DONE | No complex sharding |
| "Database-backed access" | DONE | Working with PostgreSQL |
| "Useful first" | DONE | Core flow working |
| "Observability later" | DEFERRED | As requested |
| "15,000 employees" | PARTIAL | Groups overage not handled |

---

## Architecture Flow (Current)

```
User → Open WebUI → MCP Entra Token Auth (Function)
                           │
                           ▼
                    Uses __oauth_token__
                           │
                           ▼
                    Decodes JWT claims
                    (email, groups)
                           │
                           ▼
                    MCP Proxy receives request
                    with X-Auth-Source: entra-token
                           │
                           ▼
                    Database lookup:
                    1. Check group_tenant_mapping
                    2. Check user_tenant_access
                           │
                           ▼
                    Returns authorized servers only
```

---

## Test Results Summary

| Test | Status | Result |
|------|--------|--------|
| Admin account (alamajacintg04@gmail.com) | PASS | 3 servers (atlassian, github, filesystem) |
| Microsoft OAuth (kimcalicoy24@gmail.com) | PASS | 2 servers (github, filesystem) |
| Tool Server removal | PASS | Deleted from Admin Settings |
| Function visibility | PASS | Changed to Public |

---

## Bottom Line

**Working:** Core multi-tenant authentication with database-backed access control.

**Critical Gaps:**
1. No actual Entra ID groups configured (using direct DB entries)
2. Groups overage for enterprise scale not implemented
3. Only 26% of planned MCP servers enabled

**Immediate Next Steps:**
1. Create Entra ID groups in Azure Portal
2. Get real enterprise test accounts (not personal Microsoft)
3. Test with actual group-based access flow
4. Configure more MCP server API keys

The foundation is solid, but enterprise-scale features (groups overage, full server catalog) need work before 15,000 employee rollout.

---

*Generated: January 15, 2026*
