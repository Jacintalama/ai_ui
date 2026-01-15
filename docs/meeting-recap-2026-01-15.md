# Meeting Recap - January 15, 2026

**Attendees:** Lukas Herajt, Team
**Topics:** Open WebUI Update, Architecture Decisions, Priorities

---

## Key Announcements

### 1. Open WebUI Major Update (v0.6.43 → v0.7)

Lukas updated both the AIUI repo and deployed environment to the new version.

**New Features:**
- Improved MCP server setup and error handling
- **Smart Router** for tool calling (similar to ChatGPT's approach)
  - Decides on-the-spot whether to call a web service or use a tool
  - Better handling of multiple tool calls
  - Smarter decision-making about which tool to invoke

**Impact:** Should significantly improve how the AI decides what tools to use and when.

### 2. MCP Tools Working in Production

> "On the MCP tools list, yes, it comes from the MCP tools, from the production server, that's perfect."

MCP tools are now confirmed working from the production server.

---

## Architecture Decisions

### Database Strategy

| Current | Target | Reason |
|---------|--------|--------|
| SQLite | **PostgreSQL** | Production-ready, better for multi-tenant |
| ChromaDB | **PGVector** | Single database for everything |

**Lukas's Preference:**
- Use PostgreSQL with PGVector (vector database built into Postgres)
- One database containing everything (simpler architecture)
- Avoid separate databases for vectors and relational data

### Redis Integration

**Purpose:**
- Session management
- Workspace tracking
- Chat session persistence
- **Tenant data separation** (keeps data separate by remembering which chat belongs to which tenant)

**Setup:**
```bash
docker compose down
docker compose up
```

**Note:** Redis is useful for multi-tenant architecture - it helps keep track of different workspaces, chats, and tenants.

---

## Priorities (Ordered)

| Priority | Focus Area | Status |
|----------|------------|--------|
| **1** | Make it useful (integrations, pipelines) | Current Focus |
| **2** | Redis for session/tenant separation | In Progress |
| **3** | Entra ID setup | In Progress |
| **4** | HTTP servers setup | Next |
| **5** | Observability, logging, dashboards | Future |
| **6** | Kubernetes scaling | Later (have someone for this) |

### Key Quote:
> "Currently the priority is to make it very useful, you know, like be integrated and have like the pipelines integrated... Kubernetes are good for scaling, however, we have someone that figures out scaling, so we don't need to kind of spend crazy amount of time with Kubernetes. But we need to kind of make it communicate with different services or make it do cool stuff."

---

## Observability (Future)

**For Leadership:**
- CEOs/CTOs like seeing graphs and usage metrics
- Build dashboards showing how things are being used

**Timing:**
- Not immediate priority
- Focus on usefulness first
- Add observability after core functionality is stable

> "I feel like currently the priority is to make it very useful... afterwards, then it would be a good time to make it like observable and have some good logging for debugging and build some nice dashboards."

---

## Community Tools & Pipelines

**Approach:**
- Use community tools/functions/pipelines for inspiration
- Consider using them directly if they fit
- Learn from how others are implementing things

---

## Technical Summary

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ARCHITECTURE DIRECTION                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐           │
│  │  Open WebUI │     │   Redis     │     │  PostgreSQL │           │
│  │    v0.7     │────▶│  Sessions   │────▶│  + PGVector │           │
│  │ Smart Router│     │  Tenants    │     │  All Data   │           │
│  └─────────────┘     └─────────────┘     └─────────────┘           │
│         │                                                           │
│         ▼                                                           │
│  ┌─────────────────────────────────────────────────────────┐       │
│  │                    MCP Proxy                             │       │
│  │  - 18 servers configured                                 │       │
│  │  - Entra ID group-based access                          │       │
│  │  - Multi-tenant isolation                               │       │
│  └─────────────────────────────────────────────────────────┘       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Action Items

### Immediate
- [ ] Complete Entra ID setup
- [ ] Set up HTTP servers for Tier 1 MCP integrations
- [ ] Configure Redis for session management

### Short-term
- [ ] PR changes for Redis integration
- [ ] Migrate from SQLite to PostgreSQL
- [ ] Set up PGVector for vector storage

### Future
- [ ] Build observability dashboards
- [ ] Add logging for debugging
- [ ] Usage metrics for leadership

---

## Key Decisions Made

1. **Database:** PostgreSQL + PGVector (not SQLite + ChromaDB)
2. **Sessions:** Redis for tenant separation
3. **Priority:** Usefulness > Observability > Scaling
4. **Scaling:** Delegate to infrastructure team, focus on integrations
5. **Open WebUI:** Updated to v0.7 for smart router feature

---

*Meeting Notes: January 15, 2026*
*Recorded by: Lukas Herajt*
