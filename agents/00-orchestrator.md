# Orchestrator

Runs when the user gives a single prompt covering the whole pipeline
("find and apply to X in Y") rather than one phase at a time. Read
`context/hard-rules.md` before starting. This file calls the other agent
files in sequence — it doesn't duplicate their logic.

## Parsing the prompt
Extract: role, location, and (optional) a match-score threshold. Also look
for source limits ("LinkedIn only"), seniority, remote/hybrid/on-site,
company stage, visa/sponsorship constraints, and volume ("top 10", "apply
to 5"). A prompt with no threshold ("find and apply UX jobs in SF") is not
the same request as one with a threshold ("...85%+") — see Mode A vs Mode B
below.

When the prompt is vague, use the defaults in `profile/personal-info.md`
for location, search radius, remote preference, salary floor, and
dealbreakers. Ask only if the missing role/title family would make the
search materially wrong. For example, ask before choosing between Product
Designer and Software Engineer, but don't ask whether "SF" includes nearby
hybrid roles if the profile already defines a default radius.

## Decision quality bar
Every job that leaves Matching must have a clear next action:
- `Proceed` — clears dealbreakers, score meets the run threshold, and the
  apply path is feasible.
- `Review` — promising but below threshold, missing one important signal,
  compensation/location is unclear, or automation will require doc handoff.
- `Skip` — fails a hard dealbreaker, is materially misaligned, appears
  stale/closed, or requires claims the user's profile cannot honestly
  support.
- `Blocked` — account creation, credentials, CAPTCHA, missing user fact, or
  an unsafe/unparseable form prevents progress.

The orchestrator should not pass ambiguous rows downstream. If a job is
`Review`, keep it in the results table with the reason. If it is `Skip`,
log the reason only when it has already entered the pipeline or would be
useful for dedupe. If it is `Blocked`, continue the rest of the batch and
surface the blocker at the end.

## Mode A — No threshold given
Intent controls how far the pipeline runs:

- Discovery intent (`find`, `search`, `list`, `show`): run Discovery →
  Matching and return ranked, scored results. Do not return title/link-only
  results unless the user explicitly requests discovery only.
- Action intent (`apply`, `fill`, `prepare`, `find and apply`): use Matching's
  normal score bands as the decision rule and run Tailoring → Application for
  the top 3 jobs marked `Proceed`, unless the prompt gives a different count.
  Do not wait for the user to pick rows and do not stop after listing jobs.

Sort results by decision, then score, then freshness. `Review` jobs remain in
the report but do not replace a `Proceed` job in the default top-three batch.

Missing role or location is not a reason to stop in this mode — take the
defaults from `profile/personal-info.md`, run the search, and state the
scope you used. Only a missing *role* is worth one short question, because
searching for the wrong job title wastes the whole cycle.

Normalize these command forms before running the pipeline:
- `check {url}`: live verification -> deterministic duplicate lookup ->
  Matching. Do not tailor or open the application form.
- `apply {url}`: run the full sequence and stop before final submit.
- `force tailor {url}`: run Matching, record the real initial score, then
  tailor even when the normal action would be reuse, Review, or Skip. This
  never overrides dealbreakers, factual accuracy, account/credential gates,
  or final-submit confirmation.
- `continue {job}`: reopen or focus the existing mapped browser tab and resume
  after the user completed the reported human-only step.
- `submit {job}`: explicit confirmation for the named prepared job. Verify
  the company, title, attached files, and review state again before clicking.
- Search filters: `job_title`, `jobboard`, `company_page`, and
  `not_on_linkedin`. An empty or omitted `jobboard` expands to all supported
  direct company/ATS sources.

For structured or mixed natural-language commands, run
`python3 scripts/job_command.py {original prompt}` and use its normalized
intent, board allowlist, and direct-source queries. The helper is a parser,
not a source of job facts; Discovery still verifies every result.

## Cheap preflight before LLM work
Run `python3 scripts/job_index.py build` once per run, then use
`python3 scripts/job_index.py lookup --url {url}` for supplied links. Use the
canonical URL or ATS requisition key first, then company + title + JD
similarity. The result controls the next action:
- Exact requisition with terminal/application status: report the prior result;
  do not open or apply again.
- Exact requisition still prepared/blocked: reuse its folder and browser job
  key; resume instead of creating a second application.
- Similar prior role: pass the closest candidate to Tailoring for delta reuse.
- No match: continue normally.

The generated index is a cache. Application markdown remains the source of
truth, so rebuild the index after status or score changes.

## Score lifecycle
`initial_ats_score` is calculated against every existing resume variant before
tailoring and drives Proceed/Review/Skip. If Tailoring runs, rescore the final
resume with the same rubric as `tailored_ats_score` and report the delta.
Seniority, credentials, domain history, authorization, location, compensation,
freshness, and application feasibility are immutable between passes. Only
resume-controlled dimensions such as truthful title language, keyword
coverage, evidence visibility, and bullet ordering may improve. Never replace
the initial score with the tailored score.

## Mode B — Threshold given
Run Discovery → Matching → filter to only jobs at or above the threshold →
Tailoring (`03-tailoring.md`) for each survivor → Application
(`04-application.md`) fills every field and drafts every answer, stopping
each one right before final submit.

If the user asks to "apply" with a threshold, only jobs marked `Proceed`
move automatically. Jobs marked `Review` are shown separately, even when
their raw score clears the threshold, because feasibility and dealbreakers
override numeric fit.

**Batch confirm rule:** read the batch-confirm threshold from
`profile/personal-info.md`. The user has set no fixed default — the
threshold is whatever the current run specifies (the optional score argument
in `/job-pipeline {role}, {location}, {optional score}`). Jobs at or above
that run's threshold are grouped into a single batch confirmation once ready
("N ready — confirm to submit all?"); everything below it is confirmed
individually. **If a run specifies no threshold, confirm every application
individually** — never assume a batching level the user didn't give. The
submit boundary in `context/hard-rules.md` rule 1 applies either way; this
rule only controls grouping.

## Sequence for one job, end to end
1. Deterministic index checks prior applications and reusable artifacts
2. Discovery finds and dedupes the posting, pulls full JD text
3. Matching records `initial_ats_score` against resume variants and picks the best base
4. Orchestrator assigns a next action (`Proceed`, `Review`, `Skip`, or
   `Blocked`) using Matching's score plus feasibility/dealbreaker notes
5. Tailoring reuses or rewrites that resume against the JD, checked against
   `context/resume-standards.md` and `context/resume-output-spec.md`
6. Matching rescores the final resume as `tailored_ats_score`, preserving all
   immutable dimension scores and recording the score delta
7. Cover Letter (`07-cover-letter.md`) — only if the form has a cover letter
   field (required or optional) or the user asked for one. Requires the
   tailored resume from step 4 to exist first. Skip entirely when the form
   has no such field; don't write one speculatively.
8. Application drafts answers, opens/reuses the mapped Chrome tab, fills every
   field, attaches resume and cover letter, stops at the submit boundary
9. Confirmation gate (individual or batch, per the rule above)
10. On yes: submit, then Tracker (`06-tracker.md`) logs the result
11. On no: leave it in "Ready to Apply" state in the tracker, don't discard it

## Edge cases to handle explicitly

**Zero jobs clear the threshold:** report the search happened and what the
best score found was. Ask whether to show the near-misses or lower the bar.
Don't silently return nothing.

**A job requires account creation:** per hard-rules.md, this pauses that
one specific job with a signup link, and does not block the rest of the
batch. Resume it when the user confirms the account exists.

**A posting has no real form** (a Notion page, an email-to-apply listing):
switch that one job to doc handoff — draft the answers into a document for
the user to paste in manually — rather than failing to automate it. Note
this clearly when presenting the batch.

**Playwright can't reliably parse a page:** stop on that one job, tell the
user what's blocking it, don't guess at field mapping on a real submission.

## Gates before downstream work

**Live-posting gate:** verify that the canonical company/ATS page still
exposes the real title, JD, and application path. A search snippet, cached
page, or aggregator copy is not enough. If an ATS API returns no posting or
the browser shows not found/closed, mark `Skip — closed` and continue searching
for a replacement.

**Source-exclusion gate:** when the prompt says `not on LinkedIn`, Discovery
must check for an equivalent LinkedIn Jobs listing by company, title, location,
and requisition where available. Exclude confirmed LinkedIn listings and label
survivors `LinkedIn check: no equivalent listing found` with the check date.

**Artifact gate:** before reporting `Ready to Apply`, verify the application
folder contains `resume-used.md`, the named DOCX and PDF, `form-answers.md`,
and a cover letter artifact when the form exposes a cover-letter field. Render
and inspect the PDF and read live form values back. `Prepared but not filled`
and `Filled, awaiting submit` are different statuses.

Resume artifacts must be generated the same way from chat and queued Slack
commands: copy the selected source DOCX, run paragraph ordering/replacements
sequentially, run `scripts/fix_docx_contact_links.py`, export through
`scripts/export_docx_to_pdf.applescript`, then check that `format_fallback` is
false, the rendered PDF is a visually clean one-page resume, and PDF
annotations show only the intended visible URLs. A fallback PDF, a blank
trailing page, broad header click zone, hidden stale hyperlink, or parallel
edits to the same DOCX fail this gate.
