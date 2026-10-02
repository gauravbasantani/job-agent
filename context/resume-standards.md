# Resume Standards — ATS + HR Rubric

Every tailored resume is checked against this before it's marked "ready."

## ATS-parseable formatting
- No tables, text boxes, columns, headers/footers, or embedded graphics —
  many parsers drop or scramble content inside these.
- No icons or images used to convey information (a phone icon next to a
  number some parsers can't read).
- Standard, simple fonts. Standard section headers: "Work Experience,"
  "Education," "Skills" — not creative alternatives like "My Journey."
- Reverse chronological order within each section.
- Consistent date formatting throughout (e.g. "Jan 2023 – Present").
- 1-2 pages. No photos.

## Content quality
- Every bullet leads with a strong action verb and ends with a quantified
  result where the underlying data supports it (%, $, time saved, scale).
  Never invent a number that isn't in `profile/proof-points.md`.
- Keywords from the job description are matched naturally into real
  accomplishments — never stuffed as a bare list or in invisible text.
- Match seniority language to the JD (don't call yourself "lead" for a
  role titled "associate," don't undersell for a role titled "senior").

## Per-job tailoring checklist
1. Pull 8-12 of the most important keywords/skills directly from the JD.
2. Confirm each appears somewhere in the resume, in a real sentence, only
   where it's actually true.
3. Reorder bullets within each role so the most JD-relevant achievements
   lead.
4. Swap in the proof point from `profile/proof-points.md` that best matches
   what this specific JD is asking for, if more than one could apply.
5. Re-check length and formatting against the rules above before marking
   ready.

## What "good enough to submit" looks like
A tailored resume passes when: it would pass an ATS parse cleanly, a human
recruiter skimming it for 6 seconds would see the JD's top requirements
reflected in the top third of the page, and every claim on it is true and
sourced from the user's actual history.

The rules above govern content. The final generated file — page count, font,
filename, PDF export — is governed by `context/resume-output-spec.md`.
Tailoring checks both before marking a resume ready.

## HR first-pass optimization
The resume should make the recruiter say "yes, this is the right kind of
candidate" before they read deeply:
- Mirror the posting's title family in the headline when it is honest:
  Product Designer, UX Designer, Senior Product Designer, etc.
- Put the strongest 2-3 JD-matched bullets in the top third of the page,
  preferably with visible numbers or scale.
- Make hard requirements easy to find: tools, research methods, design
  systems, prototyping, cross-functional work, industry/domain, and launch
  impact should appear in normal prose, not hidden in a keyword pile.
- Preserve a coherent career narrative. Do not contort the resume so far
  toward one posting that it reads inconsistent with the user's actual
  background.
- Remove or lower bullets that are impressive but irrelevant when space is
  tight; recruiter attention is the scarce resource.

## Summary section — the standing rule

**Set by the user 2026-09-22. This applies to every resume from now on unless he
says otherwise for a specific job.**

The summary is **not** a second copy of the bullets. Metrics already appear in
Professional Experience; repeating "40% to 85%" or "70+ components" up top wastes
the most-read six lines on the page and reads like filler.

### What the summary must contain

1. **Who he is, plainly** — product or interaction designer, 4 years in, and the
   fact that three of those were as the only designer on the team.
2. **Why he does UX** — the actual reason, in his own words, not a mission
   statement.
3. **Curious and a quick learner**, shown rather than asserted: he builds small
   products on weekends to answer questions he cannot answer in Figma, then reads
   his own analytics even when the numbers are unflattering.
4. **One line that ties him to this specific role** — the single most important
   thing the JD asks for, phrased as what he finds interesting, never as a
   keyword list.
5. **Personal, human close** — he travels to new places whenever he can, and he
   loves good ice cream.
6. **Your University Sun Awards** for leadership and measurable product impact.

### What the summary must NOT contain

- **No repeated metrics** from the bullets below. This is the rule the user
  raised twice.
- **No degree recitation.** The Education section already carries the M.S. and
  the B.Tech. Name a degree in the summary only when the JD makes it a stated
  minimum or preferred qualification, as Google Trust did.
- No "passionate", "results-driven", "proven track record", or any phrase from
  the weak-phrase list above.
- **No count on the Sun Awards** until the number is confirmed. See
  `profile/proof-points.md`, Still NEEDS CONFIRMATION. Write "Your University Sun Awards",
  never "two Sun Awards".

### Working template

> {Product/Interaction} designer, 4 years in, three of them as the only designer
> on the team, which is how I learned to figure things out instead of waiting for
> a brief. {One sentence on what draws him to THIS role's core problem.} I build
> small products on weekends to answer questions I cannot answer in Figma, then
> read my own analytics even when the numbers are unflattering. Outside work I
> travel to new places whenever I can, and I love good ice cream. Recognized with
> Your University Sun Awards for leadership and measurable product impact.

Only sentence two changes between jobs. The rest is stable, because it is true
regardless of who is reading.

### Why this works
The bullets carry the keywords and the numbers, so the ATS is already satisfied
by the time a human reads the summary. What the summary buys is the thing no
bullet can: a person the reader can picture and wants to talk to. the user's
stated test is "anyone will read, understand, and call me to interview."

## Impact language rules

### Weak phrases — never use these
Every one of these has a stronger form. If a draft bullet contains one,
rewrite it before the resume can be marked ready.

| Never write | Because | Write instead |
|---|---|---|
| "Responsible for X" | Describes the job, not what you did | Lead with the verb: "Designed X," "Shipped X" |
| "Helped with / Assisted in" | Erases your actual contribution | Name your specific part: "Built the component library used by..." |
| "Worked on" | Says nothing | The verb that describes the actual work |
| "Participated in / Involved in" | Passive presence, not action | What you did in it |
| "Tasked with / Duties included" | Job-description language | Result language |
| "Successfully" | If it's on the resume, success is implied | Delete the word, keep the result |
| "Various / Multiple / Several" | Vague where a number should be | The actual number |
| "Utilized / Leveraged" | Inflated word for "used" | "Used," or better, a verb about the outcome |

### Strong verb bank (design/product roles)
Pick the verb that matches what actually happened — don't upgrade "built"
to "spearheaded" if you didn't lead it (hard-rules rule 5 applies to verbs
too):
- **Making:** designed, built, shipped, prototyped, created, developed
- **Improving:** redesigned, streamlined, reduced, increased, cut, lifted
- **Leading:** led, drove, owned, launched, established
- **Systems:** unified, standardized, automated, scaled, migrated
- **Evidence:** tested, validated, interviewed, measured, benchmarked

### Bullet formula — XYZ, outcome first
```
{Outcome X, with its number} + by + {what you did, Z}
```
Accomplished **X**, measured by **Y**, by doing **Z**. The number goes at the
front, because a recruiter skimming for six seconds should hit the result
before the verb. This matches the XYZ contract in `profile/proof-points.md`,
whose ready-made bullets are already written this way — draw from there rather
than re-deriving the wording.

- Weak: "Responsible for the design system used by teams across products"
- Better, but action first: "Built and maintained a 70+ component design system
  adopted across 4 live products"
- **Strong (XYZ):** "Raised ReQuesta session completion from **40% to 85%** by
  designing the AI output review, regeneration, and human oversight flows for an
  LLM powered assessment tool."

**When a bullet has no number, keep it verb-first.** Forcing XYZ onto a bullet
with no measurable outcome produces a vague opener ("Improved consistency
by...") that is weaker than a strong verb. Accessibility compliance,
stakeholder partnership, and documentation bullets legitimately stay verb-first.

Not every bullet has a number — but every role's top 2 bullets should, **and
those two are written XYZ**. Verb-first bullets sit below them, so the top third
of the page reads as outcomes and the supporting detail comes after.
If a real number exists in proof-points.md, it belongs in the bullet.

> **Reconciled 2026-08-26.** This section previously specified
> `{Strong verb} + {specific thing} + {quantified result}`, which put the metric
> last and contradicted the XYZ contract in `proof-points.md`. Resumes built
> earlier that day followed the verb-first version and buried their metrics at
> the end of three-line bullets. XYZ is now canonical in both files.

### Ordering within a role
1. The bullet most relevant to THIS job's JD
2. The bullet with the biggest number
3. Everything else by relevance

Never chronological-by-task, never "main duty first" — relevance first,
always.

### The read-aloud test
If a bullet would sound absurd said out loud in an interview ("I
successfully leveraged cross-functional synergies..."), it doesn't go on
the resume. Every line should survive being spoken.
