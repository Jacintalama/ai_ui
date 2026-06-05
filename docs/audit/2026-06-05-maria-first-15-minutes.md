# My First 15 Minutes With AIUI — by Maria, Flower Shop Owner

I run a small flower shop. My nephew said I should try "AIUI" because it can "build you a customer feedback form just by chatting with it on Slack." I already use Slack a little — my supplier and I message there. I am NOT a computer person. I can send an email and post on Facebook. That's about my level. Here is exactly what happened.

---

## Minute 0–2: "Okay, where is it?"

My nephew added the AIUI bot to my Slack. I open Slack and look for it. There's a little robot in the sidebar. I click it. It opens a direct message window — empty, blinking cursor.

**What I see:** Nothing. A blank message box. No "Hi Maria! Here's how to start." No buttons. No instructions. Just the empty chat.

**What I think:** *"Okay, I talk to it like a person, right? That's what 'chat' means."*

So I type the most natural thing in the world:

> can you build me a customer feedback form?

I hit enter. I wait.

The bot replies with a friendly little paragraph — `:robot_face: *AI Analysis*` and then some chatty answer *about* feedback forms. It talks at me. It does NOT build anything. It does NOT say "click here to start." It's just... a chatbot making conversation.

**What I think:** *"Wait, did it understand me? It's talking about feedback forms but it didn't DO anything. Is it broken? Did I do it wrong?"*

I had no idea I was supposed to type a magic command like `/aiui`. Nothing told me. The thing is literally pitched as "chat with a bot to build apps," so I chatted, and it just... chatted back. **This is the first moment I almost closed the window.** I genuinely thought the bot was a dud.

> *(Reality from the audit: the bot has no listener for normal messages. My plain sentence was answered by a generic AI with "no welcome/first-run message, no mention of /aiui or the App Builder panel." A first-timer "never discovers the product's purpose.")*

---

## Minute 2–4: The slash command rabbit hole

I text my nephew. He says "type slash aiui help." Fine.

I type `/aiui help`.

**What I see:** A WALL of text. Eighteen-ish commands. I'm reading things like:

- `pr-review`
- `mcp <server> <tool> [json_args]`
- `diagnose [container]`
- `analyze owner/repo`
- `deps`
- `license`
- `security` (OWASP Top 10)
- `web-search`
- `aiuibuilder <build|templates|list|status|open>`
- `cronjob`

**What I think:** *"What in the world. 'OWASP Top 10'? 'json_args'? 'owner/repo'? This is for programmers. I'm a florist. I'm in the wrong place."*

My eyes glaze over. Somewhere buried in that wall is the thing I actually want, but it's drowning in engineer words. And the one that sounds like building — `aiuibuilder` — reads like a typo. **"aiuibuilder"?** Who named this? It looks broken before I even click it.

**This is the second moment I almost quit.** A normal person sees that help screen and concludes "this is a developer tool, not for me."

---

## Minute 4–6: Trying to build, getting a lecture

I take a guess. I figure I'll just tell it what I want in the command:

> /aiui build me a feedback form

I wait, hopeful.

It... gives me another little essay *about* building forms. It does NOT start building.

**What I think:** *"Again?! I literally said BUILD. Why is it just TALKING about it?"*

Turns out (I learned later) "build" isn't a real command — the real one is the typo-looking `aiuibuilder` — so my words got shoved into the chatbot again and it lectured me instead of doing anything. To me it just felt like the bot was being deliberately unhelpful. I asked it to build something twice now and got two paragraphs of nothing.

I text my nephew again, slightly annoyed now. He sends a screenshot: there's apparently a **pinned message** in some channel with buttons. I didn't even know to look at pinned messages. Why would I?

---

## Minute 6–8: Finally, a button I understand

I find the pinned panel. NOW we're talking — actual buttons:

> **AIUI App Builder** — Tap *Build an app* to start something new, or *My apps* to manage what you've already made. Everything happens in a private DM with you.
>
> [ 🚀 **Build an app** ] [ 📂 **My apps** ]

**What I think:** *"Oh thank God. A button. THIS I can do."*

I click **🚀 Build an app**.

A tiny grey note flickers in the channel: **"Sent to your DM."** That's it. Easy to miss completely.

**What I think:** *"...Sent to my DM? What does that mean? Did something happen? Where did it go?"*

I sit there looking at the channel, waiting for something to appear right where I clicked. Nothing more happens here. The actual template picker went off to a private message somewhere and I didn't notice the tiny note pointing me there. For a good 30 seconds I think the button did nothing.

> *(Reality: "A first-timer may not notice the small ephemeral note, won't think to check the bot's DM, and concludes the button did nothing.")*

