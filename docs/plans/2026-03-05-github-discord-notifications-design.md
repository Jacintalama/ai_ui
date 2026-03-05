# GitHub → Discord Notifications — Design

**Date:** 2026-03-05
**Status:** Approved
**Origin:** Lukas standup (2026-03-05) — "Does the PR trigger the Discord notification with the webhook?"

---

## Summary

Add Discord notifications for GitHub PR and push events. When someone opens/merges a PR or pushes code, a formatted message appears in the Discord #general channel.

## Events

| Event | Trigger | Discord Message |
|-------|---------|----------------|
| PR opened | `pull_request` action=`opened` | 🔀 **New PR #N**: "title" by @author → `base` |
| PR merged | `pull_request` action=`closed` + merged | ✅ **PR #N merged**: "title" by @author |
| PR closed | `pull_request` action=`closed` + !merged | ❌ **PR #N closed**: "title" |
| Push | `push` | 📦 **Push to `branch`**: N commits by @author — latest: "message" |

## Architecture

```
GitHub webhook → Caddy → API Gateway → webhook-handler /webhook/github
                                              ↓
                                    GitHubWebhookHandler.handle_event()
                                              ↓
                                    (existing AI analysis logic unchanged)
                                              ↓
                                    NEW: _notify_discord()
                                              ↓
                                    POST discord.com/api/v10/channels/{id}/messages
```

## Implementation

- Add `_notify_discord(message)` method to `GitHubWebhookHandler` in `webhook-handler/handlers/github.py`
- Call from `handle_push()`, `handle_pull_request()` (opened, merged, closed)
- Uses existing `settings.discord_bot_token` and `settings.discord_alert_channel_id`
- Silent skip if token or channel not configured
- Messages truncated to 2000 chars (Discord limit)
- No new files, no new endpoints, no n8n dependency

## Out of Scope

- Issue notifications (not requested)
- Comment notifications (too noisy)
- n8n workflow integration (n8n API key is broken, Ralph handling)
