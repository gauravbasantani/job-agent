# AGENTS.md — Read This First

This file is the entry point for any AI agent working in this repo (Claude Code,
GPT, Kimi, or anything else). Keep this file short. Do not load anything below
until the current task actually needs it — that's the whole token strategy of
this repo. Read only what the task requires, nothing more.

## What this system does

Finds job postings, matches them against the user's resumes, tailors the best
match to the specific job description, drafts screening-question answers, and
tracks every application. A human always confirms before final submission —
no exceptions, regardless of match score.

When returning job-search results to the user, include the ATS/match score and
best-fit resume variant for each role unless he explicitly asks for discovery
only. Discovery finds the posting; Matching decides whether it is worth acting
on.

## Default job workflow

- Supported command intent is explicit:
  - `check {url}` verifies, dedupes, scores, and recommends an action without
    preparing application artifacts.
  - `apply {url}` runs the full pipeline and fills the form, stopping at the
    final-submit boundary.
  - `force tailor {url}` prepares a truthful tailored resume even when reuse
    or skipping would normally be recommended. It does not override hard
    rules, dealbreakers, unsupported claims, or the submit boundary.
  - `continue {job}` resumes the existing browser tab after a human completes
    an account, credential, OTP, or CAPTCHA step.
  - `submit {job}` is confirmation for that named prepared application only.
- Search filters may be written naturally or as
  `job_title:"..." jobboard:"..." company_page:true not_on_linkedin:true`.
  An omitted or empty `jobboard` means all supported direct ATS/company
  sources, not "no sources."
- `find`, `search`, `list`, or `show` means: verify each posting is live, run
  Matching, and return the canonical link, ATS score, best resume variant,
  decision, and source-verification status.
- `not on LinkedIn` is a real exclusion filter. Check for an equivalent
  LinkedIn Jobs listing and include only roles whose live company/ATS posting
  cannot be found there. Record how the exclusion was checked.
- `apply`, `fill`, `prepare`, or `find and apply` means run the complete
  pipeline. Do not stop after listing jobs. Tailor the resume, generate the
  final DOCX and PDF, create form answers and a cover letter when the form has
  a field, fill the live form, verify it, and stop only at the final-submit
  boundary or another hard-rule blocker.
- For a broad `find and apply` request with no count or score threshold,
  prepare the top 3 jobs marked `Proceed`. This is a workload default, not
  permission to submit.
- Never ask whether to run a repository script, Python helper, browser check,
  or other normal in-scope step. Run it. Tool/sandbox approval prompts may
  still appear when the environment requires them.
- A role is not `Ready to Apply` until its application folder contains the
  tailored markdown, recruiter-facing PDF, editable DOCX, form answers, and
  any cover letter required by the live form.
- Before spending tokens on a known job, run the deterministic application
  index. Exact requisitions already submitted are reported as duplicates;
  prepared jobs resume in place; similar prior jobs become reuse candidates.
- Keep two scores when tailoring occurs: `initial_ats_score` is the honest
  candidate/JD fit from the best existing resume, and `tailored_ats_score` is
  the final resume/JD alignment after truthful tailoring. Never overwrite the
  initial score or let immutable gaps improve during the second scoring pass.
- Fill live forms through the shared ATS adapters, not a per-company script.
  `scripts/ats_fill.mjs` inspects the form, classifies every field, refuses
  credentials/OTP/ID/payment fields outright, fills only fields that have an
  explicit answer, reads every value back, and stops at the submit boundary.
- Human-only steps (account creation, login, OTP, emailed verification,
  CAPTCHA) are recorded with `scripts/verification_handoff.py`, which keeps
  the tab mapped and tells the user exactly what to complete before
  `continue {job}`.
- Instructions sent from a phone go through `scripts/command_queue.py`.
  Enqueuing is idempotent and audited, and it is never authorization to
  submit — a queued `submit {job}` still hits the confirmation gate.

## Where things live (load only what you need)

