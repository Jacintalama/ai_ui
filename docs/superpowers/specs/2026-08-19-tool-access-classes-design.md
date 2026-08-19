# Tool access classes: make the tools reachable

Date: 2026-08-19
Status: approved, ready to implement
Scope: mcp-proxy only. Per-user vendor connections are a separate spec.

## Problem

The platform indexes 346 MCP tools. Almost nobody can reach them.

Measured on prod, per user:

| User | Platform role | Tools reachable |
|---|---|---|
| alamajacintg04 | admin | all (in the MCP-Admin group) |
| lherajt | admin | all (in the MCP-Admin group) |
| kimcalicoy24 | user | 56 |
| github@test.com | user | 40 |
| ralphbenitez32 | admin | 4 |
| clidebacalla | admin | 0 |
| alamajacint | user | 0 |
| hello@chain-lightning.com | user | 0 |
| ivandermuega | user | 0 |

Four causes, all in `tenants.get_user_tenants_async` plus its data.

1. **MCP-Admin ignores `enabled`.** The path returns `list(ALL_SERVERS.keys())`,
   all 50 registered servers. Only 13 are enabled. Admins hold grants to 37
   servers that have no container.
2. **There is no default.** An identified user with no group and no
   `user_tenant_access` row resolves to `[]`. That is 4 of the 9 users,
   including a platform admin.
3. **`group_tenant_mapping` points at servers that were never deployed.** It
   grants `linear, atlassian, slack, gitlab, hubspot` (none exist) and omits
   `clickup` (172 tools), `trello` (25) and `n8n` (20).
4. **The tool index holds 48 tools that can never run:** `github-jacintalama`
   (40 tools, registered and indexed, no container in either compose file) and
   `gmail` (8 tools, disabled here because email goes through the native Open
   WebUI tool instead).

Being a platform admin grants no MCP access at all. Only membership in the
`MCP-Admin` group does. That is the whole reason Ralph's main account sees 4
tools while another of his accounts sees everything.

## Two things verified during design that changed the plan

**`scheduler` is cross-user and must not be a default grant.**
`mcp-servers/scheduler/main.py:177` calls `webhook-handler`
`/scheduler/user-jobs`, and that endpoint (`webhook-handler/main.py:1670`)
takes no user parameter and returns every user's jobs. `scheduler_delete_cron_job`
can then delete any of them. Handing these 4 tools to everyone would let any
user list and delete another user's schedules. It needs an explicit grant.

**`filesystem` is safe but shared.** Its volume is `./mcp-data:/data`, a
dedicated scratch directory, not the repo and not `apps/`. It currently holds
0 files. There is no vendor credential, so it is a default grant, but it is one
shared pool: anything one user writes, another can read. Recorded here so the
next person does not discover it by surprise.

## Design

### 1. Access class becomes a property of the server

Add one field to `MCPServerConfig`:

```python
class AccessClass(str, Enum):
    PUBLIC = "public"        # no vendor credential -> any signed-in user
    RESTRICTED = "restricted"  # no vendor credential, but cross-user reach
    SHARED = "shared"        # runs on one shared vendor token -> grant required
```

Chosen over a separate allow-list because "is this safe to hand everyone?" then
lives next to the thing it describes. A list in another file drifts, which is
exactly how cause 3 happened.

Classification of the 13 enabled servers:

| Class | Servers | Tools |
|---|---|---|
| PUBLIC | google-drive 7, calendar 6, filesystem 14, web-search 3, excel 2, dashboard 2, meeting-kb 0 | **34** |
| RESTRICTED | scheduler 4 | 4 |
| SHARED | clickup 172, github 40, trello 25, n8n 20, sonarqube 3 | 260 |

34 + 4 + 260 = 298, which is the indexed tool count on enabled servers.

`api_key_env` cannot derive this. It is uniformly `MCP_API_KEY` on every
server, because that is the proxy's own key for reaching the container, not the
vendor credential. The class has to be declared.

### 2. Access resolution becomes one expression

```
admin:     enabled ∩ everything
non-admin: enabled ∩ (PUBLIC ∪ granted)
```

The `enabled` intersection is applied once, to the return value, so it holds on
every path. That is what fixes cause 1, and it removes the shape that produced
the recent auth hole: one rule written in several places, wrong in some of them.

"admin" here means MCP-Admin group membership **or** Open WebUI admin role
(`db.is_openwebui_admin`, already written and already used by the admin portal).
That is what takes `ralphbenitez32` from 4 tools and `clidebacalla` from 0.

### 3. Data and hygiene

- Repoint `group_tenant_mapping` at servers that exist.
- Delete the `github-jacintalama` registry entry and its 40 index rows.
- Prune index rows whose server is disabled (removes gmail's 8 as well).
- Drop `mcp_proxy.user_server_access`. Its 22 rows are read by no code, and
  they duplicate what the groups already grant while mostly naming disabled
  servers. Nothing real is lost.
- Leave `mcp_proxy.tenant_server_keys` untouched. It is the foundation the
  per-user connections spec will build on.

### 4. Result

Every signed-in user goes to 34 working tools. Both stranded admins gain the
full enabled set. Nobody gains access to a shared vendor token, which is the
rule chosen for the connections work: connect your own, or no access.

## Testing

Following `mcp-proxy/tests/test_meta_access.py`:

- a user with no grants resolves PUBLIC servers and only those
- a user with no grants does not resolve SHARED or RESTRICTED servers
- a disabled server never appears, on the admin path or any other
- an Open WebUI admin resolves the enabled set without MCP-Admin group membership
- an unidentified caller still resolves nothing
- a call-site assertion so a future endpoint cannot re-derive access its own way

Each test is proved to bite by reintroducing the bug it covers.

## Not in this spec

Per-user vendor credentials for ClickUp, Trello, GitHub and Notion. Those need
mcp-proxy to call the vendor REST API directly, because the third-party MCP
containers take their credential from boot-time env and expose no per-call
parameter for it (verified: zero `apikey`/`api_key`/`token`/`credential`
parameters across all 217 ClickUp, Trello and GitHub tool schemas). Separate
spec.
