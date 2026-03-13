# ElevenLabs Voice Discord Bot — Design Document

**Date:** 2026-03-13
**Status:** Approved

## Problem

Users want to interact with the AIUI platform via voice in Discord instead of typing slash commands. All `/aiui` commands should be accessible through natural speech.

## Solution

ElevenLabs hosted Conversational AI agent + thin Discord voice bridge container.

## Architecture

```
User speaks in Discord voice channel
        │
        ▼
┌─────────────────┐     audio stream      ┌──────────────────────┐
│  voice-bridge   │ ◄──── WebSocket ────► │  ElevenLabs Agent    │
│  (Discord bot)  │     (11Labs SDK)       │  (hosted cloud)      │
│  ~50MB RAM      │                        │                      │
└─────────────────┘                        │  LLM: Claude (API)   │
                                           │  Voice: 11Labs TTS   │
                                           │  STT: 11Labs built-in│
                                           │                      │
                                           │  Tools (webhooks):   │
                                           │  ├─ /aiui status     │
                                           │  ├─ /aiui security   │
                                           │  ├─ /aiui sheets     │
                                           │  ├─ /aiui pr-review  │
                                           │  └─ ... all commands │
                                           └──────────┬───────────┘
                                                      │
                                              HTTP webhook calls
                                                      │
                                                      ▼
                                           ┌──────────────────────┐
                                           │  ai-ui.coolestdomain │
                                           │  .win/webhook/voice  │
                                           │  (Caddy → webhook-   │
                                           │   handler)           │
                                           └──────────────────────┘
```

### Three components:

1. **ElevenLabs Agent** (cloud) — Configured on 11Labs dashboard with Claude as LLM, webhook tools for each `/aiui` command
2. **voice-bridge container** (Docker) — Lightweight Python bot: joins Discord voice channel, pipes audio to/from 11Labs WebSocket
3. **New `/webhook/voice` endpoint** (webhook-handler) — Receives tool calls from 11Labs agent, routes to existing CommandRouter, returns results

## ElevenLabs Agent Configuration

Configured on the 11Labs dashboard (not in code):

- **Name:** AIUI Voice Assistant
- **LLM:** Claude (via ANTHROPIC_API_KEY)
- **Voice:** 11Labs voice library selection
- **System prompt:** "You are AIUI, a voice assistant for a software team. Users speak commands. Map their intent to the appropriate tool, execute it, and summarize the result conversationally. For long results, give a brief spoken summary and mention the full output is in the text channel."

### Webhook Tools

| Tool Name | Webhook URL | Description |
|-----------|-------------|-------------|
| `status` | `https://ai-ui.coolestdomain.win/webhook/voice/status` | Check health of all services |
| `ask` | `.../webhook/voice/ask` | Ask an AI question |
| `security` | `.../webhook/voice/security` | Run security audit on a repo |
| `health` | `.../webhook/voice/health` | Code health assessment |
| `deps` | `.../webhook/voice/deps` | Check outdated dependencies |
| `license` | `.../webhook/voice/license` | License compliance check |
| `pr-review` | `.../webhook/voice/pr-review` | Review a GitHub PR |
| `sheets` | `.../webhook/voice/sheets` | Write report to Google Sheets |
| `analyze` | `.../webhook/voice/analyze` | Extract business requirements |
| `rebuild` | `.../webhook/voice/rebuild` | Research and generate rebuild plan |
| `workflows` | `.../webhook/voice/workflows` | List n8n workflows |
| `report` | `.../webhook/voice/report` | End-of-day report |

### Behavior

User says "check if our dependencies are up to date" → 11Labs agent (Claude brain) maps to `deps` tool → calls webhook → gets JSON → Claude summarizes → 11Labs speaks summary → full report posted to text channel.

## Voice Bridge Container

**Purpose:** Lightweight Discord bot that bridges voice audio to/from 11Labs.

