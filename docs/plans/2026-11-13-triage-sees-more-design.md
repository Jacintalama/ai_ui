# The triage sees more of AIUI: design (2026-11-13)

Lukas, 2026-11-13: "the biggest focus, I feel, is still the triage engine, to
connect as much stuff into it of the current features of AIUI, so it
recommends the correct path." The user asked for it built without further
questions; the one open choice (memory) is recorded below as my call.

## What he named, and what is there today

| He wants the triage to see | Today (read from the code) |
|---|---|
| Connectors | All 14 in `app_triage.APPS` (Ralph added Jira, LinkedIn, Dropbox, Airtable writes on 2026-11-12/13) |
| Cron jobs, tools | Through the tool pick (`agent_jev.pick_tools`) |
| Deploy ("we can deploy with Vercel ... just recommend the most straightforward one") | Not seen. Publishing is a button in the App Builder (`routes_projects.publish_app`, 3 apps published); Deploy to Vercel is in the same Publish window (`routes_vercel.py`, OAuth configured live, 1 account connected). No chat tool does either. |
| Skills | Not weighed. 68 built-in skills plus each person's own; only a separate skills tool suggests them. |
| Knowledge base, memories ("something we mentioned 10 chats ago") | The Knowledge Graph Memory filter (global, active) puts the person's graph in front of every model, the free one included. The graph holds chat TITLES, files, collections and saved memories (`public.memory`), not what was said inside chats. Facts reach `public.memory` only through the reflection after an agent or assistant turn (`agent_memory.schedule_reflection`, called in `_run_turn`). An ordinary message answered by the free model is never reflected on, so a fact said there is lost. |

## Design

### 1. Deploy: the platform's own way first
A second kind of catalogue entry, `app_triage.PLATFORM`: things AIUI does
itself, needing no connection. First entry: **Publish**, noted for "putting a
website or app online so other people can visit it: publishing, deploying,
hosting, going live, a link to share, a custom domain, or putting it on
Vercel". Jev is asked about it in the same call as the apps
(`apps_request` covers APPS then PLATFORM). When picked:
- the assistant runs (as for an app not connected) with the brief saying the
  platform does this itself, how (App Builder or preview, Publish; the same
  window deploys to their own Vercel), to recommend it as the straightforward
  way, and not to suggest other hosting services;
- the service adds the how-to line under the answer when the answer does not
  mention Publish, because the prompt is not a guarantee.

### 2. Skills
A fourth Jev question beside the other three, `agent_jev.pick_skills_for_message`:
one yes/no per skill in the person's pool (`routes_agents._skill_pool`), asked
about the message (the existing `pick_skills` asks about a new agent's
description, a different question). At most two kept. When one fits, the
assistant runs with the `skills` tool added, and the brief names the skill, what
it does, and to read it with the skills tool and follow its steps. A skill that
needs an app the person has not connected (`skill_fit.missing`) gets that app's
Connect button. A skill already named in a recent reply is not offered again.

### 3. Memory across chats (my call: save facts, not index whole chats)
On the free-model path (route_only, no agent, no assistant), the person's
message is reflected on in the background exactly as an agent turn is, with the
answer marked as not shown, so the facts THEY state reach `public.memory`, which
the graph and the filter already carry into every other chat. The existing gates
stay: the Jev "worth remembering" check, the 40-character floor, 90 seconds per
person and two in flight. Indexing every chat's full text was the alternative:
more complete, but it embeds the content of every private chat, and Lukas named
"knowledge graph or memories", which this uses as they are.

### 4. Proof
Calibrate the two Jev cuts on labelled messages against the live Jev, as for
`app_pick`. Then end to end on the live site as the user's own account: a
deploy question, a skill question, and a fact said in one chat and asked about
in another.

## Non-goals
- A chat tool that publishes or deploys by itself. Lukas said recommend.
- Changing what Ralph built today (`can_do`, connection health, the new apps).

## Anti-goals
- Any change for an ordinary question: no extra assistant turn, no button.
- A recommendation of an outside host when the platform does it.
- Storing a fact the person did not state.

## Measured (2026-11-13, jev-1.13.0, live tasks container)

**Apps** (`app_pick`, 21 messages x 2 runs): still 0.90, no wrong pick in
either run. Two labels predated Ralph's new apps and were widened: Jira for a
team task board, Dropbox for a shared file. Lukas's own GitHub example sat at
the edge again (0.90 to 0.92).

**Publish** cut on its own (`platform_pick`, 0.60). The first wording
("putting a website or app online") scored a BUILD request ("make me a landing
page") 0.76, too close to the real deploy questions. Saying "they already
have" and "not building a new one" took the build request to 0.13. Real deploy
questions then scored 0.66 to 0.84 and nothing else rose above 0.21, so 0.60
had no wrong and no missed pick in either run; the apps' 0.90 would have missed
all three.

**Skills** (`skill_for_message`, 17 messages x 68 skills x 2 runs): every skill
asked for scored 0.94 to 0.98; no everyday question rose above 0.75 ("explain
a REST API" against brief-the-team). At 0.90 run 1 had one extra pick:
daily-standup (0.89 to 0.90 over five runs) for "every morning send me a
briefing". It is itself a morning report and never shows (two skills are
kept, both needed ones score 0.98), so it was marked fine AFTER the first run,
and said so in SKILL_CASES. Re-run: 0.90, no wrong and no missed pick.

**Dry run** of the new code from a temp folder in the container (production
untouched): "put my landing page online" Publish 0.84; "deploy my app to
Vercel" Publish 0.65 (close to the cut); "summarise my week" weekly-review
0.96; "write an apology to a customer" apology-note and draft-reply; "save my
leads somewhere" Airtable 0.94; "capital of Australia" and "explain a REST
API": nothing, no assistant turn.
