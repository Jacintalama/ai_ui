"""Fake meeting transcripts for testing the AI processor and decision engine.

Each entry is a dict with keys:
    title       str  — meeting title
    date        str  — ISO date string
    attendees   str  — comma-separated names
    transcript  str  — raw transcript text (may contain STT errors / off-topic content)
    summary     str  — pre-baked AI summary (for tests that skip the LLM call)
    problems    list[str]  — tags describing which edge-cases this transcript exercises

Problems covered (used as pytest marks / documentation):
    stt_errors          — speech-to-text misspellings ("cloud", "candy", "eleven labs", …)
    personal_content    — off-topic personal chat that must be filtered
    action_research     — contains a RESEARCH action item
    action_build        — contains a BUILD action item
    action_ask_user     — contains an ASK_USER action item
    action_integrate    — contains an INTEGRATE action item
    all_action_types    — all four action types in one transcript
    no_action_items     — purely informational, no tasks
    critical_priority   — at least one CRITICAL action item
    mixed_priority      — CRITICAL + IMPORTANT + NICE_TO_HAVE in one transcript
    multiple_assignees  — tasks spread across >1 named person
    ambiguous_assignee  — "we should" / "someone should" — no clear owner
    duplicate_items     — same task mentioned twice in different ways
    short_transcript    — under 50 chars (expect AI processor to skip)
    empty_transcript    — completely empty string
    long_transcript     — 50+ speaker turns
    whitespace_only     — only whitespace/newlines, no real content (expect skip)
    single_speaker      — only one participant speaks throughout
    conflicting_decisions — team reverses or contradicts decisions mid-meeting
    deadline_pressure   — explicit hard deadlines mentioned for action items
    external_stakeholder — external client or vendor present in the meeting
    cross_team_blocker  — action items blocked by another team or department
    multi_critical      — multiple simultaneous CRITICAL priority issues
    long_turns          — very long individual speaking turns (100+ words each)
    unicode_names       — speaker names contain non-ASCII / accented characters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FakeTranscript:
    title: str
    date: str
    attendees: str
    transcript: str
    problems: list[str] = field(default_factory=list)
    summary: Optional[str] = None  # pre-baked summary; None = no summary provided


# ---------------------------------------------------------------------------
# 1. EDGE CASES
# ---------------------------------------------------------------------------

EMPTY_TRANSCRIPT = FakeTranscript(
    title="Empty Transcript",
    date="2026-04-01",
    attendees="Ralph, Lukas",
    transcript="",
    problems=["empty_transcript"],
    summary=None,
)

SHORT_TRANSCRIPT = FakeTranscript(
    title="Too Short Transcript",
    date="2026-04-02",
    attendees="Ralph",
    transcript="Quick sync. No updates. Bye.",
    problems=["short_transcript"],
    summary=None,
)

WHITESPACE_ONLY = FakeTranscript(
    title="Whitespace Only",
    date="2026-04-02",
    attendees="Ralph",
    transcript="   \n\n  \t  \n   \n",
    problems=["whitespace_only"],
    summary=None,
)

# ---------------------------------------------------------------------------
# 2. SPEECH-TO-TEXT ERRORS ONLY
# ---------------------------------------------------------------------------

STT_ERRORS_ONLY = FakeTranscript(
    title="Weekly Standup — STT Artifacts",
    date="2026-04-03",
    attendees="Ralph, Lukas, Jacint",
    transcript="""
Ralph (00:00): Alright, quick standup. Lukas, where are you with the cloud integration?

Lukas (00:05): Yeah, cloud code is running great. I pushed a fix to the candy config last night so
traffic actually reaches the container now. The reverse proxy was dropping requests at the /meetings
path but that's sorted.

Ralph (00:22): Nice. And the voice stuff? Are we still using eleven labs?

Lukas (00:28): We're evaluating. eleven labs is expensive — like 30 bucks per million characters.
We might switch to gemini live for real-time voice. It's cheaper and has lower latency. I need to
do more research on the open web UI integration though, to see if we can swap the TTS backend
without breaking anything.

Jacint (00:55): The open web UI pipeline already supports custom TTS endpoints so that part should
be fine.

Ralph (01:10): Great. Let's get that comparison done. Lukas, can you put together the numbers
for eleven labs versus gemini live this week?

Lukas (01:18): Yeah, I'll do that today.

Ralph (01:22): Cool. Anything blocking anyone?

Jacint (01:25): Nope, I'm good.

Ralph (01:27): Alright, let's wrap up.
""",
    problems=["stt_errors", "action_research", "multiple_assignees"],
    summary=None,
)

# ---------------------------------------------------------------------------
# 3. PERSONAL CONTENT MIXED IN
# ---------------------------------------------------------------------------

PERSONAL_CONTENT_MIXED = FakeTranscript(
    title="Sprint Planning — Off-Topic Chatter",
    date="2026-04-04",
    attendees="Ralph, Lukas, Jacint",
    transcript="""
Ralph (00:00): Hey everyone, how was the long weekend?

Lukas (00:04): Oh man, we went to the lake. Weather was perfect. Did you guys do anything?

Jacint (00:10): Stayed home mostly, had the family over. Nothing crazy.

Ralph (00:18): Nice, nice. I took the kids to the aquarium. Anyway — let's get into sprint planning.
So Jacint, the Caddy routing issue. Still broken?

Jacint (00:32): Yeah, still seeing 502s on /meetings. I think candy needs a new upstream block but
I haven't had a chance to look at the config deeply. I'll fix that today — it's blocking the whole
meetings flow.

Ralph (00:48): That's critical, please prioritise it. Lukas — what about the Claude Code runner?
Is it executing tasks yet?

Lukas (00:56): Almost. The cloud code executor runs but it's not writing results back to the DB.
There's a race condition when the background task fires before the DB row is committed. I should
have a fix by end of day.

Ralph (01:15): Good. Any other blockers?

Jacint (01:18): Not really. Oh — did anyone watch the game last night? That penalty was
absolutely ridiculous.

Lukas (01:24): Ha, don't even get me started. The ref was blind.

