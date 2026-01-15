# Community Pipelines Research

**Date:** 2026-01-07
**Purpose:** Research community pipelines for N8N and Anthropic integration

---

## N8N Pipeline

### Overview

N8N is a workflow automation tool. The N8N Pipeline allows Open WebUI to trigger N8N workflows from chat conversations.

### Recommended Function

**[N8N Pipeline Function by owndev](https://openwebui.com/f/owndev/n8n_pipeline)** (v2.2.0)

| Property | Value |
|----------|-------|
| **Author** | owndev |
| **Version** | 2.2.0 |
| **License** | MIT |
| **Source** | [GitHub](https://github.com/owndev/Open-WebUI-Functions) |

### Features

- Server-Sent Events (SSE) streaming support
- Configurable AI Agent tool usage display (3 verbosity levels)
- Robust error handling
- Status updates with collapsible think elements
- Streaming and non-streaming modes

### Installation

1. Go to Admin Panel → Functions
2. Click "Import from Community"
3. Search for "N8N Pipeline" by owndev
4. Click "Get" → "Import to WebUI"

### Configuration

| Setting | Description |
|---------|-------------|
| `N8N_WEBHOOK_URL` | Your N8N webhook URL |
| `STREAMING` | Enable/disable streaming responses |
| `VERBOSITY` | Tool display level (minimal/compact/detailed) |

### Alternative N8N Functions

| Function | Author | Description |
|----------|--------|-------------|
| [N8N Pipe](https://openwebui.com/f/coleam/n8n_pipe) | Cole Medin | Simple N8N agent pipe |
| [N8N Pipe NG](https://github.com/sboily/open-webui-n8n-pipe) | sboily | Async version |
| [Combined AI and N8N](https://openwebui.com/f/rabbithole/combined_ai_and_n8n) | rabbithole | Multi-provider + N8N |

### Integration Guide

For detailed setup: [Integrating n8n with Open WebUI](https://www.pondhouse-data.com/blog/integrating-n8n-with-open-webui)

---

## Anthropic Pipeline (Claude Models)

### Overview

The Anthropic Pipeline enables Claude models (Opus, Sonnet, Haiku) in Open WebUI.

### Recommended Function

**[Anthropic Function by justinrahb](https://openwebui.com/f/justinrahb/anthropic)** (v0.2.5)

| Property | Value |
|----------|-------|
| **Author** | justinrahb, christian-taillon |
| **Version** | 0.2.5 |
| **License** | MIT |
| **Min WebUI Version** | 0.3.17 |

### Features

- All Claude models supported (3, 3.5, 3.7, 4)
- Extended thinking support
- Streaming responses with thinking visualization
- Image/PDF processing
- 128K output tokens for Claude 3.7 and 4

### Installation

1. Go to Admin Panel → Functions
2. Click "Import from Community"
3. Search for "Anthropic" by justinrahb
4. Click "Get" → "Import to WebUI"

Or direct link: https://openwebui.com/f/justinrahb/anthropic

### Configuration

| Setting | Description |
|---------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |

### Available Models After Installation

| Model | Description |
|-------|-------------|
| claude-3-opus | Most capable, best for complex tasks |
| claude-3-sonnet | Balanced performance and cost |
| claude-3-haiku | Fastest, most affordable |
| claude-3.5-sonnet | Enhanced Sonnet version |
| claude-3.7-sonnet | Latest Sonnet with extended thinking |
| claude-4-opus | Latest Opus (2025) |
| claude-4-sonnet | Latest Sonnet (2025) |

### Alternative Anthropic Functions

| Function | Author | Description |
|----------|--------|-------------|
| [Anthropic Balaxxe CoT](https://openwebui.com/f/ncks024/anthropic_balaxxe_cot) | ncks024 | Chain of thought support |
| [Claude 4.5 with Thinking](https://openwebui.com/f/niknub/claude_4_5_with_thinking) | niknub | Thinking visualization |
| [Anthropic Claude Thinking 96K](https://openwebui.com/f/lavantien/anthropic_claude_thinking_96k) | lavantien | Extended context |

---

## How to Install Community Functions

### Method 1: Import from Community (Recommended)

1. Open WebUI Admin Panel → Functions
2. Click "+ Add Function" → "Import from Community"
3. Search for the function
4. Click "Get" → "Open WebUI URL" → "Import to WebUI"

### Method 2: Manual Import

1. Copy the function code from GitHub or community
2. Admin Panel → Functions → "+ Add Function"
3. Paste the code and save

### Method 3: Direct URL

Use URLs like:
```
https://openwebui.com/f/justinrahb/anthropic
```

Click "Get" button directly.

---

## Other Useful Community Functions

| Category | Function | Description |
|----------|----------|-------------|
| **AI Providers** | Google Gemini | Gemini Pro/Ultra models |
| **AI Providers** | Perplexity | Search-augmented AI |
| **AI Providers** | Deepseek | Chinese AI models |
| **AI Providers** | Grok | xAI models |
| **Automation** | Zapier | Workflow automation |
| **Search** | Tavily | AI-powered search |
| **Code** | Code Interpreter | Execute Python code |

### Community Functions Directory

Browse all functions: https://openwebui.com/functions

---

## Recommendations for Client

### Priority 1: Anthropic Pipeline
- **Why:** Client mentioned needing Claude models
- **Action:** Install `justinrahb/anthropic` function
- **Cost:** Requires Anthropic API key (~$15/1M tokens for Opus)

### Priority 2: N8N Pipeline
- **Why:** Client mentioned workflow automation needs
- **Action:** Install `owndev/n8n_pipeline` function
- **Requirements:** Running N8N instance with webhook

### Additional Considerations

1. **Multi-provider comparison:** Install multiple AI provider functions to compare responses
2. **Extended thinking:** Use functions with thinking visualization for complex reasoning
3. **Caching:** Some functions include intelligent caching to reduce API costs

---

## References

- [Open WebUI Functions Directory](https://openwebui.com/functions)
- [Open WebUI Functions Documentation](https://docs.openwebui.com/getting-started/quick-start/starting-with-functions/)
- [N8N Pipeline GitHub](https://github.com/owndev/Open-WebUI-Functions)
- [Anthropic Function](https://openwebui.com/f/justinrahb/anthropic)
- [N8N Integration Guide](https://www.pondhouse-data.com/blog/integrating-n8n-with-open-webui)
