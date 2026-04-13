# Multilingual Voice Bot — ElevenLabs Quick Win

**Date:** 2026-04-03
**Status:** Approved
**Approach:** A — Model upgrade + multilingual voice + dashboard config

## Problem

The Discord voice bot (ElevenLabs Conversational AI) only works well in English. It uses `eleven_turbo_v2_5` (32 languages, optimized for English) and an English-only voice ID (`JBFqnCBsd6RMkjVDRZzb`). Users speaking other languages (Tagalog, Dutch, etc.) get poor recognition and English-only responses.

## Goal

Support all languages ElevenLabs offers (up to 74 with v3). The bot should auto-detect the user's language and respond in that same language, maintaining consistent voice identity across languages.

## Design

### Part 1: Code Changes

**`webhook-handler/config.py`** — Update two defaults:

| Setting | Current | New |
|---|---|---|
| `elevenlabs_model_id` | `eleven_turbo_v2_5` | `eleven_multilingual_v2` |
| `elevenlabs_voice_id` | `JBFqnCBsd6RMkjVDRZzb` | Multilingual-capable voice ID (select from ElevenLabs library) |

No changes to `voice_bot.py` — the audio pipeline is language-agnostic. ElevenLabs handles language detection in their ASR.

### Part 2: ElevenLabs Dashboard Changes (Manual)

On the agent dashboard for the configured `agent_id`:

1. **Voice** — Select a multilingual voice that maintains identity across languages
2. **Model** — Switch to `eleven_multilingual_v2` (or v3 if available on plan)
3. **System prompt** — Add: "Always respond in the same language the user is speaking. If the user switches languages, follow them. Do not default to English unless the user speaks English."
4. **First message** — Keep English or make language-neutral (bot switches once user speaks)

### Part 3: Server Deployment

Update `.env` on Hetzner (`/root/proxy-server/.env`):

```
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
ELEVENLABS_VOICE_ID=<chosen multilingual voice ID>
```

Rebuild:

```bash
docker compose -f docker-compose.unified.yml up -d --build webhook-handler
```

## What This Gets You

- 29 languages (multilingual v2) or 74 languages (v3) including Tagalog, Dutch, German, Spanish, Japanese
- Auto-detection — speak any language, bot responds in that language
- Same voice identity across all languages
- Zero architecture changes — same pipeline, same Discord integration
- Same cost ($0.08-0.10/min)

## Known Limitations

- Mid-sentence language mixing (Taglish, Spanglish) may confuse ASR
- Tool/command names in webhook handler are English — LLM agent handles translation internally
- Voice pronunciation quirks possible for numbers/acronyms in some languages
- Language is fixed per conversation turn, not mid-sentence

## Future Enhancements (if needed)

- **Approach B:** Pass explicit `language` parameter to `AsyncConversation` for better ASR accuracy
- **Approach C:** Dynamic language detection + voice switching per session
- **Gemini Live API migration:** For 90+ languages at $0.02/min (requires new WebSocket bridge)