Ralph (01:30): Haha, okay okay. Let's stay on track. We should also look into integrating
n8n with the calendar service so meetings can auto-schedule tasks. That's on the backlog
but it'd be nice to have.

Lukas (01:45): Yeah, I can look at the n8n workflow for that after the critical fixes.

Ralph (01:50): Perfect. Let's close this out.
""",
    problems=[
        "personal_content",
        "stt_errors",
        "action_build",
        "critical_priority",
        "mixed_priority",
        "multiple_assignees",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 4. ALL FOUR ACTION TYPES IN ONE MEETING
# ---------------------------------------------------------------------------

ALL_ACTION_TYPES = FakeTranscript(
    title="Platform Review — All Action Types",
    date="2026-04-07",
    attendees="Ralph, Lukas, Jacint, Sarah",
    transcript="""
Ralph (00:00): Okay team, let's go through the platform review. Lots to cover.

Sarah (00:08): Before we start — the webhook handler is throwing 500s on the GitHub push event.
It's blocking our CI notifications. That needs to be fixed today; it's critical.

Ralph (00:18): Agreed, Jacint can you take that?

Jacint (00:20): Yes, I'll look at it right after this call. It's probably the HMAC signature
verification, I've seen that fail when the secret rotates.

Ralph (00:30): Good. Lukas — the voice bot evaluation. Where are we?

Lukas (00:35): So we're deciding between eleven labs and gemini live. I need to run the numbers
on cost per minute for our expected call volume. Can someone confirm with the team what the
target call volume is going to be? Like are we thinking 100 hours a month or more like 1000?

Ralph (00:52): Good question. That's a decision for the business side. I'll ask Marcus today and
get back to you.

Lukas (01:01): Also, once we pick a provider, we need to integrate it with open web UI. The
TTS settings are configurable but we need the API keys loaded into the environment and the
candy proxy updated to route voice requests correctly.

Sarah (01:18): The cloud code executor also needs access to those env vars at runtime. We
might need to update the Docker compose file.

Ralph (01:28): Okay so to summarise that thread: Lukas researches pricing, I ask Marcus about
volume targets, then we integrate the chosen provider. Got it. Sarah — what about the auth service?

Sarah (01:40): We need to connect the auth service to Entra ID. We have the client credentials
but they haven't been added to the MCP proxy config yet. I can set that up once I confirm the
redirect URI — I need to check which URI the Entra app registration is pointing to.

Ralph (01:58): Sounds like an ASK_USER for the IT team. Can you email Tom?

Sarah (02:04): Yeah, I'll do that today.

Ralph (02:10): Great. What else?

Lukas (02:14): One more thing — it might be nice to have a dashboard showing action item
completion rates across meetings. Not urgent, just a thought.

Ralph (02:22): Put it on the backlog. Okay let's close this out.
""",
    problems=[
        "all_action_types",
        "stt_errors",
        "critical_priority",
        "mixed_priority",
        "multiple_assignees",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 5. NO ACTION ITEMS — PURELY INFORMATIONAL
# ---------------------------------------------------------------------------

NO_ACTION_ITEMS = FakeTranscript(
    title="System Architecture Walkthrough",
    date="2026-04-08",
    attendees="Ralph, Lukas, New Hire (Priya)",
    transcript="""
Ralph (00:00): Priya, welcome to your first architecture walkthrough. I'll hand it to Lukas
to explain how the platform is structured.

Lukas (00:10): Sure. So at the top level we have Cloudflare sitting in front of everything.
Traffic hits our Hetzner VPS and goes through Caddy as the reverse proxy. Caddy handles TLS
and routes to an API gateway, which then fans out to our individual services.

Priya (00:30): And those services — what are the main ones?

Lukas (00:33): Open WebUI is the main user-facing app. Then we have the MCP proxy, which
brokers tool calls between the LLM and backend services like GitHub, Gmail, n8n, and our
custom meeting storage service. The webhook handler listens to events from external platforms
and triggers automations.

Priya (01:00): Cool. What database are you using?

Lukas (01:02): Postgres, running in a Docker container. Each service has its own schema.
Auth is handled via Entra ID for the admin portal and via API keys for Open WebUI.

Ralph (01:20): We also have Grafana and Loki for observability. Promtail ships logs from
all containers.

Priya (01:30): This is really helpful, thanks. I think I have a solid picture now.

Ralph (01:35): Great. Any questions before we move on?

Priya (01:37): Not right now, I'll read through the docs and come back if I do.

Ralph (01:40): Perfect.
""",
    problems=["no_action_items"],
    summary=None,
)

# ---------------------------------------------------------------------------
# 6. AMBIGUOUS ASSIGNEES
# ---------------------------------------------------------------------------

AMBIGUOUS_ASSIGNEE = FakeTranscript(
    title="Backend Sync — Vague Ownership",
    date="2026-04-09",
    attendees="Ralph, Lukas",
    transcript="""
Ralph (00:00): Quick sync on the backend stuff.

Lukas (00:04): Yeah, so we should probably look into why the meeting KB push is sometimes
timing out. Not sure if it's the file upload or the polling loop.

Ralph (00:15): Someone should investigate. Also, we need to figure out which model to default
to in open web UI — we've been leaving it as gpt-4-turbo but Claude is probably better for
our use case. We should decide on that.

Lukas (00:30): Agreed. And there's the question of whether to cache model responses for
repeated queries. That could save cost. We should research that at some point.

Ralph (00:42): Yeah, and we need to get those Loki retention policies in place before the
disk fills up. That's been on the list for a while.

Lukas (00:52): True. It'd also be cool to add a meeting search endpoint to the API.
Not urgent, just a nice-to-have.

Ralph (01:00): For sure. Okay, I think we've got a list. Let's action it.
""",
    problems=[
        "ambiguous_assignee",
        "action_research",
        "action_build",
        "action_ask_user",
        "mixed_priority",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 7. DUPLICATE / REPEATED ACTION ITEMS
# ---------------------------------------------------------------------------

DUPLICATE_ITEMS = FakeTranscript(
    title="Monday Standup — Repeated Tasks",
    date="2026-04-10",
    attendees="Ralph, Jacint",
    transcript="""
Ralph (00:00): Morning Jacint. What are you on today?

