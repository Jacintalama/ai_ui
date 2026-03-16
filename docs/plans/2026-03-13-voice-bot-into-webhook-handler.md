# Voice Bot Into Webhook-Handler — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Merge the voice-bridge Discord bot into the webhook-handler process to eliminate a separate container and save ~150MB RAM.

**Architecture:** The Discord voice bot runs as a background asyncio task inside webhook-handler's FastAPI lifespan. It calls the voice webhook endpoint internally via localhost. No separate container needed.

**Tech Stack:** discord.py[voice], PyNaCl, ffmpeg, FastAPI lifespan background tasks

---

### Task 1: Add dependencies and ffmpeg to webhook-handler

**Files:**
- Modify: `webhook-handler/requirements.txt`
- Modify: `webhook-handler/Dockerfile`

**Step 1:** Add `discord.py[voice]>=2.3.0` to requirements.txt

**Step 2:** Add ffmpeg to Dockerfile: `apt-get install -y ffmpeg`

---

### Task 2: Create voice_bot.py in webhook-handler

**Files:**
- Create: `webhook-handler/voice_bot.py`

Move the VoiceBot class from voice-bridge/main.py into webhook-handler/voice_bot.py. Key changes:
- Remove container-specific env var loading (will receive config from main.py)
- Change webhook URL to `http://localhost:8086` (same process)
- Add `start_voice_bot(token, api_key, ...)` async function that main.py calls
- Update API key to new one

---

### Task 3: Start voice bot in webhook-handler lifespan

**Files:**
- Modify: `webhook-handler/main.py`

In the `lifespan()` function, after all existing init, if `DISCORD_BOT_TOKEN` and `ELEVENLABS_API_KEY` are set, start the voice bot as a background asyncio task.

---

### Task 4: Update docker-compose and env vars

**Files:**
- Modify: `docker-compose.unified.yml`
- Modify: server `.env`

Remove voice-bridge service from docker-compose. Add ELEVENLABS env vars to webhook-handler service. Update API key on server.

---

### Task 5: Deploy and verify

Deploy updated webhook-handler to server, rebuild, verify both `/aiui` slash commands and `!voice` text commands work. Remove voice-bridge directory from server.
