# Matching Agent

Scores a job description against the user's resume variants and picks the
best base resume for tailoring. Read `profile/resumes-md/` (pre-extracted
markdown, not the original docx/pdf) and `profile/personal-info.md`
(dealbreakers, salary floor) before scoring.

## Reading the experience requirement correctly
Do not take the smallest "N years" figure in a JD. Postings routinely
contain several: "6+ years in Product/UX Design" alongside "3+ years
managing stakeholders" and unrelated numbers. The seniority signal is the
one attached to the **core discipline** requirement, which is usually the
largest and appears first in the requirements list.

This was scored wrong once: an Oscar Health posting requiring 6+ years was
read as 3, turning a 12-point seniority penalty into a 3-point bonus and
reporting 91% for what was really about 72%. Extract the requirements
section first, then read the years from it, rather than regexing the whole
document.

## Scoring approach
For each JD, compare against every resume variant in `profile/resumes-md/`:
- Role/title alignment — 20 points
- Must-have skills and keyword overlap — 25 points
- Evidence strength from real resume/proof-point content — 20 points
- Seniority match — 10 points
- Domain/product relevance — 10 points
- Location, work mode, compensation, and authorization fit — 10 points
- Application feasibility and freshness — 5 points

Use whole numbers and write the reason for any large deduction. The score
is a decision aid, not permission to ignore hard rules.

## Two-stage scoring contract
The first pass is always `initial_ats_score`. It compares the JD with every
existing resume variant and represents the honest candidate/job fit before
job-specific rewriting. This is the score used for the Proceed/Review/Skip
decision.

When Tailoring produces `resume-used.md`, run the same rubric again and store
the result as `tailored_ats_score`. Keep both scores and report
`score_delta = tailored_ats_score - initial_ats_score`. The second score is an
estimated final-resume alignment score, not a claim about a proprietary ATS.

Lock these dimensions to their first-pass scores during rescoring because
wording cannot change them:
- seniority and required years;
- credentials, clearance, and unsupported tools;
- actual industry/domain history;
- location, work mode, compensation, and work authorization;
- posting freshness and application feasibility.

Only resume-controlled representation may improve: honest title-family
language, must-have keyword coverage, proof-point selection, evidence
specificity, and visibility/order. If a second-pass increase cannot be traced
to a changed final-resume line, remove it. If tailoring lowers the score,
repair or revert the harmful change rather than hiding the result.

For a tailored application, save the two dimension maps and documented resume
changes to `score-breakdown.json`, then run:
```
python3 scripts/score_guard.py applications/{job}/score-breakdown.json
```
Do not report the tailored score or mark the resume ready unless the validator
returns `valid: true`. Use `hard_cap: 69` when an unsupported required
credential/tool/experience triggers the existing cap, and `dealbreaker: true`
when both scores must remain zero.

## Dealbreaker gates
Apply these before scoring:
- Any explicit dealbreaker from `profile/personal-info.md` (for example,
  sponsorship or salary floor) — if the JD clearly fails it, score 0 and
  mark `Skip — dealbreaker`.
- Roles requiring credentials, years, tools, portfolio type, security
  clearance, or industry experience the profile clearly does not support
  should not exceed 69, even if keyword overlap is high.
- Jobs with incomplete JD text, unclear apply path, or uncertain
  compensation/location can score normally but must be marked `Review`
  unless the missing information is not material to the profile.

Produce one score per resume variant per job, and select the
highest-scoring variant as that job's match. Ties go to whichever variant
needs less tailoring work.

## Score bands
- 90-100: Strong fit. Tailoring should mostly reorder and sharpen existing
  evidence. Mark `Proceed` if feasibility is clean.
- 80-89: Good fit. Proceed only if the run threshold allows it and the gaps
  are honest to address. Otherwise mark `Review`.
- 70-79: Possible but not optimal. Usually `Review`; do not auto-apply
  unless the user explicitly lowered the threshold.
- 0-69: Weak, risky, or blocked by dealbreaker. Mark `Skip` unless there is
  a strategic reason to keep it as a near-miss.

## HR screening lens
Score for how a recruiter and ATS will see the resume in the first pass:
- The posting title or title family should be visible in the resume's top
  third after tailoring.
- The top 5-7 hard requirements in the JD should map to actual resume
  lines or proof points, not only to broad skills labels.
- Recent, measurable impact beats older or vague keyword matches.
- A role is weaker if the resume can match it only by changing the user's
  identity, seniority, or core experience narrative.
- Penalize roles that are too junior, too senior, or a different function
  even when the design/product vocabulary overlaps.

## Output per job
- Initial ATS match score (percentage)
- Tailored resume alignment score and delta, when a final resume exists
- Best-fit resume variant
- Decision: `Proceed`, `Review`, `Skip`, or `Blocked`
- Tailoring level: `minor`, `moderate`, or `heavy`
- One line on what's driving the score (what matched well, what's missing)
- Top matched requirements and top gaps
- Any dealbreaker, feasibility, or application notes that affect the
  orchestrator's next step

Use this compact user-facing form:
`Initial ATS: 84% | Tailored alignment: 91% (+7) | Decision: Proceed`.
For an un-tailored check, show only the initial score and label it clearly.

## Filter behavior
If the calling context gave a score threshold, apply it here. If no threshold
was given, return the full scored list; the orchestrator uses the score bands
and request intent to decide whether to report results or prepare the top
`Proceed` jobs. Every user-facing job row includes the score and selected
resume variant unless the user explicitly requested discovery only.