Jacint (00:04): Still on the Caddy config. I need to fix the /meetings upstream block —
502s are still happening.

Ralph (00:12): Right, that routing issue. Can you make that your top priority?

Jacint (00:16): Yeah, it's first on my list.

Ralph (00:20): Cool. And there was also that thing from last week — the Caddy reverse proxy
wasn't correctly forwarding headers to the meetings container. Is that the same issue?

Jacint (00:30): It's the same root cause. The upstream block is broken so both problems
go away when I fix that one config.

Ralph (00:38): Got it. So just one fix, two symptoms. Make sure you test both paths after.

Jacint (00:44): Will do.

Ralph (00:46): Anything else?

Jacint (00:48): I should also look at the loki log queries — the alerts dashboard is
showing stale data. That's a separate issue, probably the datasource config in Grafana.

Ralph (00:58): Yeah, tackle the Caddy issue first since it's critical, then Grafana.

Jacint (01:04): Sounds good.
""",
    problems=[
        "duplicate_items",
        "action_build",
        "critical_priority",
        "stt_errors",
        "multiple_assignees",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 8. CRITICAL PRIORITY — PRODUCTION INCIDENT
# ---------------------------------------------------------------------------

PRODUCTION_INCIDENT = FakeTranscript(
    title="Incident: Auth Service Down",
    date="2026-04-11",
    attendees="Ralph, Lukas, Jacint",
    transcript="""
Ralph (00:00): Okay, we have an incident. The auth service is returning 500 on all login
attempts. Open Web UI is completely inaccessible.

Lukas (00:08): I'm looking at the logs now. The Entra ID token validation is failing —
looks like the client secret expired.

Ralph (00:16): Can we rotate it right now?

Lukas (00:18): I need the Entra admin portal access. Jacint, can you log into Azure and
rotate the secret for the AIUI app registration?

Jacint (00:24): On it. Pulling it up now.

Ralph (00:28): While Jacint does that — Lukas, we need to add secret expiry alerting.
This can't happen again. Can you set up a monitor that pings us 30 days before expiry?

Lukas (00:38): Yes, I'll set that up today as a n8n workflow. We should also store
the secret rotation procedure in the knowledge base so whoever is on call can handle it.

Ralph (00:50): Agreed. Jacint — how long does the rotation take?

Jacint (00:53): Few minutes. I'll paste the new secret into the Docker compose .env and
restart the auth service container.

Ralph (01:00): Good. Once it's up, test all the auth paths — login, token refresh,
MCP proxy auth.

Jacint (01:06): Will do.

Ralph (01:10): Lukas, after the secret alerting, write up the post-mortem doc. We need
to understand why we didn't catch this before it hit prod.

Lukas (01:18): Sure. I'll have a draft by EOD.

Ralph (01:22): Thanks both. Let's get this resolved.
""",
    problems=[
        "action_build",
        "action_integrate",
        "action_ask_user",
        "critical_priority",
        "multiple_assignees",
        "stt_errors",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 9. HEAVY STT ERRORS — LOTS OF MISSPELLINGS
# ---------------------------------------------------------------------------

HEAVY_STT_ERRORS = FakeTranscript(
    title="Voice Integration Planning",
    date="2026-04-12",
    attendees="Ralph, Lukas",
    transcript="""
Ralph (00:00): Let's plan the voice bot. Are we going with eleven labs or something else?

Lukas (00:06): I've been looking at gemini live and also eleven labs. Gemini live has
lower latency — like 300ms versus eleven labs at around 600ms. But eleven labs quality
is better. Also eleven labs has a conversational AI product now, which might save us
from building the turn-taking logic ourselves.

Ralph (00:28): And cost?

Lukas (00:30): eleven labs is about $11 per hour of audio. Gemini live is hard to
price because it charges per token, not per minute. I'd need to estimate our average
conversation length to compare properly.

Ralph (00:45): Okay, do that estimate. What does the architecture look like with open
web UI?

Lukas (00:52): So open web UI supports custom TTS endpoints. We'd configure it to
call our chosen provider. Requests go through candy, so we'd need a new candy route
for the voice endpoint — something like /voice/tts proxying to the provider's API.

Ralph (01:10): And cloud code — does it need to be aware of voice?

Lukas (01:14): Cloud code tasks can include voice transcripts as context if we feed
them through the mcp proxy. So if a voice call creates action items, cloud code can
act on them. We'd use cloud to summarise the voice session and pass it to the decision
engine.

Ralph (01:30): That's cool. So the flow is: voice call → eleven labs or gemini → open
web UI receives transcript → cloud summarises → decision engine classifies → tasks
get created.

Lukas (01:42): Exactly. We could also hook this to fathom so all our meetings auto-flow
into the pipeline.

Ralph (01:50): Love it. Let's get the cost comparison done first. Can you have it
by end of week?

Lukas (01:55): Yeah, I'll have the numbers by Thursday.
""",
    problems=[
        "stt_errors",
        "action_research",
        "action_build",
        "multiple_assignees",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 10. LONG TRANSCRIPT — MANY SPEAKERS, MANY ITEMS
# ---------------------------------------------------------------------------

LONG_TRANSCRIPT = FakeTranscript(
    title="Quarterly Planning — All Teams",
    date="2026-04-14",
    attendees="Ralph, Lukas, Jacint, Sarah, Marcus, Priya",
    transcript="""
Ralph (00:00): Alright everyone, quarterly planning time. Let's be efficient because we
have a lot to cover. Marcus, you kick off with the business priorities.

Marcus (00:12): Sure. Top priority this quarter is the enterprise onboarding flow. We
need to be able to spin up a new tenant — provision their knowledge base, configure
their MCP tools, set their permissions — all in under 10 minutes. Currently it's a
manual process that takes an hour.

Ralph (00:32): Got it. Lukas, that sounds like an automation task for you.

Lukas (00:36): Yeah, I can build a tenant provisioning workflow. I'll need to know
which MCP tools each plan tier gets though. Marcus, can you send me the tier matrix?

Marcus (00:46): I'll send it over after this call.

Ralph (00:50): Good. Sarah — auth?

