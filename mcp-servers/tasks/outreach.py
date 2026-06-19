"""Pure outreach logic: prompt, JSON candidate extraction, cap/dedupe,
n8n POST, summary text. No DB. Tested in tests/test_outreach_logic.py."""
from __future__ import annotations

import json
import os
import re
from typing import Optional

import httpx
from pydantic import BaseModel

from claude_executor import extract_final_body

N8N_BASE = os.environ.get("N8N_WEBHOOK_BASE", "https://n8n.srv1041674.hstgr.cloud")
OUTREACH_WEBHOOK_PATH = "recruiting-outreach"
_FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


class Candidate(BaseModel):
    name: str
    github_url: str = ""
    email: Optional[str] = None
    subject: str = ""
    body: str = ""


class CandidateList(BaseModel):
    candidates: list[Candidate] = []


def extract_candidates(raw_log: str) -> CandidateList:
    """Pull the fenced ```json block out of the agent's pre-sentinel body."""
    body = extract_final_body(raw_log) if raw_log else ""
    if not body:
        return CandidateList()
    m = _FENCE.search(body)
    if not m:
        return CandidateList()
    try:
        data = json.loads(m.group(1))
        return CandidateList(**data)
    except (ValueError, TypeError):
        return CandidateList()


def cap_and_dedupe(candidates: list[Candidate], count: int) -> list[Candidate]:
    """Drop duplicate emails (case-insensitive); cap the *emailable* subset to
    `count`. No-email candidates are always kept (collected, not emailed)."""
    seen: set[str] = set()
    emailable: list[Candidate] = []
    no_email: list[Candidate] = []
    for c in candidates:
        if c.email:
            key = c.email.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            emailable.append(c)
        else:
            no_email.append(c)
    return emailable[:max(0, count)] + no_email


def build_outreach_prompt(role: str, location: str, jobdesc: str, count: int,
                          *, direction: str = "hire") -> str:
    if direction == "reverse":
        rloc = f" in {location}" if location.strip() else ""
        return f"""You are a job-search assistant working ON BEHALF OF a job seeker. \
Find up to {count} companies hiring for: {role}{rloc}, then draft a tailored \
application email to each — written in the FIRST PERSON as the seeker.

The seeker's background / skills (use this to tailor every application):
---
{jobdesc}
---

STEPS:
1. Use the WebSearch and WebFetch tools to find companies plausibly hiring for \
"{role}"{rloc}. For each company, find a REAL careers/jobs/hiring-contact email \
(careers@, jobs@, or a named recruiter). Never guess or fabricate an email — use \
null if you cannot find a real one.
2. Draft a SHORT, tailored, first-person application email per company (subject + \
body), grounded in the seeker's background above and signed as the seeker.
3. Output EXACTLY ONE fenced json block (no prose after it), then a new line with \
the single word COMPLETED. Use name = the company, github_url = the company \
careers/jobs URL, email = the contact email (or null), and subject/body = the \
application:
```json
{{"candidates":[{{"name":"...","github_url":"...","email":"... or null","subject":"...","body":"..."}}]}}
```
If you cannot find any companies, output a candidates list of [] then COMPLETED. \
On a hard error, output a line starting with FAILED: and the reason."""
    loc = f" located in {location}" if location.strip() else ""
    return f"""You are a recruiting research assistant. Find up to {count} software \
engineers matching: {role}{loc}.

STEPS:
1. Build a GitHub user-search query from the role and location and call the GitHub \
API with Bash, e.g.:
   curl -s -H "Authorization: token $GITHUB_TOKEN" \
   "https://api.github.com/search/users?q={role}+{location}+type:user&per_page={count*2}"
   (URL-encode the query; $GITHUB_TOKEN is in your environment.)
2. For each login, GET https://api.github.com/users/<login> to read the public \
email and name. Where the email is missing, use the WebSearch / WebFetch tools to \
try to find a public professional email. Never guess or fabricate emails — use null \
if you cannot find a real one.
3. Draft a SHORT, personalized recruiting email for each engineer referencing \
their work and this job description:
---
{jobdesc}
---
4. Output EXACTLY ONE fenced json block (no prose after it) of this shape, then a \
new line with the single word COMPLETED:
```json
{{"candidates":[{{"name":"...","github_url":"...","email":"... or null","subject":"...","body":"..."}}]}}
```
If you cannot find anyone, output a candidates list of [] then COMPLETED. \
On a hard error, output a line starting with FAILED: and the reason."""