| Need to... | Read this |
|---|---|
| **Verify any claim about the user before using it** | **`profile/profile-for-agents.md`** (source of truth, 2026-10-02) |
| Explain why YourSideProject's source is private | `profile/why-repos-are-private.md` |
| Understand the rules that apply to everything | `context/hard-rules.md` |
| Match the user's writing voice | `context/writing-style.md` |
| Know what makes a resume ATS/HR-standard | `context/resume-standards.md` |
| Generate the final resume file (format/naming/scan rules) | `context/resume-output-spec.md` |
| Run the whole pipeline start to finish | `agents/00-orchestrator.md` |
| Search for jobs | `agents/01-discovery.md` |
| Score a job description against resumes | `agents/02-matching.md` |
| Rewrite a resume for a specific JD | `agents/03-tailoring.md` |
| Write a cover letter | `context/cover-letter-guidelines.md` + `agents/07-cover-letter.md` |
| Fill out and submit an application | `agents/04-application.md` |
| Inspect/fill a form on any supported ATS | `scripts/ats_adapters.mjs` + `scripts/ats_fill.mjs` |
| Manage Chrome tabs, retries, Slack/Gmail/account handoff, or remote commands | `context/automation-runtime.md` |
| Run jobs queued from the user's phone while he is away | `context/mobile-workflow.md` |
| Read/write the user's personal data | `agents/05-profile.md` |
| Log or look up an application | `agents/06-tracker.md` |
| Update statuses from pasted job emails | `scripts/email_status_update.py` |
| Start a new session with the right context | `context/new-chat-prompt.md` |
| Find the user's actual resumes/personal info | `profile/` (gitignored, local only) |
| See past applications | `applications/` (gitignored, local only) — or the summary in `TRACKER.md` |

## The claim rule (added 2026-10-02)

`profile/profile-for-agents.md` is the single source of truth for every factual
claim about the user: numbers, ownership, project status, links. `profile/proof-points.md`
is corrected to match it and carries the approved bullets.

**On every new resume or cover letter: use `yourname.example.com` as the
portfolio link, and take metrics from the corrected proof points, never from an
older `resume-used.md`.** Material already sent is not revisited. Its **"Never
claim"** list overrides this file, the résumé standards, and anything written
in an older application folder. Do not copy a bullet from a previous
`resume-used.md` without checking it against that list first; many older
folders contain claims that are now forbidden.

## The rule that never changes

Read `context/hard-rules.md` in full before doing anything that touches an
actual job application. It is short on purpose. Follow it exactly.

## Operating mode: decide, don't ask

the user wants one prompt in and a result out. Rounds of clarifying questions
are the failure mode, not diligence. **Decide and proceed**, then list the
assumptions you made at the end so he can correct any of them in one pass.

**Decide these yourself. Never ask:**
- Which resume variant to use, and how heavily to tailor it
- Which bullets to cut, keep, or reorder
- Whether a job is worth including in results
- Search scope when unspecified — take it from `profile/personal-info.md`
- Every demographic, EEO, and compliance answer — they are recorded in
  `profile/personal-info.md`, so read them, never re-ask and never infer a
  value from a name or nationality
- Filenames, folder names, and where output goes
- Whether to write a cover letter (write one whenever the form has a field)

**Ask only when:**
1. A hard rule requires it — final submit, account creation, credentials
2. A fact about the user is genuinely not in `profile/` and cannot be
   inferred, e.g. "Have you used {product}?" Leave the field blank, keep
   going, and mention it once at the end
3. An action is irreversible and outward-facing — pushing a repo public,
   emailing a recruiter

**When information is missing, take the defensible default and say so.**
A stated assumption the user can reject in five seconds beats a question that
blocks the work.

**Verify your own output before reporting it.** Logs lie. A fill script
reported a successful selection while having picked "Cisgender woman"
for a man; a page-count check passed on a resume that was two-thirds empty.
Render the PDF and look at it. Read back what a form field actually holds.

## Token discipline

- Never open `applications/*.md` in bulk to answer a question the generated
  `TRACKER.md` table can already answer. Run `scripts/build_tracker.py`
  (no LLM needed) to keep that table current, and read the table, not the files.
- Never re-parse `profile/resumes-docx/` or `profile/resumes-pdf/` during search
  or tailoring. Read the pre-extracted `profile/resumes-md/` versions instead.
  Only touch the original docx/pdf when generating a final submission file.
- Each agent file below is scoped to one job. Don't load `04-application.md`
  while doing discovery, and so on.
- Prefer one focused script or API request over repeated shell exploration.
  Do not print directory trees, inspect unrelated applications, or rerun the
  same lookup when a saved result is still current.

## Tests

`./scripts/run_tests.sh` runs everything (Python `unittest` + `node --test`,
no third-party runners). Run it after changing any script in `scripts/`.
Coverage: command parsing, job index/dedupe, ATS score guard, tracker build,
Chrome tab mapping and state machine, ATS adapter detection/field inspection,
and verification-handoff/phone-queue idempotency,
and email status classification (rejection vs interview wording).

## For humans setting this up

See `README.md` for setup steps, folder meanings, and first-run instructions.
