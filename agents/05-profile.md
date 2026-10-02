# Profile Agent

Manages reading (and, when the user asks, updating) the user's personal
data in `profile/`. This folder is gitignored — it never gets pushed. Other
agents read from here; this file defines what should be in it and how it's
kept efficient.

## Folder contents and purpose

- `profile/resumes-docx/` — original resume files, source of truth for
  formatting. Not read directly during search/matching/tailoring.
- `profile/resumes-pdf/` — same content as backup/alternate extraction
  source.
- `profile/resumes-md/` — markdown extraction of each resume variant,
  regenerated whenever a docx/pdf source changes. **This is what every
  other agent actually reads** during search, matching, and tailoring —
  cheap to load, cheap to re-read repeatedly in one session.
- `profile/cover-letters-docx/` — original base cover letter files, source
  of truth for formatting. Not read directly during drafting.
- `profile/cover-letters-pdf/` — same content as backup/alternate
  extraction source.
- `profile/cover-letters-md/` — markdown extraction of each base cover
  letter, regenerated whenever a docx/pdf source changes. **This is what
  `07-cover-letter.md` actually reads** when drafting — the structure and
  phrasing in these files are the user's voice template.
- `profile/personal-info.md` — contact info, address, phone, work
  authorization status and dates, EEO/voluntary-disclosure answers
  (race/ethnicity, veteran status, gender), salary floor and target,
  location preferences, and hard dealbreakers (e.g. sponsorship
  requirements). See `profile/personal-info.template.md` for the schema.
- `profile/proof-points.md` — reusable, real achievement/metric blocks the
  tailoring and application agents pull from. See
  `profile/proof-points.template.md` for the schema.

## Extraction step (run once, or whenever a source file changes)
When a new or updated file appears in `resumes-docx/` or `resumes-pdf/`,
extract its full text content into a matching file in `resumes-md/`. This
is a one-time cost per resume version — every subsequent search, match, or
tailor pass reads the cheap markdown copy instead of re-parsing the
original file.

The same extract-once pattern applies to cover letters: a new or updated
file in `cover-letters-docx/` or `cover-letters-pdf/` gets extracted to a
matching file in `cover-letters-md/`, and only the markdown is read during
drafting.

## What this agent does NOT do
It doesn't score or tailor anything — it only serves data to the agents
that do. It doesn't decide what counts as a dealbreaker — it surfaces
whatever the user has written in `personal-info.md` and other agents apply
it.
