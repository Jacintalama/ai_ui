# Connecting Buzz to IO

**For whoever builds the Buzz side.** The IO side is already built and
deployed. Buzz needs one outbound call, described below. Nothing else.

When it works, a Buzz user talks to IO in Buzz and IO answers with that
user's own memory, tools and models. Their IO account, not a shared one.

## What Buzz has to do

Send every message meant for IO to:

```
POST https://ai-ui.coolestdomain.win/webhook/gateway/buzz
Content-Type: application/json
X-Buzz-Signature: sha256=<hex>
```

Body:

```json
{
  "user_id": "the Buzz user's stable id",
  "user_name": "Ralph Benitez",
  "text": "what's on today",
  "conversation_id": "the thread or room id"
}
```

Show the `reply` from the response back to the user:

```json
{ "reply": "You have three things today..." }
```

That is the whole integration. Request and response, no callback, no polling,
no websocket to hold open.

### The fields

| Field | Required | Notes |
|---|---|---|
| `user_id` | yes | Must be **stable for that person forever**. It is what IO pairs to an account. If it changes, that user silently becomes a stranger and has to pair again. Max 128 chars. |
| `text` | yes | What the person typed. Trimmed to 8000 chars. |
| `user_name` | no | Display name, used so a person can see whose account is linked. |
| `conversation_id` | no | The thread. One IO chat is kept per value. Omit it and IO keeps one conversation per user, which is usually what you want for a direct message. |

## Signing

`X-Buzz-Signature` is `sha256=` followed by the lowercase hex HMAC-SHA256 of
the **exact request body bytes**, keyed with the shared secret.

```python
import hashlib, hmac
sig = "sha256=" + hmac.new(SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
```

```javascript
const sig = "sha256=" + crypto.createHmac("sha256", SECRET)
                              .update(rawBody).digest("hex");
```

Sign the bytes you actually send, not a re-serialised object. Two JSON
encoders disagree about spacing and key order, and IO verifies against the raw
bytes it received, so re-encoding produces a signature that will not match.

The secret is shared out of band. Never put it in client code: anything
holding it can speak as any Buzz user.

## Responses

| Status | Meaning | What to do |
|---|---|---|
| `200` | Handled. Body has `reply`. | Show `reply` to the user. |
| `400` | `user_id` or `text` missing, empty, or not a string. Or the body was not JSON. | Fix the payload. Retrying unchanged will not help. |
| `401` | Signature missing or wrong. | Fix the signing. This is the one to check first if nothing works. |
| `429` | That user is sending faster than IO can answer, 20 a minute. | Back off. The limit is per `user_id`, so other users are unaffected. |
| `503` | Buzz is not switched on for this IO server. | Ask IO to set it up. |

## Pairing, and why the first reply looks odd

IO does not know who a Buzz `user_id` belongs to until the person says so.

1. A Buzz user messages IO for the first time.
2. IO replies with a short pairing code instead of an answer.
3. They open IO's **Channels** page while signed in, and paste the code.
4. Every later message is answered as that account.

Nothing special is required from Buzz for this. The code arrives as an
ordinary `reply` and the user does the rest.

**Do not build a way for one user to enter another's code.** A code links
whichever IO account asked for it, and it hands the holder that account's
memory, email assistant and files.

## Switching it on

Two things, both on the IO server:

- `BUZZ_WEBHOOK_SECRET` on **webhook-handler**, the shared secret. Until it
  exists the endpoint returns 503 and accepts nothing.
- `BUZZ_ENABLED=1` on **both webhook-handler and tasks**.

Both services read that flag deliberately. webhook-handler serves the
endpoint; tasks renders the Channels row. Setting it on only one is exactly
how the Terminal channel once ended up live while the page called it switched
off.

## Checking it end to end

```bash
SECRET='the shared secret'
BODY='{"user_id":"test-user-1","user_name":"Test","text":"hello"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')

curl -sS https://ai-ui.coolestdomain.win/webhook/gateway/buzz \
  -H "Content-Type: application/json" \
  -H "X-Buzz-Signature: sha256=$SIG" \
  -d "$BODY"
```

First run returns a pairing code. Paste it into IO's Channels page, then run
it again and you get a real answer.

## What is deliberately not here

- **No push from IO.** IO only ever answers a message. Nothing arrives in Buzz
  unprompted, so Buzz needs no inbound endpoint at all.
- **No per-user bot tokens.** Telegram lets a user bring their own bot; Buzz
  users share this one integration, which is why the Channels row never offers
  to take a token.
- **No attachments or voice.** Text only for now. Telegram carries voice memos
  through the same pipeline, so adding them later is work on this side, not a
  change to the contract above.
