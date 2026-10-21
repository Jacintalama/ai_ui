"""Measure where JEV_MIN_CONFIDENCE should sit, from real Jev answers.

Asks Jev (agent_decider) about a fixed set of team messages, each labelled
with what should happen: one answer and which agents may give it, or a job
for several. Prints, per cut-off, how many messages would go to one agent
(right), how many would go to one agent wrongly (wrong), and how many would
take today's path (fallback: the lead's triage).

Only PATH_ONE_AGENT changes the round; a plan and a fallback both run the
triage. So a wrong pick is the cost and a right pick is the gain.

The two rosters are the real ones on production on 2026-10-21: names and
roles only. Calls Jev directly, so it writes no tasks.agent_decision rows.
Run where the key is, in the tasks container:

    docker cp jev_calibrate.py tasks:/app/scripts/
    docker exec tasks python /app/scripts/jev_calibrate.py [current|alone|count]

Spend is capped (CAP_USD); one full run is about 26 calls of about 500
input tokens at $0.042 per million, so about $0.0006.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_decider  # noqa: E402

CAP_USD = 0.01
CUTS = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]


def _team(*pairs):
    return [{"id": f"agent-{name.lower()}", "name": name, "meta": {"role": role}}
            for name, role in pairs]


ROSTERS = {
    "small": _team(("Mia", "Receptionist"), ("Ada", "Project manager"),
                   ("Dev", "Developer")),
    "big": _team(("Mia", "Receptionist"), ("Kai", "App reviewer"),
                 ("Iris", "Drive librarian"), ("Nora", "Calendar keeper"),
                 ("Rex", "Programmer"), ("Ada", "Project manager"),
                 ("Vera", "Researcher")),
}


def _a(roster, message, *who):
    return {"roster": roster, "message": message, "kind": "answer",
            "who": set(who)}


def _j(roster, message):
    return {"roster": roster, "message": message, "kind": "job", "who": set()}


CASES = [
    _a("small", "the login button on my app does nothing when I click it",
       "Dev"),
    _a("small", "can you fix the typo in the footer of my site", "Dev"),
    _a("small", "why is my page loading so slowly on mobile", "Dev"),
    _a("small", "add a dark mode toggle to the settings page", "Dev"),
    _a("small", "what is the status of the website project this week", "Ada"),
    _a("small", "what deadlines do we have coming up on the project", "Ada"),
    _a("small", "a client called asking about our opening hours, what should "
       "I tell them", "Mia"),
    _a("small", "please welcome the new visitor and ask what they need",
       "Mia"),
    _a("small", "how is everyone doing today", "Mia", "Ada", "Dev"),
    _j("small", "plan the launch: write the timeline, build the signup page, "
       "and prepare a welcome message for new visitors"),
    _j("small", "build a contact form, then draft a friendly reply for "
       "incoming messages, and track it all on the project plan"),
    _j("small", "fix the broken checkout, update the project timeline to "
       "match, and let the client know when it is done"),
    _a("big", "review my latest app and tell me what breaks", "Kai"),
    _a("big", "find the budget spreadsheet in my drive", "Iris"),
    _a("big", "find the contract PDF from last month in my files", "Iris"),
    _a("big", "what meetings do I have tomorrow", "Nora"),
    _a("big", "book a meeting with the design team for Friday afternoon",
       "Nora"),
    _a("big", "the checkout page throws an error when I submit the form",
       "Rex", "Kai"),
    _a("big", "research the top three competitors in online bookkeeping",
       "Vera"),
    _a("big", "look up current pricing for cloud hosting providers", "Vera"),
    _a("big", "what is the status of the Q4 project plan", "Ada"),
    _a("big", "someone emailed asking for a refund, how should we reply",
       "Mia"),
    _j("big", "research competitor pricing, build a pricing page for the app, "
       "and schedule a review meeting with me on Monday"),
    _j("big", "find last quarter's report in drive, summarise the key numbers, "
       "and put a meeting on my calendar to discuss them"),
    _j("big", "write the code for a new invoice feature and then have it "
       "reviewed before release"),
    _j("big", "research three tools for team chat, compare them, and book a "
       "call with the winner's sales team next week"),
]


#: Ways to ask the answer-or-job question. Keys stay "answer" and "job",
#: the two choices agent_decider.read_answer reads. "current" is what the
#: decider sends today. The others exist because the current wording scored
#: clear one-agent messages ("the login button does nothing") 0.04 to 0.30:
#: fixing a bug is not "one reply", though it is one person's work.
WORDINGS = {
    "current": {"instructions": agent_decider.KIND_INSTRUCTIONS,
                "criteria": dict(agent_decider.KIND_CRITERIA)},
    "alone": {
        "instructions": ("Does the new message need only one team member, or "
                         "work from several team members with different "
                         "roles?"),
        "criteria": {
            "answer": "one team member can handle all of it alone, even if "
                      "it takes some work",
            "job": "it clearly needs two or more team members with "
                   "different roles",
        },
    },
    "count": {
        "instructions": "How many team members does the new message need?",
        "criteria": {"answer": "one team member",
                     "job": "two or more team members"},
    },
}


def outcome(case, kind, kc, who, wc, cut) -> str:
    """What the round would do with this answer at this cut-off."""
    if kind == "answer" and kc >= cut and wc >= cut:
        right = case["kind"] == "answer" and who in case["who"]
        return "right" if right else "wrong"
    return "fallback"


def table(rows, cuts) -> dict:
    """{cut: {"right": n, "wrong": n, "fallback": n}}."""
    out = {}
    for cut in cuts:
        counts = {"right": 0, "wrong": 0, "fallback": 0}
        for case, kind, kc, who, wc in rows:
            counts[outcome(case, kind, kc, who, wc, cut)] += 1
        out[cut] = counts
    return out


async def run(cases, key: str, cap_usd: float = CAP_USD, wording=None):
    """Ask Jev about each case. ([(case, kind, kc, who, wc)], dollars spent).
    Stops before a call that would pass the cap, judged by the last call.
    `wording` (one of WORDINGS) replaces the answer-or-job question for this
    run only; the decider's own wording is put back afterwards."""
    saved = agent_decider.KIND_INSTRUCTIONS, agent_decider.KIND_CRITERIA
    if wording is not None:
        agent_decider.KIND_INSTRUCTIONS = wording["instructions"]
        agent_decider.KIND_CRITERIA = dict(wording["criteria"])
    rows, spent, last = [], 0.0, 0.0
    try:
        for case in cases:
            if spent + last > cap_usd:
                print(f"stopped at the ${cap_usd} cap after {len(rows)} calls")
                break
            body = agent_decider.build_request(case["message"], [],
                                               ROSTERS[case["roster"]])
            data = await agent_decider._post(body, key)
            last = agent_decider.cost_usd(
                (data.get("usage") or {}).get("input_tokens")) or 0.0
            spent += last
            a = data["answers"]
            rows.append((case, a["kind"]["choice"],
                         float(a["kind"]["confidence"]),
                         a["who"]["choice"], float(a["who"]["confidence"])))
    finally:
        agent_decider.KIND_INSTRUCTIONS, agent_decider.KIND_CRITERIA = saved
    return rows, spent


def main() -> None:
    key = agent_decider._key()
    if not key:
        sys.exit("TYPESAFE_API_KEY is not set")
    name = sys.argv[1] if len(sys.argv) > 1 else "current"
    if name not in WORDINGS:
        sys.exit(f"unknown wording {name!r}; one of {', '.join(WORDINGS)}")
    print(f"wording: {name}")
    rows, spent = asyncio.run(run(CASES, key, wording=WORDINGS[name]))
    print("expected | jev kind conf | jev who conf | message")
    for case, kind, kc, who, wc in rows:
        want = "job" if case["kind"] == "job" else "/".join(sorted(case["who"]))
        print(f"{want:9}| {kind:6} {kc:.2f} | {who:5} {wc:.2f} | "
              f"{case['message'][:60]}")
    print()
    print("cut  | right wrong fallback")
    for cut, n in table(rows, CUTS).items():
        print(f"{cut:.2f} | {n['right']:5} {n['wrong']:5} {n['fallback']:8}")
    print(f"\n{len(rows)} calls, ${spent:.6f}")


if __name__ == "__main__":
    main()