Sarah (00:54): We need Entra ID SSO for enterprise tenants. Right now we have API key
auth only. I need to look into whether open web UI supports Entra SSO natively or if
we have to build a wrapper.

Ralph (01:08): That's a research task then?

Sarah (01:10): Yes. I'll investigate this week and report back on what we need to build.

Ralph (01:16): Perfect. Jacint — infrastructure?

Jacint (01:20): We have three things. First, the Hetzner server is at 70% disk — we
need to clean up old Docker images and add a retention policy for Loki logs. That's
starting to get critical, we could fill up within a month at current rate.

Ralph (01:36): Okay, that's critical. Do that this week.

Jacint (01:40): Second: we should consider adding a second Hetzner node for redundancy.
If the VPS goes down, everything goes down. Not urgent but worth planning.

Ralph (01:50): Agreed, add it to the backlog. Third?

Jacint (01:54): Third: the Caddy config needs a health check endpoint at /.well-known/health
that returns the status of each upstream service. We currently have no way to see which
service is down without SSHing in.

Ralph (02:08): That's important. Priya, can you take the health check endpoint since
you're learning the codebase?

Priya (02:14): Sure, happy to. Should I add it to all services or just Caddy?

Ralph (02:18): Just Caddy routing to each service's existing /health endpoint. Keep it simple.

Priya (02:24): Got it, I'll do that this week.

Ralph (02:28): Lukas — back to you. What else is on your plate?

Lukas (02:32): The meeting decision engine needs some tuning. We're getting too many
RESEARCH items classified as BUILD items — the LLM is confused by action items that
mention "implement research findings". I want to update the classification prompt.

Ralph (02:48): Is that blocking anything?

Lukas (02:52): Not blocking, but it means some tasks go to the wrong queue and have
to be manually reclassified.

Ralph (02:58): Okay, important but not critical. Add it to your list after the tenant
provisioning work.

Lukas (03:04): Also — the voice bot. I've been doing the cost comparison between
eleven labs and gemini live. Eleven labs is $11 per hour, gemini live is roughly
$4 per hour at our expected volume. That's a big difference.

Marcus (03:20): That's a no-brainer then — gemini live.

Lukas (03:22): Well, quality is better with eleven labs. We'd need to listen to
both before deciding.

Ralph (03:30): Can we get a demo from both? Lukas, set up a trial account for gemini
live and generate a sample. We already have eleven labs access.

Lukas (03:40): I'll do that today.

Sarah (03:44): One more thing — the cloud code executor is running in the tasks service
but it doesn't have network access to the MCP proxy. It can plan and describe changes
but it can't actually call any tools. We need to fix the Docker network config.

Ralph (03:58): Is that blocking task execution?

Sarah (04:02): Yes, for any task that requires tool use. Claude falls back to a
NEEDS_STEPS response instead of completing automatically.

Ralph (04:10): That's critical. Jacint, can you fix the Docker network config today?

Jacint (04:14): I'll do it now. It's probably just a network name mismatch in the
compose file.

Ralph (04:20): Great. Anything else blocking?

Priya (04:24): Not from me.

Marcus (04:26): I'll send the tier matrix to Lukas today.

Ralph (04:30): Perfect. Let me just recap what we've committed to this week:
Jacint — disk cleanup and Docker network fix today. Priya — Caddy health check endpoint.
Lukas — tenant provisioning workflow, gemini live demo, voice cost analysis.
Sarah — Entra SSO research. Marcus — tier matrix to Lukas.
Anything I'm missing?

Lukas (04:48): The classification prompt tuning.

Ralph (04:50): Right, next week for that one. Okay, that's a wrap. Good session.
""",
    problems=[
        "long_transcript",
        "all_action_types",
        "stt_errors",
        "critical_priority",
        "mixed_priority",
        "multiple_assignees",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 11. SINGLE SPEAKER — solo status update, no other participants
# ---------------------------------------------------------------------------

SINGLE_SPEAKER = FakeTranscript(
    title="Solo Status Update — Ralph",
    date="2026-04-15",
    attendees="Ralph",
    transcript="""
Ralph (00:00): Quick solo update for the record since the team is out today. I've been
working on the n8n workflow for tenant provisioning. The first three steps — creating
the Postgres schema, setting up the knowledge base collection, and generating the API
key — are all wired up and working in my dev environment.

Ralph (01:15): Still need to handle the MCP tool assignment step. Each tenant gets a
different set of tools based on their plan tier. Marcus was supposed to send the tier
matrix but I haven't seen it yet. I'll ping him again.

Ralph (02:30): Also: the Caddy health check endpoint is partially done. I added the
top-level route but haven't tested the upstream probing logic yet. Priya was going to
take this one but she's on leave this week.

Ralph (03:45): One thing I noticed: the Loki disk usage jumped overnight — went from
70% to 74%. If this keeps up we'll hit 80% by the end of the week. I'll run the log
retention cleanup script now rather than waiting for Jacint.

Ralph (04:30): That's the update. Nothing critical but the disk situation needs
monitoring. I'll check again tomorrow.
""",
    problems=["single_speaker", "action_build", "action_ask_user"],
    summary=None,
)

# ---------------------------------------------------------------------------
# 12. CONFLICTING DECISIONS — team reverses direction mid-meeting
# ---------------------------------------------------------------------------

CONFLICTING_DECISIONS = FakeTranscript(
    title="Architecture Decision — Voice Provider",
    date="2026-04-15",
    attendees="Ralph, Lukas, Marcus",
    transcript="""
Ralph (00:00): Okay, final call on the voice provider. Lukas, what did the numbers show?

Lukas (00:06): ElevenLabs comes out at about $11 per hour for TTS. Gemini Live at our
expected volume is around $4 per hour. Quality-wise ElevenLabs is noticeably better —
more natural intonation, better handling of pauses. Gemini Live sounds a bit robotic.

Ralph (00:22): I think quality wins here. We're positioning this as a premium product.
Let's go with ElevenLabs.

Marcus (00:28): Agreed, let's not cheap out on the customer-facing voice experience.

Lukas (00:32): Okay, I'll start the ElevenLabs integration. I'll need to add the API
key to the environment and build the candy proxy route.

Ralph (00:42): Perfect. Decision made — ElevenLabs.