I eventually find the DM. There's a dropdown: **"Pick a template to start…"** with options like "A one-page site to promote a product or service" and an online store one, plus a **Blank** button.

**What I think:** *"None of these say 'feedback form.' Is a form even one of these? Do I pick the closest one? Do I pick Blank? What's Blank?"*

I hesitate. I don't want to pick the wrong one and ruin it. But there's no "feedback form" option, so I nervously pick the landing-page one and hope I can describe what I really want.

A pop-up form appears: **"Build: A one-page site…"** with one box: **"Describe your app,"** placeholder *"e.g. a portfolio site for Maya, a UX designer."*

I type carefully:

> A simple feedback form for my flower shop customers — name, email, a star rating, and a comments box.

I click **Build**.

---

## Minute 8–10: The brick wall

The pop-up closes. And then I get hit with this:

> **Your Discord account isn't linked. Ask Lukas to add you.**

I stare at it.

**What I think, in order:**
1. *"Discord? I'm on SLACK. What is Discord?"*
2. *"Who is Lukas??"*
3. *"I just spent five minutes describing my form and NOW you tell me I'm not allowed?"*

I have never been so confused and insulted by software. It says "Discord" — I'm not on Discord. It tells me to "Ask Lukas" — I don't know any Lukas. There's no Lukas in my shop. There's no button to fix it. It's a wall with a stranger's name carved into it.

> *(Reality: this is a Discord-flavored error leaking onto Slack — "_format_build_error and run_panel_publish/enhance/unpublish/delete hard-code Discord wording," and "'Ask Lukas' is meaningless to anyone who doesn't know Lukas." And critically: the Build button "does NOT require a linked account" up front, so I was allowed all the way to the finish line before being bounced. Classic sunk-cost cliff.)*

**This is the third and biggest moment I almost quit — and honestly, the moment most people like me WOULD quit for good.** All that effort, then a brick wall referencing a product I'm not using and a person I've never met.

---

## Minute 10–12: The "scope" sentence that broke my brain

I don't give up *yet*, only because my nephew set this up and I don't want to disappoint him. I poke around. On a *different* attempt (My apps), I get a *different* error — and this one's even worse:

> **I couldn't read your email from Slack. Ask an admin to grant the bot the users:read.email scope, then try again.**

**What I think:** *"...what is a 'scope'? What is 'users colon read dot email'? Who is 'an admin'? Is that me? Is that my nephew? Is that Lukas??"*

This sentence wasn't written for me. It was written for a programmer. There's no link, no button, nothing I can press. It's a locked door with the instructions written in a language I don't read.

And here's the part that really got me: one error told me to **"Ask Lukas to add you,"** and this one told me to **"ask an admin to grant a scope."** So which is it? Find a guy named Lukas? Find an "admin"? Grant a "scope" myself? I have *three different contradictory instructions* and not one of them is something I can actually do.

> *(Reality: two contradictory "not linked" messages exist, and the Slack one "is pure technical jargon aimed at an admin, not the end user… There is no button or link to act on — it's a dead end worded for an engineer.")*

---

## Minute 12–14: My nephew "links" me, and I try a schedule instead

My nephew does something on his end (apparently HE'S the admin, or knows who is). He says "you're linked now, try again."

I think — okay, forget the form for a second, let me try the other thing it advertised: *scheduling*. I saw a panel: **"📅 Scheduled tasks — Set up tasks that run on a schedule."** I open **New schedule**. Two boxes:

- **What should it do?** — *"e.g. summarize my unread emails and list the top 3"*
- **When?** — hint: *"A cron expression or plain English both work."* placeholder: *"0 9 * * *  /  every morning  /  every Monday 9am"*

**What I think:** *"'A CRON expression'? '0 9 star star star'?? I thought this was supposed to be NO coding. That looks exactly like the scary computer stuff I was promised I wouldn't have to do."*

The placeholder literally leads with `0 9 * * *`. My stomach drops. But it also says "plain English," so I copy the friendly-looking example it gave me — **"every Monday 9am"** — figuring if it's their own example, it must work.

I get:

> **Couldn't understand that schedule time — try e.g. "every morning at 8am".**

**What I think:** *"I typed YOUR example. The one you showed me. And you're telling me you can't understand it??"*

I am now furious in the quiet way you get furious at a machine. It suggested "every Monday 9am" as a sample and then rejected "every Monday 9am" (turns out it secretly needs the word "at" — "every Monday **at** 9am" — but nobody tells you that). The error gives me one new example and no clue which word it didn't like. I'm just guessing magic phrases at this point.

> *(Reality: "'every Monday 9am' WITHOUT the word 'at' fails… the modal placeholder promises 'plain English' and shows 'every Monday 9am' as an example, but that exact example does not parse." And the failure "never says WHICH field was wrong… or why.")*

**This is the fourth moment I almost quit.** Being rejected for typing the software's own suggestion is the kind of thing that makes you feel stupid AND angry at the same time — and that's the feeling that makes people leave and never come back.

---

## Minute 14–15: I finally get a build going... into silence

I add "at" — "every Monday at 9am" — and it works. Small victory. But I'm tired now. Let me just get my feedback form built (I'm linked now). I redo the whole template → describe → Build dance. This time it takes:

