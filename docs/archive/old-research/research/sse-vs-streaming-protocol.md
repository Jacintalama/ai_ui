# SSE vs Streaming Protocol Research

**Date:** 2026-01-07
**Purpose:** Understanding protocol compatibility between Atlassian MCP and Open WebUI

---

## The Problem (As Client Described)

> "Atlassian MCP uses SSE, Open WebUI uses Streaming - they don't communicate"

## Research Findings

### MCP Transport Types

The Model Context Protocol supports **three transport mechanisms**:

| Transport | Description | Status |
|-----------|-------------|--------|
| **stdio** | Standard input/output streams | ✅ Current standard |
| **Streamable HTTP** | HTTP POST/GET with optional SSE | ✅ Current standard (2025-06-18) |
| **SSE** | Server-Sent Events only | ⚠️ DEPRECATED (2024-11-05) |

**Key Insight:** SSE is deprecated! The newer "Streamable HTTP" transport uses HTTP POST/GET and can optionally use SSE for streaming responses.

### Atlassian MCP Server Status

According to [Atlassian Support](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/getting-started-with-the-atlassian-remote-mcp-server/):

- **Old endpoint:** `/sse` (deprecated)
- **New endpoint:** `/mcp` (Streamable HTTP)
- Atlassian **recommends updating** clients to use `/mcp` instead of `/sse`

**This means:** Atlassian has ALREADY updated to the newer protocol!

### Open WebUI MCP Support

According to [Open WebUI MCP Documentation](https://docs.openwebui.com/features/mcp/):

| Feature | Support |
|---------|---------|
| Native MCP Support | ✅ Added September 2025 |
| Streamable HTTP | ✅ Full MCP 2025-06-18 compliance |
| OAuth 2.1 | ✅ Supported |
| Per-user authentication | ✅ Supported |

**Open WebUI now natively supports Streamable HTTP MCP servers!**

---

## Solution: mcpo Proxy

[mcpo](https://github.com/open-webui/mcpo) is Open WebUI's official MCP-to-OpenAPI proxy that supports ALL transport types:

### Supported Transports in mcpo

```bash
# stdio transport (default)
mcpo --port 8000 -- uvx mcp-server-time

# SSE transport
mcpo --port 8000 --server-type "sse" -- http://127.0.0.1:8001/sse

# Streamable HTTP transport
mcpo --port 8000 --server-type "streamable-http" -- http://127.0.0.1:8002/mcp
```

### How mcpo Works

```
┌─────────────┐      ┌──────────┐      ┌─────────────────┐
│  Open WebUI │ ──→  │   mcpo   │ ──→  │   MCP Server    │
│  (OpenAPI)  │ ←──  │  (proxy) │ ←──  │ (stdio/SSE/HTTP)│
└─────────────┘      └──────────┘      └─────────────────┘
```

mcpo converts ANY MCP transport to OpenAPI endpoints that Open WebUI understands.

---

## Atlassian Integration Options

### Option A: Use Native MCP Support (Recommended)

Since Open WebUI v0.6+ supports native Streamable HTTP:

1. Go to Admin → Settings → External Tools
2. Add Atlassian MCP Server directly:
   - URL: `https://mcp.atlassian.com/v1/mcp`
   - Auth: OAuth 2.1
   - No mcpo needed!

### Option B: Use mcpo with SSE (Legacy)

If you need to use the legacy SSE endpoint:

```bash
# Wrap Atlassian SSE endpoint with mcpo
mcpo --port 8003 \
  --server-type "sse" \
  --header '{"Authorization": "Bearer YOUR_TOKEN"}' \
  -- https://mcp.atlassian.com/v1/sse
```

### Option C: Use mcp-atlassian Package

The [mcp-atlassian](https://pypi.org/project/mcp-atlassian/) Python package supports both transports:

```bash
# Install
pip install mcp-atlassian

# Run with stdio (default)
python -m mcp_atlassian

# Run with SSE
python -m mcp_atlassian --transport sse --port 8000
```

Then wrap with mcpo for Open WebUI.

---

## Why the "Protocol Mismatch" is No Longer a Problem

| Year | Situation |
|------|-----------|
| 2024 | SSE was standard, Open WebUI didn't support it → Problem |
| 2025 | Streamable HTTP becomes standard, Open WebUI adds native support → Solved |
| 2026 | Both sides support Streamable HTTP, mcpo handles legacy → No problem |

### What Changed:

1. **Atlassian** migrated from `/sse` to `/mcp` (Streamable HTTP)
2. **Open WebUI** added native MCP support (September 2025)
3. **mcpo** was created to bridge ANY transport type

---

## Recommendation for Client

### For New Integrations:
Use **native MCP support** in Open WebUI with Atlassian's `/mcp` endpoint.

### For Legacy SSE Servers:
Use **mcpo with `--server-type sse`** to wrap the SSE endpoint.

### Summary:

| Approach | Complexity | When to Use |
|----------|------------|-------------|
| Native MCP | Low | Atlassian, GitHub, modern MCP servers |
| mcpo (stdio) | Medium | Local CLI-based MCP servers |
| mcpo (SSE) | Medium | Legacy SSE-only servers |
| mcpo (streamable-http) | Medium | Remote HTTP MCP servers |

---

## References

- [MCP Transports Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [Open WebUI MCP Documentation](https://docs.openwebui.com/features/mcp/)
- [mcpo GitHub Repository](https://github.com/open-webui/mcpo)
- [Atlassian MCP Server](https://github.com/atlassian/atlassian-mcp-server)
- [mcp-atlassian PyPI](https://pypi.org/project/mcp-atlassian/)
- [Open WebUI Native MCP Discussion](https://github.com/open-webui/open-webui/discussions/16238)

---

## Conclusion

**The protocol mismatch problem has been solved by the ecosystem:**

1. SSE is deprecated → Use Streamable HTTP
2. Open WebUI supports native MCP → No proxy needed for modern servers
3. mcpo exists for legacy support → All transports covered

**Client Action Items:**
1. Update Atlassian integration to use `/mcp` endpoint (not `/sse`)
2. Use Open WebUI's native MCP support for Atlassian
3. Use mcpo only for legacy servers that haven't migrated