async def post_outreach_to_n8n(job_title: str, candidates: list[Candidate],
                               *, timeout: float = 90.0) -> dict:
    """POST the batch to the n8n recruiting-outreach webhook (mirror routes_cron).
    Returns the parsed JSON ({sent, saved, sheet_url}) or raises on non-2xx."""
    url = f"{N8N_BASE.rstrip('/')}/webhook/{OUTREACH_WEBHOOK_PATH}"
    payload = {"job_title": job_title,
               "candidates": [c.model_dump() for c in candidates]}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        text = resp.text.strip()
        return json.loads(text) if text else {}


def format_outreach_summary(found: int, sent: int, saved: int, sheet_url: str = "") -> str:
    # `saved` is the total written to the sheet this run (emailed + collected),
    # per the n8n Respond node — so phrase it as total-saved, not "no-email only".
    parts = [f"Outreach complete — found {found} engineer(s).",
             f"Emailed {sent}.",
             f"Saved {saved} to your sheet."]
    return " ".join(parts)


def build_review_candidates(candidates: list[Candidate]) -> list[dict]:
    """Manual-review rows with stable ids. Selected defaults ON for emailable
    candidates, OFF for no-email ones."""
    rows = []
    for i, c in enumerate(candidates):
        email = (c.email or "").strip()
        rows.append({
            "id": f"c{i}", "name": c.name, "github_url": c.github_url,
            "email": email, "subject": c.subject, "body": c.body,
            "selected": bool(email),
            "status": "draft" if email else "no_email",
        })
    return rows


def apply_candidate_edit(candidates: list[dict], cid: str, *, email=None,
                         subject=None, body=None, selected=None) -> list[dict]:
    """Return a new list with row `cid` updated. Unknown cid -> unchanged.
    Email drives status: an email makes it draft/selectable; no email forces
    status=no_email and selected=False."""
    out = []
    for c in candidates:
        if c["id"] != cid:
            out.append(c)
            continue
        c = dict(c)
        if email is not None:
            c["email"] = email.strip()
        if subject is not None:
            c["subject"] = subject
        if body is not None:
            c["body"] = body
        has_email = bool(c["email"])
        c["status"] = "draft" if has_email else "no_email"
        if not has_email:
            c["selected"] = False
        elif selected is not None:
            c["selected"] = bool(selected)
        out.append(c)
    return out


def set_selection(candidates: list[dict], selected_ids: list[str]) -> list[dict]:
    """Overwrite selection with exactly `selected_ids` (only emailable rows can
    end up selected). Mirrors a Discord multi-select reporting the full set."""
    chosen = set(selected_ids)
    out = []
    for c in candidates:
        c = dict(c)
        c["selected"] = (c["id"] in chosen) and bool(c["email"])
        out.append(c)
    return out


def sendable_candidates(candidates: list[dict]) -> list[Candidate]:
    """Selected + has-email rows -> Candidate objects for n8n."""
    return [Candidate(name=c["name"], github_url=c["github_url"], email=c["email"],
                      subject=c["subject"], body=c["body"])
            for c in candidates if c.get("selected") and (c.get("email") or "").strip()]


def review_summary(candidates: list[dict]) -> dict:
    emailable = sum(1 for c in candidates if (c.get("email") or "").strip())
    selected = sum(1 for c in candidates
                   if c.get("selected") and (c.get("email") or "").strip())
    return {"total": len(candidates), "emailable": emailable, "selected": selected}
