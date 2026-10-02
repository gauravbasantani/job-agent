# Cover Letter Agent

Writes a tailored cover letter for a specific job. Runs after Tailoring
(the resume must exist first — the letter references what the resume
proves). Read `context/writing-style.md` and `context/hard-rules.md`
before drafting.

## Source material (in priority order)
1. `profile/cover-letters-md/` — extracted versions of the user's own base
   cover letters (see extraction note below). Their structure and phrasing
   are the voice template — the letter should sound like the user's
   existing letters, not like a generic AI letter.
2. The tailored resume for this job (`applications/{job}/resume-used.md`) —
   the letter highlights 2-3 things from it, it doesn't repeat all of it.
3. `profile/proof-points.md` — for the specific story/metric the letter
   leads with.
4. **Company research** — before drafting, do a quick search on the
   company: what they build, recent launches or funding, what the team
   seems to care about. One or two genuinely specific references beat five
   generic compliments. Never fabricate company facts — if research turns
   up nothing solid, write around it rather than inventing.

## Extraction step
Same pattern as resumes: when the user adds base cover letters to
`profile/cover-letters-docx/` or `cover-letters-pdf/`, extract each to
markdown in `profile/cover-letters-md/` once, and read only the markdown
during drafting.

## Header block
Top of every letter:
- Name, phone, email, portfolio link, location — pulled from
  `profile/personal-info.md`.
- **Conditional relocation line:** compare the job's location against the
  user's current location.
  - Job is in another city/state and NOT remote → include
    "(open to relocating to {job city})" in the header location line.
  - Job is remote, or in the user's current metro → omit the line
    entirely. Don't leave a placeholder.

## Body rules
- Opens per `writing-style.md`: "Hi I am {{NAME}}, {{TITLE}} with
  {{ONE_LINE_HOOK}}." — with the hook chosen to match this JD.
- 250-350 words. One page, always. Nobody reads a two-page cover letter.
- Structure: why this company specifically (the researched, genuine
  reason) → the 1-2 proof points most relevant to their JD → close with a
  direct, non-groveling line.
- Human tone throughout: no "I am excited to leverage," no restating the
  job posting back at them, no flattery padding. Every sentence should be
  something the user could say out loud in an interview without wincing.
- Never reuse a letter verbatim across companies. Substance can repeat;
  phrasing and company anchoring must be fresh per letter.

## Output
```
applications/{date}-{company}-{role}/
  cover-letter.md                                  (source)
  Your_Name_{Job_Title}_Cover_Letter.docx
  Your_Name_{Job_Title}_Cover_Letter.pdf    ← attached when a form asks
```
Same naming pattern as the resume spec. Generate the PDF only when the
application actually has a cover letter field — many don't, and the draft
can sit as markdown until needed.

## When to write one
- The application form has a cover letter field (required or optional —
  fill optional ones too, they're a differentiator precisely because
  most people skip them).
- The user explicitly asks for one.
- Skip silently when the form has no field for it, but note in the
  tracker whether one was written/used per job.
