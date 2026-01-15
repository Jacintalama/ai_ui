# Demo Script: How Multi-Tenant Auth Works

**For:** Lukas Herajt
**By:** Jacint Alama
**Purpose:** Show exactly how users get filtered access to MCP tools

---

## The Big Picture (30 seconds)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   USER                    OPEN WEBUI              MCP PROXY             │
│                                                                         │
│  ┌─────────┐             ┌─────────┐            ┌─────────────┐        │
│  │  Joel   │ ──login──►  │         │ ──email──► │             │        │
│  │ @google │             │  Open   │  +groups   │  MCP Proxy  │        │
│  └─────────┘             │  WebUI  │            │  (Filter)   │        │
│                          │         │            │             │        │
│  ┌─────────┐             │         │            │   ┌─────┐   │        │
│  │  Mike   │ ──login──►  │         │ ──email──► │   │GitHub│  │        │
│  │ @msft   │             │         │  +groups   │   ├─────┤   │        │
│  └─────────┘             └─────────┘            │   │Files │  │        │
│                                                 │   ├─────┤   │        │
│                                                 │   │More..│  │        │
│                                                 │   └─────┘   │        │
│                                                 └─────────────┘        │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Demo

### Step 1: User Clicks "Sign in with Microsoft"

```
┌─────────────────────────────────────────┐
│         Open WebUI Login Page           │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │      Sign in with Microsoft     │   │  ← User clicks this
│  └─────────────────────────────────┘   │
│                                         │
│           ── or ──                      │
│                                         │
│  Email: [____________________]          │
│  Pass:  [____________________]          │
│         [      Sign In       ]          │
│                                         │
└─────────────────────────────────────────┘
```

---

### Step 2: Microsoft Authenticates User

```
┌─────────────────────────────────────────┐
│         Microsoft Login Page            │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │  🏢 Sign in to your account     │   │
│  │                                 │   │
│  │  Email: joel@google.com         │   │
│  │  Pass:  ********                │   │
│  │                                 │   │
│  │  [        Sign In        ]      │   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

**Microsoft returns this data to Open WebUI:**

```json
{
  "email": "joel@google.com",
  "name": "Joel Alama",
  "groups": ["MCP-GitHub", "MCP-Google"]
}
```

---

### Step 3: Open WebUI Creates/Updates User

```
┌─────────────────────────────────────────────────────────────┐
│                    Open WebUI Database                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Users Table:                                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ ID  │ Name        │ Email            │ Groups          │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ 1   │ Joel Alama  │ joel@google.com  │ MCP-GitHub,     │ │
│  │     │             │                  │ MCP-Google      │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ 2   │ Mike Test   │ mike@microsoft.. │ MCP-Microsoft   │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ 3   │ Admin       │ admin@company..  │ MCP-Admin       │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**No manual work needed! Groups sync automatically from Entra ID.**

---

### Step 4: User Uses Chat with MCP Tools

When Joel asks a question that needs tools:

```
┌─────────────────────────────────────────────────────────────┐
│  Open WebUI Chat                                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Joel: "Search for repositories about Python"               │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  🔧 Using tool: github.search_repositories             │ │
│  │  Query: "Python"                                       │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  AI: Found 1,234 repositories about Python...               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

### Step 5: Open WebUI Sends Request to MCP Proxy

**Open WebUI adds user info to the request headers:**

```http
GET /github/search_repositories HTTP/1.1
Host: mcp-proxy:8000

# These headers are added automatically:
X-OpenWebUI-User-Email: joel@google.com
X-OpenWebUI-User-Name: Joel Alama
X-User-Groups: MCP-GitHub,MCP-Google
```

---

### Step 6: MCP Proxy Checks Permissions

```python
# Inside MCP Proxy (simplified)

def check_access(user_email, user_groups, requested_server):

    # Group to Server mapping
    GROUP_ACCESS = {
        "MCP-GitHub": ["github"],
        "MCP-Google": ["google-drive", "google-calendar"],
        "MCP-Microsoft": ["sharepoint", "teams"],
        "MCP-Admin": ["ALL SERVERS"],
    }

    # Check if user's groups allow access
    for group in user_groups:
        if requested_server in GROUP_ACCESS[group]:
            return ALLOWED ✅

    return DENIED ❌