Lukas (01:00): Actually — I just pulled up the ElevenLabs pricing page again. The TTS
rate is $11 per hour but if we want their conversational AI product — which handles
turn-taking and interruption detection so we don't have to build that ourselves — it's
closer to $22 per hour. That changes the math considerably.

Ralph (01:16): $22 per hour? That's way over budget. We assumed TTS-only but the
client spec says the voice bot needs natural conversation flow. We can't ship TTS-only.

Marcus (01:26): At any reasonable call volume that cost is unsustainable. Gemini Live
all-in is $4 to $5 per hour including the LLM side?

Lukas (01:34): Correct. At 1,000 hours a month that's a $17,000 difference.

Marcus (01:40): We have to reverse the decision. It has to be Gemini Live.

Ralph (01:46): Agreed. We're going with Gemini Live. Lukas, do not start the ElevenLabs
integration — pivot to Gemini Live instead.

Lukas (01:54): Got it. I'll set up the Gemini Live trial today and do a quality check
before we fully commit. I want to make sure the voice quality is acceptable before we
announce this to customers.

Ralph (02:02): Good call. Marcus, can you hold on adding this to the roadmap until
Lukas confirms the quality is acceptable? Give us until end of week.

Marcus (02:08): Sure, Friday works.
""",
    problems=[
        "conflicting_decisions",
        "action_research",
        "action_build",
        "multiple_assignees",
        "stt_errors",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 13. DEADLINE PRESSURE — hard deadlines drive urgency
# ---------------------------------------------------------------------------

DEADLINE_PRESSURE = FakeTranscript(
    title="Pre-Demo Crunch — Enterprise Onboarding",
    date="2026-04-15",
    attendees="Ralph, Lukas, Jacint, Sarah",
    transcript="""
Ralph (00:00): Hard deadline everyone: the enterprise client demo is Monday at 10am.
That's four days away. We need the tenant provisioning flow working end-to-end by
Friday so we have the weekend to test. Let's go through what's left.

Lukas (00:16): Provisioning workflow is about 80% done. Schema creation and KB
collection setup work. Still need to wire up MCP tool assignment — probably half a
day of work.

Ralph (00:28): Can you finish that today? We need tomorrow for integration testing.

Lukas (00:32): If I start right after this call, yes — tonight.

Ralph (00:36): Do it. Sarah — Entra SSO?

Sarah (00:42): This is the problem. I emailed IT three days ago about the redirect URI
and still no response. Without it I cannot finish the auth integration. The client
specifically asked for SSO and it's in the contract.

Ralph (00:56): That is critical. I'm calling Tom directly right after this meeting.
If there's no response by noon today I escalate to his manager. The demo cannot go
ahead without SSO.

Sarah (01:06): If I get the URI today, I can have the integration done by Friday
morning. That gives us the weekend to test.

Ralph (01:14): You'll have it by noon. Jacint — infrastructure?

Jacint (01:20): The Docker network issue is fixed — cloud code executor can reach the
MCP proxy now. I also ran the disk cleanup: we're back to 58% and I set up a weekly
cron to auto-clean old Docker images.

Ralph (01:34): Good. Can you also make sure the staging environment matches production
by Thursday? The client will be looking at our staging URL during the demo.

Jacint (01:42): I'll sync staging configs Thursday morning.

Ralph (01:48): Perfect. Lukas — we also need a demo script. Step-by-step walkthrough.

Lukas (01:54): Can you write that? You know the narrative better than I do.

Ralph (01:58): Fair. I'll draft it by Thursday. Sarah — once SSO is in, full end-to-end
test as a new enterprise user on Friday?

Sarah (02:04): Yes. Full walkthrough — provision, login via SSO, run a meeting summary,
create a task. Everything the client will see.

Ralph (02:12): To be explicit about timelines: tonight Lukas finishes provisioning.
Noon today I get Sarah the redirect URI. Friday morning Sarah tests SSO end-to-end.
Thursday I write the demo script and Jacint syncs staging. Any of those at risk?

Lukas (02:26): I'm confident on tonight.

Sarah (02:28): Friday is achievable if I have the URI by noon.

Jacint (02:30): Thursday morning staging sync is fine.

Ralph (02:34): Let's go.
""",
    problems=[
        "deadline_pressure",
        "action_build",
        "action_ask_user",
        "critical_priority",
        "mixed_priority",
        "multiple_assignees",
        "stt_errors",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 14. EXTERNAL STAKEHOLDER — vendor / client present in meeting
# ---------------------------------------------------------------------------

EXTERNAL_STAKEHOLDER = FakeTranscript(
    title="Vendor Review — ElevenLabs Integration Call",
    date="2026-04-15",
    attendees="Ralph, Lukas, Alex (ElevenLabs), James (ElevenLabs)",
    transcript="""
Ralph (00:00): Thanks for joining, Alex, James. We're evaluating ElevenLabs for our
voice assistant product. Lukas has been leading the technical assessment on our side.

Alex (ElevenLabs) (00:12): Happy to be here. We're seeing a lot of interest in
conversational AI right now. What's the primary use case — TTS only or the full
conversational product with turn-taking?

Lukas (00:24): TTS to start. We handle the LLM side ourselves via open web UI. We
need a high-quality voice layer that works with our candy proxy and keeps latency
under 500ms for the first chunk.

James (ElevenLabs) (00:38): That's very achievable. Our streaming endpoint typically
delivers the first audio chunk in 200 to 300ms. We also have a websocket API at around
150ms in ideal conditions. I'll share the docs link after the call.

Ralph (00:52): What about pricing at scale? We're estimating 10 to 50 million
characters a month initially.

Alex (ElevenLabs) (01:02): At that range you'd be on an enterprise contract. I can
put together a quote this afternoon — we'd also include a 99.9% uptime SLA and a
dedicated support Slack channel.

Lukas (01:14): That's important for us since this is customer-facing. One more
technical question: the websocket API — is it documented well enough to integrate
without support? We'd be routing through an internal proxy, not calling it directly.

James (ElevenLabs) (01:28): Yes, the docs are thorough. There are code samples for
Python and Node. The main thing to watch is the binary frame format — audio comes back
as base64-encoded PCM in the JSON envelope, not a raw binary stream. That trips people
up initially.

