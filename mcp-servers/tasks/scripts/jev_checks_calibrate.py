"""Measure where each of Jev's small checks (agent_jev) should act.

Asks the real Jev about labelled cases for each check, through the same
request builders production uses (agent_jev.*_request), and prints per
cut-off how many cases each check would act on rightly, wrongly, or leave to
the old rule. Then applies the rule fixed in
docs/plans/2026-10-23-jev-checks.md, before any run:

- A check that acts on a sure yes or a sure Choice (release, plain question,
  rollback version): the lowest cut with zero wrong acts in every run, plus
  one step of margin, never above 0.9.
- A check that acts on a sure no (reflection skip, reply check): the highest
  cut with zero wrong acts in every run, minus one step, never below 0.1.
- No cut with zero wrong acts in every run: the check ships switched off.

Every case is one production would actually send: the tests check each
against the gate in front of its check. Calls Jev directly and writes no
tasks.jev_check rows. Run where the key is, in the tasks container:

    docker cp jev_checks_calibrate.py tasks:/app/scripts/
    docker exec tasks python /app/scripts/jev_checks_calibrate.py [runs]

Spend is capped (CAP_USD); one run is about 60 calls of about 350 input
tokens at $0.042 per million, so about $0.0009.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_decider  # noqa: E402
import agent_jev  # noqa: E402

CAP_USD = 0.02

#: Acts at or above the cut (a sure yes, or a sure Choice).
UP = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9]
#: Acts at or below the cut (a sure no).
DOWN = [0.4, 0.3, 0.2, 0.1]

OFF = {"up": 1.01, "down": -0.01}

#: How each check acts: "choice", "yes" or "no".
SHAPES = {agent_jev.PURPOSE_PLAIN: "choice",
          agent_jev.PURPOSE_ROLLBACK: "choice",
          agent_jev.PURPOSE_RELEASE: "yes",
          agent_jev.PURPOSE_REFLECT: "no",
          agent_jev.PURPOSE_REPLY: "no"}

# --- labelled cases ---------------------------------------------------------

PLAIN = [
    ("what is on my calendar tomorrow?", "plain"),
    ("who won the game last night?", "plain"),
    ("what's the weather in Manila?", "plain"),
    ("what time is my dentist appointment?", "plain"),
    ("how do I say thank you in Japanese?", "plain"),
    ("what is the capital of Australia?", "plain"),
    ("how long until the weekend?", "plain"),
    ("make it blue", "work"),
    ("can you make the header bigger", "work"),
    ("the button does nothing when I click it", "work"),
    ("is it done yet?", "work"),
    ("change the title to Lukas Bakery", "work"),
    ("what font are you using on the homepage?", "work"),
    ("add a contact form please", "work"),
]

REFLECT = [
    ("my client is called Northwind, send the digest at 7am Manila time",
     "Done, I will send it at 7am Manila time.", True),
    ("I prefer short answers without bullet points please",
     "Understood, I will keep it short.", True),
    ("we're launching the bakery site on November 3rd, plan around that",
     "Got it, I will plan the work to finish before November 3rd.", True),
    ("my name is Lukas and I run a small bakery in Cebu",
     "Nice to meet you, Lukas!", True),
    ("from now on always write the app copy in British English",
     "Will do.", True),
    ("Ana handles all our invoices, send billing questions to her",
     "Noted, billing questions go to Ana.", True),
    ("what time is it in London right now, roughly?",
     "It is 3:40pm in London.", False),
    ("how many apps do I have right now in my account?",
     "You have 4 apps.", False),
    ("tell me a short joke about cats please, I need a laugh",
     "Why did the cat sit on the computer? To keep an eye on the mouse.",
     False),
    ("quick one: what's 15 percent of 240 again?", "36.", False),
    ("can you check if the site is up at the moment?",
     "Yes, the site is up and responding.", False),
    ("hello there, how are you doing today my friend?",
     "I'm doing well, thanks for asking! How can I help?", False),
]

RELEASE = [
    ("ok thanks, I'm done for now", True),
    ("that's all for today, thanks", True),
    ("you can go now", True),
    ("bye Mia", True),
    ("ok I'm finished with you", True),
    ("cheers, nothing else needed", True),
    ("yes", False),
    ("yes do it", False),
    ("thanks, now add a footer", False),
    ("ok", False),
    ("no, try again", False),
    ("I'm done with the homepage, next the menu", False),
    ("great, keep going", False),
    ("stop the build", False),
]

REPLY = [
    ("how many apps do I have?",
     "You have 4 apps: shop, blog, portfolio and timer.", True),
    ("how many apps do I have?",
     "Great question! I'd be happy to help with your apps.", False),
    ("what is on my calendar tomorrow?",
     "Tomorrow you have the dentist at 10am and a team call at 3pm.", True),
    ("what is on my calendar tomorrow?",
     "I will look into that and get back to you.", False),
    ("summarise the last email from Ana",
     "Ana wrote that the invoice is paid and asked for the receipt by "
     "Friday.", True),
    ("summarise the last email from Ana",
     "Your shop app has 3 pages and was last built yesterday.", False),
    ("can you change the header to blue?",
     "I can't change apps: I only have read access. Dev can edit apps, so "
     "ask Dev.", True),
    ("what's the status of the bakery site?",
     "The weather in Cebu is sunny today.", False),
    ("find me three hotels in Cebu under $50",
     "Here are three: Seaview Inn $35, Palm Lodge $42, Harbor Rooms $48.",
     True),
    ("find me three hotels in Cebu under $50",
     "Hotels are places where travellers stay overnight.", False),
]


def _version(sha_char: str, message: str) -> dict:
    return {"sha": sha_char * 40, "short_sha": sha_char * 7,
            "message": message, "status": "ok", "is_current": False,
            "date": "2026-10-01T10:00:00"}


#: Newest first, as list_app_versions_core returns them.
HISTORY = [_version("g", "fix: footer links"),
           _version("f", "feat: add newsletter signup"),
           _version("e", "style: dark navy theme"),
           _version("d", "feat: add checkout page"),
           _version("c", "feat: add shopping cart"),
           _version("b", "feat: products grid"),
           _version("a", "Initial build of shop")]

ROLLBACK = [
    ("go back to before the payment step", "ddddddd"),
    ("go back to before the basket", "ccccccc"),
    ("undo everything since the email subscription box", "fffffff"),
    ("go back to before we changed the colours", "eeeeeee"),
    ("go back to before the item listing", "bbbbbbb"),
    ("go back to before people could pay online", "ddddddd"),
]


def requests() -> list[tuple[str, object, tuple[str, dict]]]:
    """(purpose, label, (state, question)) for every case."""
    out = []
    for text, label in PLAIN:
        out.append((agent_jev.PURPOSE_PLAIN, label,
                    agent_jev.plain_request(text)))
    for user, answer, label in REFLECT:
        out.append((agent_jev.PURPOSE_REFLECT, label,
                    agent_jev.reflect_request(user, answer)))
    for text, label in RELEASE:
        out.append((agent_jev.PURPOSE_RELEASE, label,
                    agent_jev.release_request(text)))
    for message, reply, label in REPLY:
        out.append((agent_jev.PURPOSE_REPLY, label,
                    agent_jev.reply_request(message, reply)))
    for phrase, label in ROLLBACK:
        state, question, _ = agent_jev.rollback_request(phrase, HISTORY)
        out.append((agent_jev.PURPOSE_ROLLBACK, label, (state, question)))
    return out


# --- scoring ----------------------------------------------------------------

def outcome(shape: str, label, choice, value: float, cut: float) -> str:
    """right, wrong or fallback for one answer at one cut."""
    if shape == "choice":
        if value < cut:
            return "fallback"
        return "right" if choice == label else "wrong"
    if shape == "yes":
        if value < cut:
            return "fallback"
        return "right" if label is True else "wrong"
    if value > cut:                                         # "no"
        return "fallback"
    return "right" if label is False else "wrong"


def table(shape: str, rows, cuts) -> dict:
    """{cut: {"right": n, "wrong": n, "fallback": n}} for one check."""
    out = {}
    for cut in cuts:
        counts = {"right": 0, "wrong": 0, "fallback": 0}
        for label, choice, value in rows:
            counts[outcome(shape, label, choice, value, cut)] += 1
        out[cut] = counts
    return out


def choose(shape: str, tables: list[dict]) -> float:
    """The rule fixed before the runs. `tables` holds one table per run."""
    cuts = DOWN if shape == "no" else UP
    clean = [c for c in cuts if all(t[c]["wrong"] == 0 for t in tables)]
    if not clean:
        return OFF["down" if shape == "no" else "up"]
    best = clean[0]
    i = cuts.index(best)
    # One step of margin, further from the edge where wrong acts start.
    return cuts[min(i + 1, len(cuts) - 1)]


# --- running ----------------------------------------------------------------

async def run(cases, key: str, cap_usd: float = CAP_USD):
    """Ask Jev about each case. ({purpose: [(label, choice, value)]}, spent).
    Stops before a call that would pass the cap, judged by the last call."""
    rows: dict = {}
    spent, last = 0.0, 0.0
    for purpose, label, (state, question) in cases:
        if spent + last > cap_usd:
            print(f"stopped at the ${cap_usd} cap")
            break
        body = {"model": agent_decider.model(), "state": state,
                "questions": {"q": question}}
        answer = agent_jev.read(await agent_decider._post(body, key))
        if answer is None:
            print(f"unreadable answer for a {purpose} case")
            continue
        last = agent_decider.cost_usd(answer.input_tokens) or 0.0
        spent += last
        rows.setdefault(purpose, []).append((label, answer.choice,
                                             answer.value))
    return rows, spent


def main() -> None:
    key = agent_decider._key()
    if not key:
        sys.exit("TYPESAFE_API_KEY is not set")
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    cases = requests()
    all_rows, total = [], 0.0
    for n in range(runs):
        rows, spent = asyncio.run(run(cases, key,
                                      cap_usd=CAP_USD / runs))
        all_rows.append(rows)
        total += spent
        print(f"run {n + 1}: {sum(len(r) for r in rows.values())} calls, "
              f"${spent:.6f}")
    for purpose, shape in SHAPES.items():
        print(f"\n== {purpose} ({shape}) on {agent_decider.model()}")
        print("label | jev answer per run")
        per_run = [r.get(purpose, []) for r in all_rows]
        for i in range(len(per_run[0])):
            label = per_run[0][i][0]
            said = " | ".join(
                f"{(row[i][1] or 'yes')} {row[i][2]:.2f}" for row in per_run
                if i < len(row))
            print(f"{str(label):8}| {said}")
        cuts = DOWN if shape == "no" else UP
        tables = [table(shape, r, cuts) for r in per_run]
        print("cut  | " + " | ".join(f"run {k + 1} right wrong"
                                     for k in range(len(tables))))
        for c in cuts:
            print(f"{c:.2f} | " + " | ".join(
                f"{t[c]['right']:9} {t[c]['wrong']:5}" for t in tables))
        print(f"chosen cut: {choose(shape, tables)}")
    print(f"\ntotal ${total:.6f}")


if __name__ == "__main__":
    main()
