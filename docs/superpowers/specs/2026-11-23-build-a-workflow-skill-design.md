# Build a workflow from plain words — design (approved 2026-11-23)

## Intent

Lukas, standup 2026-11-19: people who never automated anything should be
able to get an n8n workflow by describing a job, without being asked
"what's the trigger?". Each user brings their own n8n (Connections), and
the point of that is that a workflow uses the apps they already connected
in AIUI (`link_aiui`).

## What gets built

A built-in skill, `agent_skills/build-a-workflow/SKILL.md`, which the main
chat's skill pick (`agent_jev.pick_skills_for_message`, cut 0.90) chooses
when somebody describes a job to happen on its own.

The skill tells the model to:

1. Ask what should happen, in their words. Never say trigger, node,
   webhook or cron unless they did.
2. Ask when, as plain choices: when you press a button (manual), every
   day or week at a time (schedule), when another app or website sends
   something (web address).
3. Use the apps connected in AIUI through `link_aiui`, not ask for vendor
   keys inside n8n.
4. Say the plan back in one or two sentences and build only on a yes.
   Created switched off; offer to switch it on.
5. Point elsewhere when n8n through AIUI cannot do it: "when an email
   arrives" → Automations (email trigger); a plain timed job for the
   assistant → Schedules.
6. No n8n connected → say so; the Connect button comes from the triage.

## Approaches considered

- **A skill (chosen).** Matches Lukas's words ("giving it skills"), reuses
  the skill pick, the tool loop and the approval on writes; text plus a
  calibration, no new code path.
- A rewrite of `create_workflow`'s tool help: reaches only a model that
  already chose the tool, so the questions come too late.
- A dedicated question flow in code: most control, most code, and it
  duplicates what the skill loop already does.

## Checks

- Unit: the skill loads, fits `MAX_SKILL_CHARS`, names its tools, and the
  body avoids the jargon it forbids in what it tells the person to hear.
- Live: `scripts/jev_checks_calibrate.py skills` with new cases. It must
  be picked for the three example jobs and never for the general cases or
  the other skills' cases. Wrong picks → fix the description, re-measure.

Example jobs (builder's call, the user handed over the choice):
"save the people who fill in my website form into Airtable", "every
Monday send my team a summary of last week's GitHub issues", "when
someone books a meeting, add them to my CRM" (no AIUI path yet).

## Not in scope

Gmail send / Calendar create from n8n steps; starting a workflow from an
email. Separate work.