Lukas (01:44): Good to know. We'd need to decode that on the proxy side before
forwarding to open web UI. I'll prototype that this week.

Ralph (01:52): So next steps from our side: Lukas prototypes the websocket integration
using the free trial credits. We review the enterprise pricing quote when Alex sends
it. Then we make a final decision by end of week.

Alex (ElevenLabs) (02:04): We'll have the quote over by 5pm today. And feel free to
reach out if you hit anything in the integration — James is available for technical
questions.

Ralph (02:12): Perfect. Thank you both, we'll be in touch.
""",
    problems=[
        "external_stakeholder",
        "action_research",
        "action_integrate",
        "multiple_assignees",
        "stt_errors",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 15. CROSS-TEAM BLOCKER — work blocked on other teams / departments
# ---------------------------------------------------------------------------

CROSS_TEAM_BLOCKER = FakeTranscript(
    title="Integration Blockers — IT and Security Dependencies",
    date="2026-04-16",
    attendees="Ralph, Lukas, Sarah",
    transcript="""
Ralph (00:00): Let's go through our external blockers. Several things are stuck waiting
on other teams. Sarah, start with IT.

Sarah (00:08): The Entra SSO integration is completely blocked on IT. I've been waiting
five days for Tom to configure the app registration redirect URI. Without it the OAuth
flow cannot complete. The enterprise demo is Monday — this is critical. I have ticket
IT-4471 open but zero response despite two follow-up emails.

Ralph (00:28): I'll escalate to Tom's manager today. If a ticket isn't getting response
in five days that's a process failure. Lukas — what's blocking you?

Lukas (00:36): Two things from different teams. First, Gemini Live API keys. Our Google
Cloud billing account still isn't approved for the Gemini API. Finance needs to sign
off on a spend limit increase. I submitted the request Monday — last time this took a
full week to process.

Ralph (00:52): That could blow past the demo deadline.

Lukas (00:56): Exactly. I can stub out the voice integration with mock responses so
development continues, but we can't do real end-to-end tests without approved access.

Ralph (01:04): I'll email the finance contact today and flag the deadline. Second
blocker?

Lukas (01:10): Cloud code executor needs write access to the shared GCS bucket for
storing task artifacts. That's a DevOps team permissions request — three business day
SLA. I submitted it yesterday so earliest we hear back is Friday.

Ralph (01:22): Again, cutting it close. Work around it with local storage for now and
migrate after the demo. Sarah — you mentioned a security review?

Sarah (01:30): Yes, and this is the one I'm most worried about. The CISO team needs to
sign off on the MCP proxy before we can give it access to any external APIs — ElevenLabs,
Gemini, Google Drive, all of it. I submitted the architecture diagram last week but
haven't heard back. Without that sign-off we legally cannot connect to external services.

Ralph (01:50): I wasn't fully aware that was a hard gate. How long does their review
normally take?

Sarah (01:56): One to two weeks for a new service, but can be expedited to 48 hours if
a director sponsors it.

Ralph (02:04): I'll get Marcus to sponsor it today. This blocks more than the demo —
it blocks everything we're building. Can you put together a one-page summary of what
the MCP proxy does and what APIs it touches? We need something concrete to hand to the
CISO team.

Sarah (02:18): I can have that by noon.

Ralph (02:22): Good. Lukas — while waiting on permissions, finish everything that
doesn't require external access: provisioning workflow DB steps, health check endpoints,
classification prompt tuning.

Lukas (02:32): That keeps me busy through the week. I'll flag immediately if anything
else surfaces.

Ralph (02:38): Let's keep moving where we can. I'll chase IT, finance, and the CISO
sponsor today and report back by EOD.
""",
    problems=[
        "cross_team_blocker",
        "action_ask_user",
        "critical_priority",
        "deadline_pressure",
        "multiple_assignees",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 16. MULTI-CRITICAL — several simultaneous CRITICAL incidents
# ---------------------------------------------------------------------------

MULTI_CRITICAL = FakeTranscript(
    title="Emergency: Multiple Production Incidents",
    date="2026-04-16",
    attendees="Ralph, Lukas, Jacint, Sarah",
    transcript="""
Ralph (00:00): We have three active incidents. Everyone stay on the call. Jacint, auth.

Jacint (00:06): Still broken. The Entra secret rotation fixed the 500s but now the
MCP proxy is rejecting every request with a 403. It's using the old JWT public key to
validate tokens — the proxy config wasn't reloaded after the secret was rotated.
Nobody can use any MCP tools.

Ralph (00:20): CRITICAL. What do you need to fix it?

Jacint (00:24): I need the new public key value to update the proxy config, then a
container restart. Two minutes once I have the key.

Lukas (00:30): Pasting the key in Slack now.

Ralph (00:32): Jacint, fix that immediately. You have five minutes. Second incident — Lukas.

Lukas (00:38): The n8n meeting processor crashed at 3am. The Fathom email poller got
a malformed JSON response from the Gmail API and the error wasn't caught — it put the
entire workflow into an error state. Eleven meetings that came in since 3am haven't
been processed, summarised, or pushed to the knowledge base.

Ralph (00:56): CRITICAL. Team is flying blind — we have no meeting summaries for this
morning. Can you fix and reprocess?

Lukas (01:02): I've already patched the error handling in the n8n workflow. Manual
reprocessing takes about 20 minutes. I'll start it the moment the MCP proxy is back
up because the processor needs to call the LLM through the proxy.

Ralph (01:14): Okay, that's dependent on Jacint's fix. Go as soon as the proxy is up.
Third incident — Sarah.

Sarah (01:20): Worst one. A cloud code executor task ran overnight. It was supposed to
update a single Caddy route but it ended up overwriting the entire Caddy configuration
file. All external routing is broken — every service is returning 502 to users. Direct
container access still works but nothing is reachable through the domain.

Ralph (01:40): CRITICAL. The entire platform is down for users. Do we have a config backup?

Sarah (01:44): Yes — I took one last Thursday before the routing changes. I can restore
from that in under a minute. I just need a go-ahead since it'll overwrite the current file.

