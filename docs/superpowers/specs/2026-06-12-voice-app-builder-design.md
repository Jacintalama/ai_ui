# Voice App Builder + TTS Cutout Fix — Design

**Date:** 2026-06-12
**Status:** Approved (design approved in session; spec available for review)
**Owner:** webhook-handler (voice layer) + ElevenLabs agent config

## Problem

1. **Feature:** The Discord voice assistant (General voice channel, ElevenLabs
   Conversational AI agent "AIUI Voice Assistant") cannot build websites. The
   user wants: after the intro, saying "create me a website" leads the agent to
   ask **"start from a template, or a blank project?"**, then ask relevant
   follow-up questions, then start an App Builder build — fully by voice.
2. **Bug:** The agent's voice sometimes cuts out mid-message and never finishes
   the sentence ("the ai voice on discord is cut and it wont continue speak").

## Root causes (bug)

Both found by inspection of `webhook-handler/voice_bot.py`; no live sessions in
retained logs to corroborate (container rebuilt 2026-06-11 ~15:14, no voice
sessions since), so fixes ship with instrumentation that makes any recurrence
visible.

1. **Output queue overflow, silent drop.** `AudioOutputSource._queue` has
   `maxsize=200` frames = 4.0 s of audio. ElevenLabs streams TTS faster than
   realtime while Discord drains at exactly realtime (50 fps), so any reply
   longer than ~6 s overflows the queue and `feed()` silently drops the tail
   (`except queue.Full: pass`). Symptom: speech stops mid-sentence, session
   continues normally.
2. **Watchdog kills sessions mid-speech.** `_watchdog_should_reconnect` fires
   when no **user** transcript arrived for 25 s while a human is in the
   channel. It ignores whether the agent is currently speaking. Any agent
   answer (or answer + user thinking pause) extending past 25 s gets the
   session torn down and reconnected mid-sentence; the new session re-greets
   and conversation context is lost. ("..." turn-timeout transcripts are
   filtered and do not reset the clock, making this easier to hit.)

## Decisions (user-approved)

- Voice builds are owned by the user's **linked email**, supplied via a new
  `VOICE_USER_EMAIL` env var (one line appended to the server `.env`; nothing
  else in that file is touched). Fallback when unset: voice builds respond
  with the not-linked message.
- Template picking by voice: agent asks **"what kind of site?"** and suggests
  the **2–3 closest** templates by name; never reads all ~29 aloud.
- The agent reads back a one-line summary and **confirms before building**.

## Design

### A. Voice cutout fix — `voice_bot.py`

1. `AudioOutputSource._queue` maxsize 200 → **4500** frames (90 s; ≈17 MB
   worst-case transient, acceptable on the 3.8 GB box). On `queue.Full`:
   increment a `_dropped` counter and log a WARNING (rate-limited: every 50th
   drop), instead of dropping silently.
2. `_dropped` is exposed in `_pipeline_stats()` → appears in the `stats5s` log
   line and `!voice diag`.
3. `_watchdog_should_reconnect` returns False while agent audio is queued or
   playing (`_audio_output._has_content or not _audio_output._queue.empty()`).
4. The activity clock (`_last_user_transcript_time`, renamed
   `_last_activity_time`) also resets when playback drains
   (`_on_playback_drained`), so the 25 s deafness countdown starts **after**
   the agent finishes speaking, not after the user's last words.
5. Remove dead `_wait_and_unmute` (no callers since the queue-state mute gate
   landed). Keep the "User interrupted agent" log to correlate any future
   cutout reports with ElevenLabs-initiated interruptions.

### B. Voice App Builder flow

**Conversation logic lives in the ElevenLabs agent prompt** (approach A:
agent-driven dialog + thin tools; a server-side wizard state machine was
rejected as YAGNI, and routing via the generic `ask` tool targets OpenWebUI
chat, not the App Builder).

Prompt addition (full prompt becomes config-as-code, see D):

- When the user wants to create a website/app: ask "template or blank?".
- Template path: ask what kind of site, call `list_templates`, suggest the 2–3
  closest matches by label, let the user pick by voice.
- Collect a short description (name, purpose, style) in 1–2 questions.
- Read back a one-line summary, get a yes, then call `start_build` with
  `template_key` (omitted for blank) and `description`.
- After starting: say it takes a few minutes, the preview link will be posted
  in the text channel, and the user can ask "is my build done?" anytime.
- Keep spoken replies short (also reduces audio buffering).

**Three new webhook tools** (POST `https://ai-ui.coolestdomain.win/webhook/voice/<name>`,
existing `X-Voice-Secret` auth, created via the ElevenLabs tools API):

| Tool | Maps to | Notes |
|---|---|---|
| `list_templates` | `aiuibuilder templates` (existing handler) | Full catalog in `full_result`; the LLM picks suggestions. |
| `start_build` | `aiuibuilder build [template] <description>` (existing handler) | Body: `template_key` (optional), `description` (required). The voice layer composes the `aiuibuilder` arguments string. |
| `build_status` | voice-layer handler (new) | Speaks "still building / ready at URL / failed / no build yet". Optional `task_id` in body; defaults to the **last voice-started build**. |

**Voice layer changes** (`main.py` + `handlers/commands.py`):

1. `config.py`: new setting `voice_user_email: str = ""` (env
   `VOICE_USER_EMAIL`).
2. `_resolve_email_for_ctx`: `ctx.platform == "voice"` → return
   `settings.voice_user_email or None` (None → existing not-linked reply).