> **Building `landing-3a1f` … I'll post the link here when it's ready (usually a few minutes).**

**What I think, first:** *"What is `landing-3a1f`? I called it a feedback form for my flower shop. That's not what I named it. Is that even MY thing? Why is it in that weird code font with dashes and numbers?"*

I don't recognize my own app. Every message from here on calls it `landing-3a1f` in that little code-box font, and I keep wondering if it built the wrong thing.

**Then I wait. And wait.** "Usually a few minutes," it said. The chat goes completely silent. No spinning wheel. No "still working." No progress bar. No "50% done." Nothing.

**What I think at 3 minutes:** *"Is it still going?"*
**At 5 minutes:** *"Did it freeze? Did it crash? Should I click Build again?"*

I genuinely don't know if it's working or dead. I almost click the button a second time (which, I later learned, would've told me "a build is already running — try again in a few minutes," because apparently only ONE person on the whole system can build at a time — so if some other customer somewhere was also building, I'd just get refused with no explanation).

> *(Reality: "No progress feedback for the entire build duration — one 'usually a few minutes' message, then silence." The backend can secretly run build → verify → retry up to 3 times and "can realistically run far longer." Plus the platform-wide single-build lock. "Most users will assume it crashed and either give up or spam the button.")*

At minute 15, I'm staring at a silent chat that says it's building something called `landing-3a1f`, with no idea if it's alive, and I've already hit four walls to get here. I put my phone down to go help an actual customer who walked into my actual shop. Whether AIUI ever finishes building my form, I may never come back to find out.

---

# The 5 Moments Maria Almost Quit

> Ranked by how many real first-timers would drop off — highest impact first.

### 1. 🧱 The "Ask Lukas" / "Discord account isn't linked" brick wall — AFTER investing effort *(Minute 8–10)*
The single worst moment. I was let all the way through template-pick → describe-my-app → Build, and only THEN told I was never allowed — with a message that says **"Discord"** (I'm on Slack) and **"Ask Lukas"** (a stranger). No self-service fix, no link, no button. Sunk-cost effort + a wall + a personal in-joke I'm not in on. **Most people quit here permanently.**

### 2. 🤐 No onboarding + a chatbot that ignores plain typing *(Minute 0–2)*
The very first thing I did — type "can you build me a feedback form?" like a normal human — got answered by a chatty AI that *did nothing*. No welcome, no "type /aiui," no hint the buttons exist. A huge share of users conclude the bot is broken or offline in the first 60 seconds and never even reach a button.

### 3. 🔤 "users:read.email scope" (and the contradictory linking instructions) *(Minute 10–12)*
A locked door with the instructions written in programmer. "Scope," "admin," "users:read.email" — none of it is something a florist can act on, and it directly contradicts the *other* error ("Ask Lukas"). Three different "fix it" stories, zero of them clickable.

### 4. 😤 Rejected for typing the app's OWN example ("every Monday 9am") *(Minute 12–14)*
The placeholder suggests "every Monday 9am," I type exactly that, and it says it can't understand it (it secretly needs "at"). Being made to feel stupid for following the instructions — with an error that won't tell you which word was wrong — is uniquely rage-inducing and drives people out.

### 5. 🕳️ Build goes into total silence — "usually a few minutes," then nothing *(Minute 14–15)*
After all that, the one success drops me into a void: no progress, no spinner, no heartbeat, for minutes that can stretch much longer behind the scenes. Plus my app is renamed to a code string (`landing-3a1f`) I don't recognize. I can't tell if it's working or dead, I'm tempted to re-click (and hit the hidden single-build lock), and there's nothing keeping me here while I wait. Many simply walk away and never see the result.

---

**Bottom line, from me, a 52-year-old who just wanted a feedback form:** I was promised "just chat with it, no coding." In 15 minutes I was ignored when I chatted, lectured when I asked it to build, handed a wall of programmer commands, blocked by a guy named Lukas, asked to grant a "scope," rejected for using the software's own example, and finally left staring at a silent screen building something called `landing-3a1f`. I never got my form. The only reason I made it this far is that my nephew was on the other end of a text. Without him, I'd have quit at minute two.