Jacint (01:52): Do it. The current config is broken. Thursday's backup is better than
what's there now.

Ralph (01:56): Sarah, restore the Caddy config right now. That's the most urgent fix.

Sarah (02:00): Restoring now.

Ralph (02:04): Good. After all three fires are out, we do a post-mortem. Lukas — why
did the cloud code executor have write access to the Caddy config directory?

Lukas (02:12): It's running as root in the container. I'll fix the permissions today —
the executor should only have write access to the tasks directory, nothing else.

Ralph (02:20): That is how we end up in situations like this. Make it your first task
after the meeting queue is reprocessed. Priority order: Sarah restores Caddy now.
Jacint updates the MCP proxy key and restarts. Lukas reprocesses meetings once proxy
is up. Then executor permissions. Check back in 30 minutes.

Jacint (02:36): Proxy key updated — restarting now.

Sarah (02:38): Caddy restored. Routes are coming back up.

Lukas (02:42): Queue reprocessing starting in 60 seconds.
""",
    problems=[
        "multi_critical",
        "critical_priority",
        "multiple_assignees",
        "action_build",
        "stt_errors",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 17. LONG TURNS — individual speeches exceed 100 words
# ---------------------------------------------------------------------------

LONG_TURNS = FakeTranscript(
    title="Technical Deep Dive — MCP Proxy Architecture",
    date="2026-04-16",
    attendees="Ralph, Lukas, Priya",
    transcript="""
Ralph (00:00): Priya is taking over ownership of the MCP proxy this quarter. Lukas,
full technical walkthrough please.

Lukas (00:08): Sure. The MCP proxy is the central nervous system of the platform.
Every tool call the LLM makes goes through it — when open web UI sends a request like
"search the web for X" or "fetch the latest GitHub issues", it hits the proxy first.
The proxy validates the JWT, determines which tools the tenant is authorised to use
based on their plan tier, routes the request to the appropriate backend service,
handles retries on transient failures, logs every tool call to Postgres for audit
purposes, and streams the response back to open web UI. The key design principle is
that no LLM ever calls an external API directly — all external I/O goes through the
proxy so we have a single place to enforce rate limits, audit access, and apply
security policy. We currently have eight registered tools: web-search, github, gmail,
gdrive, meetings, tasks, calendar, and the open-webui knowledge base. Each one is a
separate microservice in Docker, and the proxy holds their internal network addresses
in its config. Adding a new tool is a two-step process: register its address in the
proxy config, and implement the standard tool interface — a POST /invoke endpoint that
accepts a JSON body and streams back results.

Priya (03:10): What happens if one of those services goes down mid-request?

Lukas (03:16): Great question — this is where the circuit breaker comes in. The proxy
runs health checks against every tool service every thirty seconds. If a service fails
three consecutive checks, the proxy marks it as unavailable and returns a structured
error to the LLM rather than waiting for a timeout. The LLM can then gracefully tell
the user the capability is temporarily down instead of hanging. The circuit breaker
state is held in memory — not persisted — so if the proxy itself restarts, the breaker
resets to closed for all services. That's a known limitation: in theory a flapping
service could cause repeated error bursts after proxy restarts. In practice we haven't
hit it, but if we do the fix is to back the breaker state with Redis. The health check
endpoints on each tool service are simple GET /health routes returning a JSON status
object. Priya — the Caddy health dashboard you're building will aggregate those. You
can call the proxy's own GET /health/tools endpoint which returns a rollup of all
downstream service states. That's probably the best place to start understanding how
the whole thing fits together.

Ralph (06:00): What about internal auth — between the proxy and the tool services?

Lukas (06:06): Right now we use shared secrets — each tool service has an internal
API key set in its Docker environment, and the proxy sends it in the Authorization
header on every request. This is acceptable for an internal Docker network because
traffic never leaves the host machine, but it is not great practice. The keys are
rotated manually and there is no automated expiry. When we have bandwidth, the right
long-term solution is mutual TLS between containers, or at minimum a secret manager
with automatic rotation like HashiCorp Vault. Priya, when you are working in the proxy
codebase, treat the authentication middleware as the highest-risk module — a bug there
affects every single tool call on the platform. My strong advice is to write tests
before you change anything in that layer. The coverage is about 80% right now; the
untested edges are mostly in the retry and circuit breaker logic, which is also on
the backlog.

Priya (08:30): How do I run the test suite locally?

Lukas (08:36): You will need Docker Compose and the dev .env file — ask Ralph for the
credentials. Then docker compose up -d to start the dependency containers, followed
by pytest in the mcp-proxy directory. The test suite spins up mock tool services and
runs full request cycles end-to-end. It takes about 90 seconds to complete. If you
want to orient yourself before touching any code, start with the routing module —
it is the simplest part of the proxy and will give you a solid mental model for how
requests flow through before you get into the middleware chain.

Ralph (10:00): Good overview. Priya, two action items for you this week: write the
Caddy health dashboard endpoint we discussed, and get the dev environment set up so
you can run the test suite. Lukas — can you schedule an hour to pair with Priya on the
circuit breaker tests that are missing?

Lukas (10:14): Yes, Friday afternoon works for me.

Priya (10:18): That works for me too.

Ralph (10:20): Great. Let's schedule it.
""",
    problems=[
        "long_turns",
        "action_build",
        "multiple_assignees",
        "stt_errors",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 18. UNICODE NAMES — speakers with non-ASCII / accented characters
# ---------------------------------------------------------------------------

UNICODE_NAMES = FakeTranscript(
    title="Multilingual Team Standup",
    date="2026-04-16",
    attendees="Renée, Łukasz, José, Søren",
    transcript="""
Renée (00:00): Good morning everyone. Łukasz, can you start?

Łukasz (00:06): Sure. I finished the candy routing fix last night. The /meetings
upstream block is correct now and the 502 errors are gone. I also added a basic health
check endpoint to the MCP proxy container that Renée asked for in our last meeting.

Renée (00:22): Excellent. José — cloud code integration?

José (00:28): I got the cloud code executor running inside the Docker network. It now
has access to the MCP proxy so it can actually call tools end-to-end instead of
falling back to NEEDS_STEPS. I did a quick smoke test — gave it a task to fetch the
latest GitHub issues and it handled it fully automatically.

