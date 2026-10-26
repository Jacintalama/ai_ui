"""A plain page of what the agents decided and did, for troubleshooting.

The owner asked (call, 2026-10-16) for a view that shows the agents talking
to each other and is plainer than the office. Five tables, newest first,
for the signed-in person only: Jev's decisions about team messages, Jev's
smaller checks (agent_jev), agent runs with model, time and cost, one agent
asking another, and team jobs.
No script and no motion: it is read, not watched.

Each table is read on its own; one that fails says so and the rest still
draw. Every value is escaped, because agent names and reasons are text that
people and models wrote.
"""
import html
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import text as sql_text

import agent_decider
from auth import CurrentUser, current_user
from db import session
from routes_agent_jobs import _names

log = logging.getLogger(__name__)

router = APIRouter()

LIMIT = 50

_RUNS = ("SELECT started_at, agent_id, source, model, status, "
         "EXTRACT(EPOCH FROM (finished_at - started_at)) AS secs, cost_usd "
         "FROM tasks.agent_run WHERE lower(user_email) = lower(:email) "
         "ORDER BY started_at DESC LIMIT :limit")
_ASKS = ("SELECT started_at, agent_id, target_agent_id, status "
         "FROM tasks.agent_step WHERE lower(user_email) = lower(:email) "
         "AND target_agent_id IS NOT NULL "
         "ORDER BY started_at DESC LIMIT :limit")
_CHECKS = ("SELECT created_at, purpose, model, choice, value, outcome, "
           "reason, ms, cost_usd FROM tasks.jev_check "
           "WHERE lower(user_email) = lower(:email) "
           "ORDER BY created_at DESC, id DESC LIMIT :limit")
_JOBS = ("SELECT j.created_at, j.status, j.lead_agent_id, "
         "COUNT(st.id) AS total, "
         "COUNT(st.id) FILTER (WHERE st.status = 'done') AS done "
         "FROM tasks.agent_job j "
         "LEFT JOIN tasks.agent_job_step st ON st.job_id = j.id "
         "WHERE lower(j.user_email) = lower(:email) GROUP BY j.id "
         "ORDER BY j.created_at DESC LIMIT :limit")


async def _rows(query: str, email: str) -> list[dict]:
    async with session() as s:
        rows = await s.execute(sql_text(query),
                               {"email": email, "limit": LIMIT})
        return [dict(r._mapping) for r in rows]


async def _read(email: str) -> dict:
    """The five tables for one person. A table that could not be read is
    None, so the page can say so instead of showing it empty."""
    out = {}
    reads = {"decisions": lambda: agent_decider.recent(email, LIMIT),
             "checks": lambda: _rows(_CHECKS, email),
             "runs": lambda: _rows(_RUNS, email),
             "asks": lambda: _rows(_ASKS, email),
             "jobs": lambda: _rows(_JOBS, email)}
    for name, read in reads.items():
        try:
            out[name] = await read()
        except Exception:                                   # noqa: BLE001
            log.warning("agent debug: could not read %s", name, exc_info=True)
            out[name] = None
    return out


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _when(value) -> str:
    try:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    except AttributeError:
        return _e(value)


def _money(value) -> str:
    if value is None:
        return ""
    try:
        return "$%.6f" % float(value)
    except (TypeError, ValueError):
        return _e(value)


def _conf(label, value) -> str:
    if label is None:
        return ""
    if value is None:
        return _e(label)
    try:
        return "%s %.2f" % (_e(label), float(value))
    except (TypeError, ValueError):
        return _e(label)


def _name(names: dict, agent_id) -> str:
    if not agent_id:
        return ""
    return names.get(str(agent_id)) or str(agent_id)


