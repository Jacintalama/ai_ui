# PR: Secure OAuth Token Validation for MCP Proxy

**Branch:** `feature/multi-tenant-mcp-groups`
**Date:** January 15, 2026
**Status:** Ready for Review

## Summary

This PR implements secure OAuth token validation for the MCP Proxy, replacing header-based authentication with cryptographically secure Microsoft OAuth validation + database lookup for tenant access.

**Key Security Improvement:** Headers can be faked → OAuth tokens are signed by Microsoft and cannot be forged.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AUTHENTICATION FLOW                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  User logs in with Microsoft (consumers tenant - personal accounts)      │
│                              ↓                                           │
│  Open WebUI receives OAuth token from Microsoft                          │
│                              ↓                                           │
│  Open WebUI sends token to MCP Proxy (Authorization: Bearer <token>)     │
│                              ↓                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      MCP PROXY                                    │   │
│  │                                                                   │   │
│  │  1. Extract token from Authorization header                       │   │
│  │  2. Fetch Microsoft's public keys (JWKS endpoint)                │   │
│  │  3. Validate token signature (cryptographic verification)         │   │
│  │  4. Check issuer, audience, expiry                               │   │
│  │  5. Extract user email from token claims                         │   │
│  │  6. Lookup tenant access in PostgreSQL database                  │   │
│  │  7. Filter MCP tools based on user's tenant access               │   │
│  │                                                                   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Security Comparison

| Aspect | Headers (Old) | OAuth + Database (New) |
|--------|---------------|------------------------|
| Can email be faked? | Yes | No - signed by Microsoft |
| Can groups/tenants be faked? | Yes | No - stored in our database |
| Validation method | None (trust header) | Cryptographic signature |
| Source of identity | Untrusted header | Microsoft identity platform |
| Source of permissions | Untrusted header | Our PostgreSQL database |
| Production ready | No | Yes |

## Implementation Details

### New Files

1. **`mcp-proxy/db.py`** - Async PostgreSQL module for tenant lookups
2. **`mcp-proxy/token_validator.py`** - Microsoft OAuth token validation

### Modified Files

3. **`mcp-proxy/mcp_server.py`** - Integrated OAuth + database lookup
4. **`kubernetes/mcp-proxy-deployment.yaml`** - Added DATABASE_URL and MICROSOFT_CLIENT_ID

### Database Schema

```sql
CREATE TABLE user_tenant_access (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    access_level VARCHAR(50) DEFAULT 'read',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_email, tenant_id)
);
```

### Sample Data

| user_email | tenant_id | access_level |
|------------|-----------|--------------|
| alamajacintg04@gmail.com | Tenant-Google | admin |
| alamajacintg04@gmail.com | github | read |
| alamajacintg04@gmail.com | filesystem | read |
| alamajacintg04@gmail.com | atlassian | read |
| steve@highspring.com | Tenant-Google | admin |
| steve@highspring.com | Tenant-AcmeCorp | admin |

## Commits

| Commit | Description |
|--------|-------------|
| `00075e7` | Added cryptography dependency |
| `2143ceb` | Created token_validator.py module |
| `faa2859` | Integrated OAuth validation into MCP server |
| `09cb034` | Added Entra ID env vars (later replaced) |
| `7f745cf` | Updated secrets template |
| `dc4956c` | Implemented database-backed OAuth authentication |

## Environment Variables

### MCP Proxy Pod

```
MICROSOFT_CLIENT_ID=031ce4f1-d328-4861-8ca1-92ad9506cb6f
MICROSOFT_CLIENT_TENANT_ID=consumers
DATABASE_URL=postgresql://openwebui:***@postgresql:5432/openwebui
```

## Deployment Status

- **Docker Image:** `mcp-proxy:v9-database` (tagged as `mcp-proxy:local`)
- **Kubernetes:** Deployed and running
- **Database Table:** Created with sample data
- **Pod Status:** Running (1/1 Ready)

## Testing Checklist

- [x] Docker image builds successfully
- [x] Container starts without errors
- [x] Database table created
- [x] Environment variables configured
- [x] Kubernetes deployment successful
- [x] Health checks passing
- [ ] OAuth login flow (requires Microsoft OAuth button on Open WebUI)
- [ ] End-to-end tool filtering test

## Known Issues

1. **Microsoft OAuth button not showing on Open WebUI login page**
   - Environment variables are correctly set
   - May need Open WebUI restart or additional configuration
   - Backend (MCP Proxy) is ready to receive OAuth tokens

## How to Test OAuth Flow

Once Microsoft OAuth button appears:

1. Click "Login with Microsoft" on Open WebUI
2. Sign in with Microsoft personal account (outlook.com, hotmail.com)
3. Open chat, type: "list my servers"
4. MCP Proxy should:
   - Validate OAuth token (logs: `[OAUTH] Validated user: email`)
   - Lookup tenants in database (logs: `[DATABASE] User email has access to: [...]`)
   - Return tools filtered by user's tenant access

## Admin Actions

### Add User Tenant Access

```sql
INSERT INTO user_tenant_access (user_email, tenant_id, access_level)
VALUES ('newuser@outlook.com', 'github', 'read');
```

### View All Access

```sql
SELECT * FROM user_tenant_access ORDER BY user_email;
```

### Revoke Access

```sql
DELETE FROM user_tenant_access
WHERE user_email = 'user@example.com' AND tenant_id = 'github';
```

## Next Steps

1. Verify Microsoft OAuth button appears on Open WebUI (may need restart)
2. Test end-to-end OAuth flow with real Microsoft login
3. Add more users to `user_tenant_access` table as needed