Søren (00:46): Does it handle errors gracefully? If a tool call times out the executor
should retry rather than crash.

José (00:54): Right now if a tool times out, the executor gets an unhandled exception
and the task goes to failed state. We need retry logic. I'll add that today — probably
three retries with exponential back-off.

Renée (01:06): Yes please. Søren raised this in the retro. Søren — Grafana alerting?

Søren (01:14): I set up the Loki log queries for error rate monitoring. Alerts now fire
into Discord when error rates exceed 5% over a five-minute window. The threshold needs
tuning though — we're getting false positives during deployments when services restart
briefly. I want to add a deployment annotation so Grafana suppresses alerts during
rolling restarts.

Renée (01:34): Good. Make the threshold tuning your first task today. Łukasz — should
we add integration tests for the new health check endpoint?

Łukasz (01:42): Yes, I'll add them to the existing suite this afternoon.

Renée (01:46): Perfect. Summary: José adds retry logic to the cloud code executor,
Søren tunes alert thresholds, Łukasz adds health check tests. I'll update the docs
to reflect the new candy routing config. Any blockers?

José (01:58): None from me.

Søren (02:00): All clear.

Łukasz (02:02): Same. Let's go.
""",
    problems=[
        "unicode_names",
        "action_build",
        "multiple_assignees",
        "stt_errors",
    ],
    summary=None,
)

# ---------------------------------------------------------------------------
# 19. PRE-BAKED SUMMARIES (for tests that skip the LLM round-trip)
# ---------------------------------------------------------------------------

WITH_SUMMARY_BUILD = FakeTranscript(
    title="Caddy Fix Standup",
    date="2026-04-05",
    attendees="Ralph, Jacint",
    transcript="""
Ralph (00:00): Jacint, the /meetings route is still returning 502.

Jacint (00:04): Yeah I know, I need to update the Caddy upstream block. I'll fix it now.

Ralph (00:08): Please do, it's blocking the whole meetings flow.
""",
    problems=["action_build", "critical_priority"],
    summary="""## Caddy Fix Standup — Summary

The `/meetings` route on Caddy is returning 502 errors, blocking the meetings pipeline.
Jacint identified the cause as a misconfigured upstream block in the Caddy config.

## Action Items

- 🔴 CRITICAL **Jacint**: Update the Caddy upstream block to fix 502 on `/meetings`.
""",
)

WITH_SUMMARY_RESEARCH = FakeTranscript(
    title="Voice Provider Comparison",
    date="2026-04-06",
    attendees="Ralph, Lukas",
    transcript="""
Ralph (00:00): We need to pick a voice provider. ElevenLabs or Gemini Live?

Lukas (00:06): I haven't done the pricing comparison yet. Let me research it.

Ralph (00:10): Do that today please.
""",
    problems=["action_research"],
    summary="""## Voice Provider Comparison — Summary

The team needs to select a voice provider (ElevenLabs vs Gemini Live) for the voice bot feature.
No decision was made — a cost and quality comparison is needed first.

## Action Items

- 🟡 IMPORTANT **Lukas**: Research and compare ElevenLabs vs Gemini Live pricing and quality for voice bot use case.
""",
)

WITH_SUMMARY_ALL_TYPES = FakeTranscript(
    title="Platform Review — Pre-Baked",
    date="2026-04-07",
    attendees="Ralph, Lukas, Jacint, Sarah",
    transcript=ALL_ACTION_TYPES.transcript,
    problems=ALL_ACTION_TYPES.problems,
    summary="""## Platform Review — Summary

The team reviewed several platform concerns:
- The webhook handler is throwing 500s on GitHub push events, blocking CI notifications.
- A voice provider decision (ElevenLabs vs Gemini Live) is needed; Lukas is researching cost.
- The auth service needs Entra ID integration; Sarah needs to confirm the redirect URI with IT.
- Lukas suggested a meeting analytics dashboard as a future nice-to-have.

## Action Items

- 🔴 CRITICAL **Jacint**: Fix the webhook handler 500 error on GitHub push events (likely HMAC signature verification).
- 🟡 IMPORTANT **Lukas**: Research ElevenLabs vs Gemini Live pricing at our expected call volume.
- 🟡 IMPORTANT **Ralph**: Ask Marcus what the target call volume is for the voice bot.
- 🟡 IMPORTANT **Sarah**: Set up Entra ID integration for the MCP proxy (confirm redirect URI with IT first).
- 🟢 NICE-TO-HAVE **Lukas**: Design a dashboard for action item completion rates across meetings.
""",
)

# ---------------------------------------------------------------------------
# Master list — import this in tests
# ---------------------------------------------------------------------------

ALL_TRANSCRIPTS: list[FakeTranscript] = [
    EMPTY_TRANSCRIPT,
    SHORT_TRANSCRIPT,
    WHITESPACE_ONLY,
    STT_ERRORS_ONLY,
    PERSONAL_CONTENT_MIXED,
    ALL_ACTION_TYPES,
    NO_ACTION_ITEMS,
    AMBIGUOUS_ASSIGNEE,
    DUPLICATE_ITEMS,
    PRODUCTION_INCIDENT,
    HEAVY_STT_ERRORS,
    LONG_TRANSCRIPT,
    SINGLE_SPEAKER,
    CONFLICTING_DECISIONS,
    DEADLINE_PRESSURE,
    EXTERNAL_STAKEHOLDER,
    CROSS_TEAM_BLOCKER,
    MULTI_CRITICAL,
    LONG_TURNS,
    UNICODE_NAMES,
    WITH_SUMMARY_BUILD,
    WITH_SUMMARY_RESEARCH,
    WITH_SUMMARY_ALL_TYPES,
]


def by_problem(tag: str) -> list[FakeTranscript]:
    """Return all transcripts that exercise a given problem tag."""
    return [t for t in ALL_TRANSCRIPTS if tag in t.problems]


def with_summary() -> list[FakeTranscript]:
    """Return transcripts that have a pre-baked summary (no LLM call needed)."""
    return [t for t in ALL_TRANSCRIPTS if t.summary is not None]
