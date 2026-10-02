# Tracker Agent

Logs and retrieves application data. Optimized so that most questions
("how many did I apply to this week") never require an LLM to open
individual application files — see the token-efficiency note at the bottom.

## Per-job file
Every job that enters the pipeline (found, tailored, applied, or blocked)
gets one file at `applications/{date}-{company-slug}-{role-slug}.md`, with
YAML frontmatter for the summary fields and a body for full detail:

```markdown
---
company: Ramp
title: Senior Product Designer
location: San Francisco, CA (Remote)
source: LinkedIn
link: https://...
ats_score: 91
initial_ats_score: 91
tailored_ats_score: 94
score_delta: 3
resume_used: R2-kajabi
decision: Proceed
tailoring_level: minor
apply_path: direct ATS
account_wall: false
canonical_url: https://...
requisition_id: 12345
active_verified_at: 2026-07-31
active_verification_method: Greenhouse board API + rendered page
linkedin_status: no_equivalent_listing_found
linkedin_checked_at: 2026-07-31
tailoring_forced: false
status: Applied
date_found: 2026-07-31
date_applied: 2026-07-31
ai_detection_trap: false
---

## Job Description
{full JD text, or a link/reference to it}

## Screening Questions & Answers
- Q: What's your work authorization status?
  A: {answer given}
- Q: Expected salary?
  A: {answer given}
...

## Notes
{anything unusual about this application — account creation needed,
doc-handoff used instead of automation, etc.}
```

## Decision fields
Use these fields consistently so `TRACKER.md` stays useful without opening
full application files:
- `decision`: `Proceed`, `Review`, `Skip`, or `Blocked`, matching
  `agents/00-orchestrator.md`.
- `tailoring_level`: `minor`, `moderate`, or `heavy`, from Matching.
- `apply_path`: direct ATS, LinkedIn Easy Apply, company portal account,
  email-to-apply, Google Form, Notion/other handoff, or unknown.
- `account_wall`: true, false, or unknown.
- `initial_ats_score`: candidate/JD fit before tailoring. This drives the
  decision and is never overwritten.
- `tailored_ats_score`: final resume/JD alignment after the locked second
  scoring pass. Blank when no tailoring occurred.
- `score_delta`: tailored minus initial.
- `canonical_url` and `requisition_id`: stable duplicate keys.
- `active_verified_at`, `active_verification_method`, `linkedin_status`, and
  `linkedin_checked_at`: discovery proof.
- `tailoring_forced`: true only when the user explicitly overrode the normal
  reuse/tailoring recommendation.

If a job is blocked or skipped, keep the reason in `status` when short
(`Blocked — needs account`, `Skipped — dealbreaker`) and add the detail in
Notes.

## Status lifecycle
`Found` → `Scored` → `Tailored` → `Ready to Apply` → `Applied`
(or `Blocked — needs account`, `Skipped — dealbreaker`, `Declined by user`)

Update the status field in place as a job moves through the pipeline — 
don't create duplicate files for the same job.

## The summary table
`TRACKER.md` at the repo root is the human-facing table (company, role,
score, decision, status, applied date, documents, and posting link) —
generated from every file's frontmatter.

**Do not use an LLM to build this table.** Run `scripts/build_tracker.py`,
which parses just the frontmatter of every file in `applications/` and
writes the table. This is a mechanical parsing task, not a reasoning task —
using an LLM for it would burn tokens reading full job descriptions and
Q&A logs it doesn't need.

Run `python3 scripts/job_index.py build` after tracker-affecting changes. The
index provides exact duplicate and similar-role candidates without loading
application bodies into the LLM. It is disposable; markdown stays authoritative.

## Answering questions about past applications
1. Check if `TRACKER.md` already answers it (counts, filters by company
   stage, status, date range, etc.) — read that table first.
2. Only open a specific job's full file in `applications/` when the
   question is about that job's actual detail (what was asked, what was
   answered) — never open files in bulk to answer something the summary
   table already covers.
