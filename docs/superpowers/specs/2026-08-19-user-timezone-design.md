# Per-user timezone, autodetected, so the assistant knows the local time

Date: 2026-08-19
Status: approved, ready to implement

## Problem

Ask any model on the platform "what time is it?" or "schedule this for tomorrow
morning" and it has nothing to work from. It does not know the date, the time,
or the user's zone. Every model on the platform has this gap, because nothing
injects a clock.

Nothing in the repo reads or stores a timezone today (`grep` for
`timezone|ZoneInfo|pytz` outside `apps/` returns nothing).

## Can it be autodetected

Yes. The browser knows the zone exactly:

```js
Intl.DateTimeFormat().resolvedOptions().timeZone   // "Asia/Manila"
```

That is an IANA zone name, which is the right thing to store: it survives
daylight saving changes, unlike a raw UTC offset.

`mcp-servers/gdrive/integrations-ui.js` is already injected into every Open WebUI
page and already resolves the signed-in user's email, so it is the natural place
to detect and report the zone. No new page, no user action.

Both containers already have working IANA tzdata, verified:

```
docker exec open-webui python -c "from zoneinfo import ZoneInfo; ..."  -> OK
docker exec tasks      python -c "from zoneinfo import ZoneInfo; ..."  -> OK
```

## Design

### 1. Store it

Migration `038_user_prefs.sql`:

```sql
CREATE TABLE IF NOT EXISTS tasks.user_prefs (
    email       TEXT PRIMARY KEY,
    timezone    TEXT,                       -- IANA name, e.g. "Asia/Manila"
    tz_source   TEXT NOT NULL DEFAULT 'auto',  -- 'auto' | 'manual'
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`tz_source` exists so a value the user sets by hand is not stomped the next time
they open the app from a laptop in another zone. Autodetect writes only when the
stored source is `auto`.

A general `user_prefs` table rather than `user_timezone`, because the next
per-user preference should not need another migration.

### 2. Detect it

In `integrations-ui.js`, on load, once per day per user (localStorage guard so
this is not a request on every page view):

```js
var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
// POST {timezone: tz} to tasks, keyed by the resolved email
```

Fails silently. A missing timezone must never break the page.

### 3. Serve it

`GET /prefs/timezone` on the tasks service, using the existing `current_user`
dependency, returning:

```json
{"timezone": "Asia/Manila", "source": "auto"}
```

`POST /prefs/timezone` accepts `{"timezone": "...", "manual": false}`, validates
the name against `zoneinfo.available_timezones()` (rejecting anything else, so
the value reaching the DB is always a real zone), and upserts.

Unknown user, or never detected: fall back to `AIUI_DEFAULT_TZ` (default `UTC`).
The injected line always names the zone, so a fallback is visible rather than
silently wrong.

### 4. Inject it

A new global Open WebUI inlet filter, `user_local_time`, modelled on the
existing `knowledge_graph_memory` filter. One system message per turn:

```
The user's current local date and time is Wednesday, 19 August 2026,
5:01 PM (Asia/Manila). Use this whenever the conversation involves dates,
times, scheduling or "today"/"tomorrow".
```

**Why a separate filter rather than folding this into the knowledge graph one.**
The knowledge graph filter returns early in two cases: when the message is
shorter than 3 characters, and when the graph context comes back empty. Both are
correct for memory and wrong for a clock. A user with an empty graph asking "hi,
what time is it" would get nothing. The clock has to be unconditional, so it
gets its own filter.

**Latency.** The filter caches the user's zone in process for 30 minutes and
computes the timestamp locally with `zoneinfo`, so the timestamp is exact on
every turn while the lookup costs roughly two requests per user per hour. Fails
open: any error leaves the chat untouched, same contract as the memory filter.

### 5. Reach

This covers every model in chat, including the Auto routers and Fusion, because
it is a global inlet filter. It does not cover the Discord, Telegram, Slack,
Mattermost or Terminal channels, which do not pass through Open WebUI. Those
users still get their zone detected, because pairing a channel requires opening
the web app at least once. Injecting the clock into the gateway path is a
follow-on, not part of this spec.

## Follow-on, deliberately not built here

Cron schedules are currently interpreted in server time. With `user_prefs` in
place, "every weekday at 9am" can mean 9am where the user is. That is a
behaviour change to existing live schedules, so it needs its own decision and
its own migration of the rows already in `tasks.schedules`.

## Testing

- IANA validation rejects `Not/AZone` and accepts `Asia/Manila`
- autodetect does not overwrite a row whose `tz_source` is `manual`
- autodetect does overwrite a row whose `tz_source` is `auto`
- the injected line renders the correct local time for a known zone and instant
- unknown user falls back to `AIUI_DEFAULT_TZ` and the line still names the zone
- the filter injects on a 2-character message (the case the memory filter skips)
- the filter leaves the body untouched when the lookup raises
