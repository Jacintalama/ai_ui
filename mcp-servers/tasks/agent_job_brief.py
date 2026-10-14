"""What a job step's agent is told, and what the lead is told at the end.

Pure: steps in, one user message out, so the wording is testable without a
model or a database.

A step sees the person's request, the whole plan with its own step marked,
and the results of the steps before it. Not the chat transcript: feeding
agents each other's replies taught the model to invent exchanges between
them (see test_agents_do_not_see_each_other), and a step needs the work so
far, not the talk around it.
"""

#: Each earlier result is cut to this. Six steps of a 20,000 character result
#: each would bury the step's own task under other agents' output, and the
#: free models have small windows.
RESULT_CAP_CHARS = 2000

_CUT_MARK = " (cut)"


def _name(names: dict[str, str], agent_id: str) -> str:
    return names.get(agent_id) or agent_id


def _cut(result: str) -> str:
    """The result, cut visibly so the agent knows it is not seeing all of it."""
    result = (result or "").strip()
    if len(result) > RESULT_CAP_CHARS:
        return result[:RESULT_CAP_CHARS] + _CUT_MARK
    return result


def _ordered(steps: list[dict]) -> list[dict]:
    return sorted(steps, key=lambda st: int(st.get("position") or 0))


def _results(steps: list[dict], names: dict[str, str]) -> list[str]:
    return ["Step %d, %s: %s" % (int(st["position"]),
                                 _name(names, st["agent_id"]),
                                 _cut(st.get("result") or "") or "(no result)")
            for st in steps]


def _message(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


def step_messages(request: str, steps: list[dict], position: int,
                  names: dict[str, str]) -> list[dict]:
    """The one user message a step's agent receives.

    The person's request, the whole plan with this step marked, and the
    results of the steps before it (each cut to RESULT_CAP_CHARS). Not the
    chat transcript: feeding agents each other's replies taught the model to
    invent exchanges (see test_agents_do_not_see_each_other).
    """
    ordered = _ordered(steps)
    lines = ["The person asked the team: %s" % (request or "").strip(), "",
             "The plan:"]
    for st in ordered:
        line = "%d. %s: %s" % (int(st["position"]),
                               _name(names, st["agent_id"]),
                               (st.get("task") or "").strip())
        if int(st["position"]) == position:
            line += " <- this is your step"
        elif st.get("status") == "done":
            line += " (done)"
        lines.append(line)
    # Only steps BEFORE this one: a later step's result, left over from a
    # retry, was written after the point the plan puts this step at.
    earlier = [st for st in ordered
               if int(st["position"]) < position and st.get("result")]
    if earlier:
        lines += ["", "Results so far:"] + _results(earlier, names)
    lines += ["", "Do your step now and answer with its result only."]
    return _message("\n".join(lines))


def final_messages(request: str, steps: list[dict],
                   names: dict[str, str]) -> list[dict]:
    """The lead's closing brief: the request and every step's result (cut)."""
    lines = ["The person asked the team: %s" % (request or "").strip(), "",
             "The results of the plan:"]
    lines += _results(_ordered(steps), names)
    lines += ["", "Write the person a short final answer from these results."]
    return _message("\n".join(lines))
