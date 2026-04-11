# Multilingual Voice Bot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable the Discord voice bot to understand and respond in any language (74+ languages) by switching to ElevenLabs multilingual model and voice.

**Architecture:** Config-only change — update default model ID and voice ID in `webhook-handler/config.py`, add the new env vars to `.env.example`, then deploy. Agent system prompt update is a manual dashboard step.

**Tech Stack:** ElevenLabs Conversational AI (eleven_multilingual_v2), Python/Pydantic settings, Docker Compose

---

### Task 1: Update ElevenLabs model default in config.py

**Files:**
- Modify: `webhook-handler/config.py:56-57`

**Step 1: Change the model ID default**

In `webhook-handler/config.py`, change line 57:

```python
# Old
elevenlabs_model_id: str = "eleven_turbo_v2_5"

# New
elevenlabs_model_id: str = "eleven_multilingual_v2"
```

**Step 2: Change the voice ID default**

In `webhook-handler/config.py`, change line 55:

```python
# Old
elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"

# New
elevenlabs_voice_id: str = "pFZP5JQG7iQjIQuC4Bku"
```

Note: `pFZP5JQG7iQjIQuC4Bku` is "Lily" — a multilingual voice. The actual voice used in production is controlled by the ElevenLabs agent dashboard + `.env` override, so this default just ensures new setups get a multilingual voice out of the box.

**Step 3: Verify config loads correctly**

Run:
```bash
cd webhook-handler && python -c "from config import settings; print(settings.elevenlabs_model_id, settings.elevenlabs_voice_id)"
```

Expected: `eleven_multilingual_v2 pFZP5JQG7iQjIQuC4Bku`

**Step 4: Commit**

```bash
git add webhook-handler/config.py
git commit -m "feat: switch ElevenLabs defaults to multilingual v2 model and voice"
```

---

### Task 2: Add model/voice env vars to .env.example

**Files:**
- Modify: `.env.example:183-185`

**Step 1: Add the new env vars**

After `ELEVENLABS_AGENT_ID=`, add the model and voice ID vars:

```bash
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=
# Multilingual model: eleven_multilingual_v2 (29 langs) or eleven_v3 (74 langs)
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
# Voice ID — use a multilingual-capable voice from ElevenLabs library
ELEVENLABS_VOICE_ID=
VOICE_WEBHOOK_SECRET=aiui-voice-2026
```

**Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add ELEVENLABS_MODEL_ID and ELEVENLABS_VOICE_ID to .env.example"
```

---

### Task 3: Update ElevenLabs agent dashboard (manual)

This task is a manual checklist — no code changes.

**Step 1: Open ElevenLabs agent dashboard**

Go to https://elevenlabs.io/app/conversational-ai and select the agent matching your `ELEVENLABS_AGENT_ID`.

**Step 2: Update the voice**

In the agent settings, select a multilingual voice. Choose one that:
- Supports the `eleven_multilingual_v2` model
- Has good quality across languages you care about (Tagalog, Dutch, English, etc.)
- Maintains consistent voice identity

**Step 3: Update the system prompt**

Add this to the beginning or end of the existing system prompt:

```
Language instructions: Always respond in the same language the user is speaking. If the user switches languages mid-conversation, follow them and respond in the new language. Do not default to English unless the user speaks English.
```

**Step 4: Update first message (optional)**

If the current first message is English-only, consider making it bilingual or keeping it English (the bot will auto-switch once the user speaks).

**Step 5: Save and test**

Save the agent config on the dashboard.

---

### Task 4: Deploy to Hetzner

**Step 1: Update server .env**

SSH into the server and update `/root/proxy-server/.env`:

```bash
ssh root@46.224.193.25
```

Add/update these lines:
```bash
ELEVENLABS_MODEL_ID=eleven_multilingual_v2
ELEVENLABS_VOICE_ID=<voice ID selected in Task 3>
```

**Step 2: Copy updated config.py to server**

```bash
scp webhook-handler/config.py root@46.224.193.25:/root/proxy-server/webhook-handler/config.py
```

**Step 3: Rebuild and restart webhook-handler**

On the server:
```bash
cd /root/proxy-server
docker compose -f docker-compose.unified.yml up -d --build webhook-handler
```

**Step 4: Verify the container is running**

```bash
docker compose -f docker-compose.unified.yml logs --tail=20 webhook-handler
```

Expected: Bot logs showing "Conversational voice bot ready" with no errors.

---

### Task 5: Test multilingual voice bot

**Step 1: Join a Discord voice channel**

Join any voice channel in the Discord server. The bot should auto-join.

**Step 2: Test English**

Speak in English. Verify the bot:
- Transcribes correctly (check text channel)
- Responds in English
- Voice sounds natural

**Step 3: Test Tagalog**

Switch to Tagalog. Verify the bot:
- Transcribes Tagalog correctly
- Responds in Tagalog
- Voice identity stays consistent

**Step 4: Test language switching**

Speak English, then switch to another language mid-conversation. Verify the bot follows the language switch.

**Step 5: Test a third language (e.g., Dutch or Spanish)**

Speak in a third language. Verify recognition and response quality.

---
