# Tailoring Agent

Rewrites the matched resume variant against a specific job description.
Read `context/resume-standards.md` in full before starting — every output
is checked against that rubric before being marked ready.

## Working format
Work entirely in markdown. Read from `profile/resumes-md/{variant}.md` (the
pre-extracted version), never the original docx/pdf during this step — that
keeps iteration cheap. Only generate a real docx/pdf output at the point
`04-application.md` actually needs a file to attach to a submission, using
the docx/pdf skills, from the final tailored markdown.

Final file generation must follow `context/resume-output-spec.md` — one
page, Calibri, PDF as the submission format, and the
`Your_Name_{Job_Title}_Resume.pdf` naming rule. Run that file's
7-second scan check before marking the resume ready. `resume-standards.md`
governs the content; `resume-output-spec.md` governs the artifact, and a
resume is not ready until it passes both.

**Generate the final file by editing the matched `.docx` in place**, per the
build method in `resume-output-spec.md`. Reordering bullets is the primary
tailoring move and it costs nothing — it preserves the original formatting
exactly. Do not rebuild the resume layout from markdown; the user's existing
design is better than anything regenerated, and rebuilding loses the bold
emphasis inside bullets.

## Tailoring steps
1. Pull the JD's top 8-12 requirements/keywords (matching agent's output
   already surfaces the gaps — start there).
2. Reorder bullets within each role so the most JD-relevant items lead.
3. Swap in the proof point from `profile/proof-points.md` that best matches
   this JD, where more than one proof point could apply to the same line.
4. Adjust phrasing to naturally include JD keywords only where they are
   actually true of the user's real experience — never fabricate, per
   `context/hard-rules.md` rule 5.
5. Run the "per-job tailoring checklist" and "what good enough looks like"
   sections of `context/resume-standards.md` against the draft.
6. Save the tailored markdown to
   `applications/{date}-{company}-{role}/resume-used.md`.

## Reuse before re-tailoring
Run the deterministic job index before opening old application files. Check
only its strongest reuse candidate, then open that candidate's
`resume-used.md` if it was built from the same base variant for a similar
role. If one exists and the new JD's top
requirements are already reflected in it, copy it and adjust only what
differs — usually a handful of bullet swaps and the summary's opening
clause. A full re-tailor from the base variant is only warranted when the
role type genuinely changes (consumer fintech vs enterprise dev tools).

Markdown is the durable artifact. Generate `.docx`/`.pdf` only when a form
actually needs a file to attach; `scripts/build_tracker.py` prunes them
once the job reaches a terminal status, and they regenerate from
`resume-used.md` plus the source file in `profile/resumes-docx/`. Never
write generated resumes back into `profile/` — that folder holds the user's
own originals and nothing else.

## Decide whether tailoring adds value
Tailor when at least one truthful resume-controlled gap can materially improve
the recruiter/ATS first pass: missing but supported JD terminology, buried
proof, weak title-family language, or a better proof-point ordering. Reuse with
minimal edits when the closest prior resume already covers the new JD's top
requirements. Do not perform a dramatic rewrite merely to move a number.

`force tailor` overrides the reuse/benefit recommendation and requires a new
job-specific resume, but it does not unlock unsupported claims. Record
`tailoring_forced: true` and preserve the original decision and gaps.

After the final markdown is ready, hand it back to Matching for the locked
second pass described in `02-matching.md`. Save `initial_ats_score`,
`tailored_ats_score`, and `score_delta`; never overwrite the initial score.

## When to do a "minor" vs "heavy" tailor
If Matching flagged the job as already close to the resume, a minor tailor
(reordering, small phrasing) is enough. If it flagged significant gaps, do
a heavier rewrite — but never invent experience to close a gap. If the gap
can't be honestly closed, that should show up as a lower match score, not
as fabricated content.
