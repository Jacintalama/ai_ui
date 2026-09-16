# The two Open WebUI pipe files match production, and agents take turns stays off

Date: 2026-09-16
Status: accepted

## What was wrong

`open-webui-functions/auto_router_pipe.py` and `io_gateway_pipe.py` are not
deployed like the rest of the platform. Open WebUI keeps a pipe's source in
`public.function.content` in the database, and that row is what runs. The files
in this repository are the copies someone installs from.

On 2026-09-04 the "agents take turns" feature shipped and was rolled back the
same night by updating both database rows. Open WebUI renders `message.output`,
not `message.content`, so the page never split a reply into separate messages,
and the marker the pipe appended sat visible in saved chats.

The repo copies were never reverted with the rows. For twelve days the files
here carried code production did not run, on `main` as well as on the branch,
so installing either file from git would have switched the broken feature back
on with nothing to warn the person doing it.

## What changed

Both files now match their live rows: no `first_only` request flag, and no
marker appended to a reply. The live content was checked for credentials before
it was committed.

The tests that pinned the old behaviour were **inverted, not deleted**. They now
assert the pipe does not send `first_only` and appends no marker. Deleting them
would have left nothing to catch the next re-import, which is how the drift
survived in the first place.

## The half that was never rolled back

The rollback changed the two pipe rows. It did not change the page:
`mcp-servers/gdrive/integrations-ui.js` still contains the whole turn taking
flow, including `aiuiParseTurns`, which reads a marker out of stored message
content and then fetches the remaining agents one at a time. That code is
dormant only because nothing produces a marker any more.

So the pipes keep one line of the withdrawn feature on purpose: they **strip**
marker shaped text from a reply on the way out, and append none. Its comment in
the page file says "the pipes already strip marker shaped text out of an
agent's own words", and that sentence has to stay true.

Without it the only way a marker could appear is from a model: an agent writes
the shape by accident, or someone asks it to. The page would then act on text a
model wrote, and run turns for agents nobody asked for. Stripping at the point
where a reply enters a stored chat costs one regular expression.

If turn taking is ever revived, the pipe change is the small part. Making Open
WebUI's renderer split messages is the part that has to be solved first.

## What is deliberately still here

The service side is untouched: `/agents/chat` still accepts `first_only`, still
returns a `queue` and a `marker`, and its tests still pass. Nothing sends the
flag, so it is unreachable. It was reviewed and works, and the half that failed
was the page, so it stays.

## How to check this is still true

```bash
ssh root@46.224.193.25 "docker exec postgres psql -U openwebui -d openwebui \
  -Atc \"select content from function where id='auto_router'\"" | tr -d '\r' | md5sum
tr -d '\r' < open-webui-functions/auto_router_pipe.py | md5sum
```

The two hashes must match, and the same for `id='io'` against
`io_gateway_pipe.py`. A pipe row reloads with no restart, so a change made in
the Open WebUI admin screen reaches production without ever touching git. Run
this after any pipe work.

## Related

- The rollback itself, 2026-09-04.
- `CLAUDE.md`, "The prompt is not a guarantee": the same shape of defect, where
  something believed to be deployed was not.
