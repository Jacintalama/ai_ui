# Deploy: bring your own bot

Branch `feat/multi-platform-gateway`, 30 commits, `5cb54922d..9811f4e14`.
Spec: `docs/superpowers/specs/2026-08-12-bring-your-own-bot-design.md`
Plan: `docs/superpowers/plans/2026-08-12-bring-your-own-bot.md`

All code and tests are done. This is the only remaining step. It needs a real
bot from BotFather, which is why it was left for a person.

## Read this first: two traps

**1. The repo's compose file is NOT the server's.**
`docker-compose.unified.yml` in this repo contains no `TELEGRAM_BOT_TOKEN` and
no `GATEWAY_TELEGRAM_BOT`, yet `@aiuiteam_bot` works in production. So the
server's copy has values the repo's does not. This deploy has to edit compose,
and pushing the repo's version over the server's would unset the shared bot's
token and take `@aiuiteam_bot` down.

Diff before you overwrite anything, per the hash-sweep rule in CLAUDE.md.

**2. `.deploy-state` is stale.**
It reads `{"sha":"5db322fcd...","deployed_at":"2026-05-18"}`, and that commit is
not in this repo's history at all (`git cat-file -t 5db322fcd` fails). The
orchestrator diffs against that SHA to decide what to rsync, so its
changed-files logic will not do what you expect. Check the server's copy before
relying on it.

## Step 1: the environment variable

The tasks service now needs `GATEWAY_PUBLIC_URL` to build the webhook URL it
registers with Telegram. Without it `_public_url()` returns `""`, the URL
becomes the relative string `/webhook/telegram/<key>`, Telegram rejects it, and
every save lands `enabled=false` with an error. The feature would be dead on
arrival.

It is not in the server `.env` either, and CLAUDE.md forbids touching `.env`.
So give it a default rather than assuming the variable exists:

```yaml
      - GATEWAY_PUBLIC_URL=${GATEWAY_PUBLIC_URL:-https://ai-ui.coolestdomain.win}
```

Add that to the **tasks** service environment block. `AIUI_FERNET_KEY` is
already there; confirm rather than assume.

Do this by editing the server's copy in place, or by diffing first and merging.
Do not scp the repo's compose over it.

## Step 2: deploy tasks

```bash
ORCH_HOST=46.224.193.25 ./scripts/deploy_orchestrator.sh
```

The orchestrator needs `rsync`, absent from Git Bash on Windows. Fallback is one
`scp` per changed file, rebuild `tasks`, then update `.deploy-state` by hand as
JSON (`{"sha": ..., "deployed_at": ..., "deployed_by": ...}`); writing a bare
SHA breaks the next deploy.

Files changed under `mcp-servers/tasks/`:
`main.py`, `models.py`, `routes_gateway.py`, `gateway_bots.py`,
`telegram_api.py`, `migrations/036_gateway_bots.sql`,
`static/gateway-link.html`, plus the new test files.

## Step 3: deploy webhook-handler by hand

The orchestrator does not watch it. One `scp` per file, never `scp -r`, which
silently skips files.

```bash
scp webhook-handler/main.py root@46.224.193.25:/root/proxy-server/webhook-handler/main.py
scp webhook-handler/clients/tasks.py root@46.224.193.25:/root/proxy-server/webhook-handler/clients/tasks.py
ssh root@46.224.193.25 "cd /root/proxy-server && sed -i 's/\r$//' webhook-handler/main.py webhook-handler/clients/tasks.py && docker compose -f docker-compose.unified.yml up -d --build webhook-handler"
```

The `sed` matters: this repo checks out CRLF on Windows, and a stray `\r` turns
a compose value into `true\r`, which reads as false.

If `scp` drops the connection on a larger file, gzip over ssh works:
`gzip -c file | ssh root@HOST "gunzip > /path/file"`.

## Step 4: confirm it came up

```bash
curl -fsS https://ai-ui.coolestdomain.win/tasks/healthz
ssh root@46.224.193.25 "cd /root/proxy-server && docker compose -f docker-compose.unified.yml ps webhook-handler"
```

Then the container test tier, which cannot run locally because there is no
Postgres:

```bash
ssh root@46.224.193.25 "docker exec tasks sh -lc 'cd /app && python -m pytest tests/test_gateway_bot_routes_db.py -q'"
```

14 tests, including the two that prove a stranger sees `bot: null` on every row
of the Channels page.

## Step 5: prove the shared bot still works

Before touching anything new. Message `@aiuiteam_bot` and get a reply, and check
the Discord bot still answers in its channel. Those are live features and this
work was built to leave them alone.

## Step 6: the real walkthrough

A unit test cannot prove this wiring; only a real bot can.

1. Create a throwaway bot in BotFather, copy the token.
2. Open Channels, expand Telegram, paste the token, Save & Enable. The card must
   come back naming your bot.
3. Press Test. It should say the bot is alive and to send your code.
4. Message the bot on Telegram, send the pairing code from the page, then ask it
   something. It must answer.
5. Press Test again. It should now send you a real message.
6. **Turn the bot off, then message it. It must stay silent.** This is the step
   that proves the cache TTL works; a stale cache would keep answering.
7. Turn it back on, confirm it answers, then Remove bot.

## Step 7: the one thing to grep for

Immediately after the first real save:

```bash
ssh root@46.224.193.25 "docker logs tasks --since 5m | grep -c 'api.telegram.org/bot'"
```

Expected: `0`.

If it is not zero, a bot token is in the container log and therefore in Loki.
Rotate that BotFather token immediately and purge the series. This was a real
bug found in the final review (httpx logs the full request URL at INFO, and
Telegram puts the token in the URL) and fixed in `9673e0d92`, but it is worth
confirming on the live box rather than trusting the fix.

## What ships dormant

The table starts empty, so nothing changes until someone saves a bot.
`/webhook/telegram` keeps serving `@aiuiteam_bot` on the env-var path. The
migration is `CREATE TABLE IF NOT EXISTS` on a new table. No Discord or Slack
file is in the diff.

The one new surface is `POST /webhook/telegram/{bot_key}`, publicly reachable
once webhook-handler restarts. With an empty table every request costs one
internal call and one indexed SELECT before returning 404.

## Known gaps, deliberately not built

- Test is not rate limited, though the spec's security section promises it.
  `GatewayRedeemBudget` is the pattern to copy.
- `token_hint` is computed on save but never rendered, so the card does not show
  which token is stored.
- Replacing a token does not clear the old bot's webhook, so it POSTs to a
  404ing key until cleared in BotFather.
- Editing a bot requires re-pasting the token, and there is no Cancel.
- Outbound-initiated messages preferring a user's own bot. Nothing sends an
  unsolicited Telegram message today, so there is no code path to change yet.