def _table(title: str, head: list[str], rows: list[list[str]] | None) -> str:
    out = [f"<h2>{_e(title)}</h2>"]
    if rows is None:
        out.append("<p>Could not read this table. Reload to try again.</p>")
        return "\n".join(out)
    if not rows:
        out.append("<p>None yet.</p>")
        return "\n".join(out)
    out.append("<table><thead><tr>"
               + "".join(f"<th>{_e(h)}</th>" for h in head)
               + "</tr></thead><tbody>")
    for cells in rows:
        # Cells arrive escaped: each was built from _e or a formatter above.
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def render_page(data: dict, names: dict) -> str:
    decisions = data.get("decisions")
    checks = data.get("checks")
    runs = data.get("runs")
    asks = data.get("asks")
    jobs = data.get("jobs")

    def rows(items, build):
        return None if items is None else [build(r) for r in items]

    d_rows = rows(decisions, lambda r: [
        _when(r.get("created_at")), _e(r.get("path")),
        _conf(r.get("kind"), r.get("kind_confidence")),
        _conf(_name(names, r.get("agent_id")) or None,
              r.get("agent_confidence")),
        "%s ms" % _e(r.get("ms")) if r.get("ms") is not None else "",
        _conf(r.get("urgency"), r.get("urgency_confidence")),
        _e(r.get("reason")), _e(r.get("model")), _money(r.get("cost_usd"))])
    c_rows = rows(checks, lambda r: [
        _when(r.get("created_at")), _e(r.get("purpose")),
        # A Choice shows its pick and confidence, a yes or no question its
        # probability of yes.
        _conf(r.get("choice"), r.get("value")) if r.get("choice")
        else _conf("yes", r.get("value")) if r.get("value") is not None
        else "",
        _e(r.get("outcome")),
        "%s ms" % _e(r.get("ms")) if r.get("ms") is not None else "",
        _e(r.get("reason")), _e(r.get("model")), _money(r.get("cost_usd"))])
    r_rows = rows(runs, lambda r: [
        _when(r.get("started_at")), _e(_name(names, r.get("agent_id"))),
        _e(r.get("source")), _e(r.get("model")), _e(r.get("status")),
        ("%.1f s" % float(r["secs"])) if r.get("secs") is not None else "",
        _money(r.get("cost_usd"))])
    a_rows = rows(asks, lambda r: [
        _when(r.get("started_at")),
        "%s asked %s" % (_e(_name(names, r.get("agent_id"))),
                         _e(_name(names, r.get("target_agent_id")))),
        _e(r.get("status"))])
    j_rows = rows(jobs, lambda r: [
        _when(r.get("created_at")), _e(r.get("status")),
        _e(_name(names, r.get("lead_agent_id"))),
        "%s of %s steps" % (_e(r.get("done")), _e(r.get("total")))])

    parts = [
        _table("Jev decisions about team messages",
               ["Time (UTC)", "Path", "Kind", "Agent", "Took", "Urgency",
                "Reason", "Model", "Cost"], d_rows),
        _table("Jev checks",
               ["Time (UTC)", "Check", "Jev said", "Done", "Took", "Reason",
                "Model", "Cost"], c_rows),
        _table("Agent runs",
               ["Started (UTC)", "Agent", "Source", "Model", "Status",
                "Took", "Cost"], r_rows),
        _table("Agents asking agents",
               ["Time (UTC)", "Who", "Status"], a_rows),
        _table("Team jobs",
               ["Created (UTC)", "Status", "Lead", "Progress"], j_rows),
    ]
    return PAGE.format(body="\n".join(parts))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agents debug</title>
<style>
body {{ font: 14px/1.4 system-ui, sans-serif; margin: 16px; color: #111;
       background: #fff; }}
h1 {{ font-size: 18px; margin: 0 0 4px; }}
h2 {{ font-size: 15px; margin: 24px 0 6px; }}
p {{ margin: 4px 0; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #999; padding: 3px 6px; text-align: left;
          vertical-align: top; }}
th {{ background: #eee; }}
div.wrap {{ overflow-x: auto; }}
@media (prefers-color-scheme: dark) {{
  body {{ color: #ddd; background: #111; }}
  th {{ background: #222; }}
  th, td {{ border-color: #555; }}
}}
</style></head><body>
<h1>Agents debug</h1>
<p>Newest first, last {limit} of each. <a href="/tasks/agents">Back to AI Agents</a></p>
<div class="wrap">
{body}
</div>
</body></html>
""".replace("{limit}", str(LIMIT))


@router.get("/tasks/agents/debug", include_in_schema=False)
async def debug_page(user: CurrentUser = Depends(current_user)) -> HTMLResponse:
    data = await _read(user.email)
    names = await _names(user.email)
    return HTMLResponse(render_page(data, names))