**Dependencies:** `discord.py[voice]`, `elevenlabs`, `PyNaCl`, `ffmpeg`

**Behavior:**
1. User types `/aiui voice` → bot joins their voice channel
2. Posts "Joined voice. Speak naturally — I'm listening." in text channel
3. Opens 11Labs WebSocket session
4. Pipes Discord audio → 11Labs (user speech)
5. Pipes 11Labs audio → Discord (agent response)
6. Posts full text results to text channel
7. Leaves after 5 min idle or `/aiui voice stop`

**Docker footprint:** ~80-100MB image, ~50MB runtime RAM. No database, no volume, stateless.

**Env vars:**

| Var | Source |
|-----|--------|
| `DISCORD_BOT_TOKEN` | Discord Developer Portal |
| `ELEVENLABS_API_KEY` | 11Labs dashboard |
| `ELEVENLABS_AGENT_ID` | 11Labs agent config |
| `WEBHOOK_HANDLER_URL` | `http://webhook-handler:8086` (internal) |

**Concurrency:** One voice session at a time (mutex, 3.8GB RAM constraint).

## Webhook Handler Changes

### New endpoint: `/webhook/voice/{command}`

```
POST /webhook/voice/security
Body: {"owner": "TheLukasHenry", "repo": "proxy-server"}

Response: {
  "spoken_summary": "Security audit complete. Found 2 medium risks...",
  "full_result": "🔒 **Security Audit**\n\n...(full markdown)...",
  "post_to_text_channel": true
}
```

**How it works:**
- 11Labs agent calls webhook with parameters extracted from speech
- Authenticates via shared secret (`VOICE_WEBHOOK_SECRET` header)
- Creates `CommandContext` with `platform: "voice"`
- Routes through existing `CommandRouter.execute()`
- Returns JSON: `spoken_summary` (for voice) + `full_result` (for text channel)

**Changes to existing code:**
- `webhook-handler/main.py` — Add `/webhook/voice/{command}` route
- `webhook-handler/handlers/commands.py` — Add voice-aware respond callback
- `Caddyfile` — No change needed (`/webhook/*` already routes)

## Discord Bot Setup

**Discord Developer Portal (one-time):**
- Enable Privileged Intents: Server Members, Message Content, Voice States
- Bot permissions: Connect, Speak, Use Voice Activity
- Register `/aiui voice` slash command with options: `join` | `stop`

## Changes Summary

| File | Change |
|------|--------|
| `voice-bridge/main.py` | **New** — Discord bot + 11Labs WebSocket bridge |
| `voice-bridge/Dockerfile` | **New** — python:3.11-slim + ffmpeg + PyNaCl |
| `voice-bridge/requirements.txt` | **New** — discord.py[voice], elevenlabs, PyNaCl |
| `webhook-handler/main.py` | **Modify** — Add `/webhook/voice/{command}` route |
| `webhook-handler/handlers/commands.py` | **Modify** — Voice-aware respond callback |
| `docker-compose.unified.yml` | **Modify** — Add voice-bridge service |

**What stays the same:**
- All existing `/aiui` commands
- CommandRouter logic
- claude-analyzer, n8n, MCP proxy
- Single PostgreSQL on Open WebUI

**External setup (manual, one-time):**
- Create 11Labs account + agent on dashboard
- Configure webhook tools → `ai-ui.coolestdomain.win/webhook/voice/*`
- Enable Discord bot voice intents
- Add `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `VOICE_WEBHOOK_SECRET` to `.env`

## Estimates

- ~150 lines voice-bridge Python
- ~60 lines new webhook endpoint
- ~30 lines docker-compose additions
- Cost: ~$0.10/min voice, $22/mo Creator plan (250 mins included)

## Constraints

- 3.8GB RAM server — voice bridge is lightweight (~50MB), audio processing offloaded to 11Labs cloud
- Single database (PostgreSQL on Open WebUI) — voice bridge is stateless, no DB needed
- One voice session at a time (mutex)