```

**Example checks:**

| User | Groups | Requests | Result |
|------|--------|----------|--------|
| Joel | MCP-GitHub, MCP-Google | `/github` | ✅ Allowed |
| Joel | MCP-GitHub, MCP-Google | `/sharepoint` | ❌ Denied |
| Mike | MCP-Microsoft | `/github` | ❌ Denied |
| Mike | MCP-Microsoft | `/sharepoint` | ✅ Allowed |
| Admin | MCP-Admin | `/anything` | ✅ Allowed |

---

## Live Demo: Test Commands

### Test 1: Joel (Google User) - Has GitHub Access

```bash
# Joel can access GitHub tools
curl -X GET "http://localhost:30800/github" \
  -H "X-OpenWebUI-User-Email: joel@google.com" \
  -H "X-User-Groups: MCP-GitHub,MCP-Google"

# Response: 200 OK + 26 GitHub tools
```

```bash
# Joel CANNOT access Filesystem tools
curl -X GET "http://localhost:30800/filesystem" \
  -H "X-OpenWebUI-User-Email: joel@google.com" \
  -H "X-User-Groups: MCP-GitHub,MCP-Google"

# Response: 403 Forbidden
```

---

### Test 2: Mike (Microsoft User) - No GitHub Access

```bash
# Mike CANNOT access GitHub tools
curl -X GET "http://localhost:30800/github" \
  -H "X-OpenWebUI-User-Email: mike@microsoft.com" \
  -H "X-User-Groups: MCP-Microsoft"

# Response: 403 Forbidden
```

---

### Test 3: Admin - Full Access

```bash
# Admin can access EVERYTHING
curl -X GET "http://localhost:30800/github" \
  -H "X-OpenWebUI-User-Email: admin@company.com" \
  -H "X-User-Groups: MCP-Admin"

# Response: 200 OK + 26 GitHub tools

curl -X GET "http://localhost:30800/filesystem" \
  -H "X-OpenWebUI-User-Email: admin@company.com" \
  -H "X-User-Groups: MCP-Admin"

# Response: 200 OK + 14 Filesystem tools
```

---

## Visual: Access Control Matrix

```
                    │ GitHub │ Filesystem │ Google │ Microsoft │
────────────────────┼────────┼────────────┼────────┼───────────┤
MCP-GitHub group    │   ✅   │     ❌     │   ❌   │    ❌     │
MCP-Filesystem group│   ❌   │     ✅     │   ❌   │    ❌     │
MCP-Google group    │   ❌   │     ❌     │   ✅   │    ❌     │
MCP-Microsoft group │   ❌   │     ❌     │   ❌   │    ✅     │
MCP-Admin group     │   ✅   │     ✅     │   ✅   │    ✅     │
────────────────────┴────────┴────────────┴────────┴───────────┘
```

---

## How to Add a New User (After Setup)

### Old Way (Manual - BAD)
```
1. User requests access
2. Admin edits code in tenants.py
3. Admin redeploys MCP Proxy
4. User can now access
5. Repeat 15,000 times... 😫
```

### New Way (Automatic - GOOD)
```
1. User logs in with Microsoft
2. Account created automatically
3. Admin adds user to group in Entra ID
4. User instantly has access
5. Done! No code changes needed 🎉
```

---

## Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    HOW IT ALL WORKS                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. User logs in with Microsoft                                │
│                    │                                            │
│                    ▼                                            │
│  2. Entra ID returns: email + groups                           │
│                    │                                            │
│                    ▼                                            │
│  3. Open WebUI syncs user + groups to database                 │
│                    │                                            │
│                    ▼                                            │
│  4. User requests MCP tool                                     │
│                    │                                            │
│                    ▼                                            │
│  5. Open WebUI sends request + headers to MCP Proxy            │
│     Headers: email, groups                                     │
│                    │                                            │
│                    ▼                                            │
│  6. MCP Proxy checks: Is user's group allowed?                 │
│                    │                                            │
│           ┌───────┴───────┐                                    │
│           ▼               ▼                                    │
│         YES ✅          NO ❌                                   │
│      Return tools    Return 403                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Questions?

**Q: What if a user is in multiple groups?**
A: They get access to ALL tools from ALL their groups combined.

**Q: What if a user is in no groups?**
A: They can use Open WebUI but won't see any MCP tools.

**Q: How fast does group sync happen?**
A: Instantly on login. If you add a user to a group in Entra ID, they get access on next login.

**Q: Can we customize which groups map to which tools?**
A: Yes! It's configured in `tenants.py` - we can add any mapping you need.