3. `/webhook/voice/{command}` special-cases three commands before the generic
   router passthrough (all other commands unchanged):
   - `list_templates` → ctx(subcommand=`aiuibuilder`, arguments=`templates`)
     through the router; the LLM reads `full_result` for matching.
   - `start_build` → reads explicit body fields `template_key` (optional) and
     `description` (required), then calls a new public router method
     `run_voice_build(ctx, template_key, description) -> dict | None`
     (mirrors `run_panel_build`): resolves email, validates the key against
     the catalog (unknown key → spoken error naming `list_templates`, no
     silent blank build), starts the build via the shared `_start_build`, and
     returns `{"slug", "task_id"}` on success. `_start_build` is changed to
     return the tasks-service result dict (currently returns None; all
     existing callers ignore the return — non-breaking).
   - `build_status` → new router method `run_voice_build_status(ctx, email,
     task_id)`: calls `TasksClient.get_build_status`, responds with a spoken
     state (building / ready at URL / needs input / failed). `main.py` decides
     the `task_id`: explicit body field if given, else the remembered last
     voice build. Survives voice-session reconnects (state lives in the web
     process, not the conversation).
4. **Last-voice-build memory:** module-level in `main.py` (single voice user
   by design): `{"task_id", "slug", "email"}`, set from `run_voice_build`'s
   return value when a voice `start_build` succeeds.
5. **Build-ready notification:** the voice ctx gets a real `notify_channel`
   closure that POSTs to the Discord channel REST API (same pattern as the
   Grafana alert forwarder in `main.py`): target = the voice bot's current
   session text channel when available (new module helper in `voice_bot.py`
   exposing the active bot's `_text_channel` id), else
   `settings.discord_alert_channel_id`. `_watch_build` then posts the preview
   link exactly like Discord text builds.
6. Spoken responses: reuse `VoiceResponseCollector.spoken_summary`.

### C. Identity

`VOICE_USER_EMAIL=<linked email>` appended to the server `.env` (value read
from the server's existing `DISCORD_USER_EMAIL_MAP`, not pasted into chat).
Compose already passes the env through to the container (verify; add to
`docker-compose.unified.yml` environment list if it uses an explicit list).

### D. Agent config as code — `webhook-handler/scripts/setup_voice_agent.py`

Idempotent script, run on the server (`python3 scripts/setup_voice_agent.py`
with env from `/root/proxy-server/.env`):

1. Reads `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `VOICE_WEBHOOK_SECRET`
   from env. Never prints secrets.
2. GET `/v1/convai/tools` — match the 3 tools by name; create missing / PATCH
   existing (URL, schema, secret header).
3. PATCH `/v1/convai/agents/{id}` — sets the **full prompt** (current live
   prompt captured into the script + new App Builder section) and
   `tool_ids` = existing 11 ∪ the 3 new ids. Everything else (voice, turn
   config, first message) untouched.
4. `--dry-run` prints the plan (tool names + prompt diff summary) without
   writing.

The 11 existing tools remain standalone ElevenLabs tools and are not modified.

## Error handling

- Tasks service down / build start fails → spoken: "The builder isn't
  reachable right now, try again in a minute." (existing
  `_format_build_error` text via spoken_summary).
- `VOICE_USER_EMAIL` unset → existing not-linked message, spoken.
- `build_status` with no remembered build → "I haven't started any build this
  session."
- Watcher posts failures to the text channel exactly as text builds do
  (`needs_input` / `failed` / still-building timeout).
- Webhook always returns 200 with a spoken summary — ElevenLabs treats non-200
  as tool failure and the agent apologizes generically; we prefer specific
  spoken errors.

## Testing

TDD; new tests in `webhook-handler/tests/`:

- `test_voice_bot_recovery.py` (extend): watchdog idle while agent audio
  queued/playing; activity clock reset on drain.
- `test_voice_bot_audio.py` (new): no drops up to N≫200 frames; `_dropped`
  increments + WARNING when truly full; `dropped` in `_pipeline_stats`.
- `test_voice_app_builder.py` (new): voice email resolution (set/unset);
  `run_voice_build` → TasksClient called with template_key/description,
  unknown key → spoken error, returns slug/task_id, ack mentions minutes +
  text channel; `run_voice_build_status` spoken states
  (building/ready/needs_input/failed); voice webhook wiring: last-build
  memory set, `build_status` with no memory → "no build yet"; notify closure
  posts to session text channel, falls back to alert channel.
- `test_setup_voice_agent_script.py` (new): tool payload building, tool
  matching/idempotency, prompt contains the App Builder flow section, secret
  header set from env (pure functions; HTTP mocked).
- Full webhook-handler suite stays green.

## Rollout

1. Commit; push to fork/main (incl. the two already-deployed voice-fix
   commits ff884a055/b666d0bbf per repo hygiene).
2. Deploy webhook-handler manually (one `scp` per changed file — never
   `scp -r` — then `docker compose -f docker-compose.unified.yml up -d --build
   webhook-handler`).
3. Append `VOICE_USER_EMAIL=<linked email>` to server `.env` (single appended
   line; approved).
4. Run `setup_voice_agent.py` on the server; verify with a GET that the agent
   has 14 tools + new prompt.
5. Smoke: `/webhook/voice/list_templates` + `/webhook/voice/build_status` with
   the secret (from server env, not chat) return spoken summaries; container
   `Up (healthy)`.
6. Live verification with the user in General voice: greeting → "create me a
   website" → template/blank question → template suggestions → confirm →
   build starts → preview link lands in text channel → "is my build done?"
   answered; long agent replies play to completion (watch `stats5s` for
   `dropped=+0`, no DAVE reconnect mid-speech).

## Out of scope (YAGNI)

- Proactive voice announcement when the build finishes (agent speaks only in
  reply; the text channel link + `build_status` polling cover it).
- Multi-user voice identity (single `VOICE_USER_EMAIL`).
- Enhance/publish/delete by voice (text/panel flows already cover these;
  can be added later as tools if wanted).
- Slack voice. Cron/schedule changes. n8n changes.
