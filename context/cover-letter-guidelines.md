# Cover Letter Guidelines

For any agent writing a cover letter for the user (Claude Code, Codex, anything
else). Read this and `context/writing-style.md` together. Writing style covers
tone everywhere; this file covers what a cover letter specifically has to do,
what it must never repeat, and how to build the file.

---

## 1. The problem this file exists to fix

On 2026-09-29 the user said the letters had started sounding like AI. He was
right, and it is measurable. Across the 114 cover letters in `applications/`:

| Line | Times reused |
|---|---|
| "Thank you for reading." | **16** |
| "The most recent thing I designed, built and shipped by myself is live at..." | **13** |
| "My resume has the outcomes on it, so I want this page for..." (all variants) | **5** |
| "One thing you should know now rather than later." | **4** |

A phrase that appears in 13 letters is not voice. It is a template, and any
recruiter who sees two of his applications sees it instantly.

**"My resume has the outcomes on it, so I want to use this page for the one
thing it cannot show"** is the worst of them. It is a throat-clear that
announces the structure of the letter before saying anything, which
`writing-style.md` already bans. Delete it on sight.

---

## 2. Banned. Do not write these, in any rewording

**Openers**
- "My resume has the outcomes on it, so I want this page for..." and every
  variant of it
- "I am writing to express my interest in..."
- "I am excited to apply for..."
- "I am reaching out regarding..."
- Any sentence that describes what the letter is about to do

**Closers**
- "Thank you for reading." Use something else, or nothing.
- "The most recent thing I designed, built and shipped by myself is live at
  yourproject.example.com." The links belong in the letter, but write the line
  fresh each time.
- "I would welcome the opportunity to..."

**Words that read as machine-written** (on top of the list in
`writing-style.md`): delve, passionate, showcasing, pivotal, tapestry,
transformative, leverage, utilize, proven track record, results-oriented,
detail-oriented, synergy, unwavering, robust, seamless, spearheaded.

**Structures**
- Announcing a section before writing it
- Triplet lists written for rhythm
- A polished aphorism as the last line of a paragraph
- Three fragments in a row for effect
- Perfectly even sentence length. Real writing varies.

---

## 3. What the research says (checked 2026-09-29)

- **Average preferred length is about 400 words.** 70% of employers want half
  a page or less. the user's letters have been running 450 to 500. Aim for
  **380 to 450**.
- **60% of hiring managers spend two minutes or less** on a cover letter.
- **41% say the introduction leaves the biggest impression.** The first two
  sentences carry most of the value.
- **72% say customization matters**, and it matters roughly twice as much at
  medium and large companies.
- Recruiters in 2026 actively screen for AI phrasing. "Delve" alone is treated
  as a marker.

Practical reading: one page, four paragraphs, and the argument has to land in
the first three lines because that may be all that gets read.

---

## 4. What a cover letter actually has to do

Four jobs, in order. If a paragraph does none of these, cut it.

1. **Say who he is and what he is applying for**, in one sentence, without
   ceremony.
2. **Show he understood their problem**, not their company description.
   Anyone can restate a job posting. The letter earns its place by saying
   something about the work that they did not say first.
3. **Back it with one real thing he did**, including the part that went wrong.
   A story with a failure in it cannot be generated from a job posting, which
   is exactly why it reads as human.
4. **Name one honest limit.** This is the most effective paragraph he writes.
   It is not modesty, it is credibility. It proves the rest was not inflated.
   Keep it to two or three sentences and never apologise for it.

The resume already carries the metrics. The letter carries the thinking.
**Do not say that out loud in the letter.** Just do it.

---

## 5. Structure that works

Four body paragraphs. Roughly:

1. **Who and what**, one or two sentences. Then go straight into the idea.
   No preamble between them.
2. **The insight.** Something specific and slightly contrarian about their
   problem. Best ones so far: dense screens do not need less on them, they
   need the same thing in the same place (a dense financial terminal); a consent
   screen is the one screen where the honest goal is not a click (an identity
   product); in a tool used eight hours a day the risk is the fast person, not
   the careless one (a data-labelling tool).
3. **The evidence.** One story, told properly, with the mistake in it. His
   real ones: the validator that flattered itself at 91% when the truth was
   72%; the ReQuesta redesign where static mocks could not answer the
   question so he built it in React; the Company B pass that came out cleaner
   and tested worse.
4. **The honest limit**, then the links.

**One idea per letter.** The weak letters try to cover everything he has done.
The strong ones make a single argument and let the resume hold the rest.

---

## 6. Voice

- Contractions. "weren't", "cannot tell", "I'd rather". A letter with zero
  contractions in 400 words reads as generated. This has been flagged before.
- Vary sentence length. Some short. Some that run longer because the thought
  needs the room.
- Plain words. "I write it in React and find out", not "I leverage rapid
  prototyping methodologies".
- No hyphens or em dashes anywhere. Rephrase.
- **Read it aloud.** If the user would not say the sentence to a person across
  a table, rewrite it.
- It is fine to be direct about a mistake. "It was not broken. It was doing
  what I asked, and what I had asked for was wrong" is the tone.

---

## 7. What goes in every letter regardless

- Applying for the specific role, named.
- One number that matters, not five.
- The portfolio link and the live product link, written fresh.
- Nothing from the resume summary. **No Sun Awards, no ice cream, no travel,
  no degree list.** Those belong on the resume. The letter is one argument.

---

## 8. Build mechanics

`scripts/build_cover_letter_docx.py` is strict. Get these wrong and the build
still reports success while the output is broken.

- **One unwrapped line per paragraph** in the markdown. Hard-wrapped text
  produced 28 body paragraphs instead of 6 on the JPMC build and the script
  said it worked.
- **Fixed four-line header**, exactly:
  ```
  Your Name
  Your City
  you@example.com | (555) 123-4567
  Portfolio | LinkedIn
  ```
- **The last three non-empty lines** are parsed as portfolio line, thanks
  line, sign-off. Everything between the header and those three is body.
- **The template has five body slots.** Fewer than five is now safe (fixed
  2026-09-28); before that fix the unused slot silently kept the base letter's
  text about utility customers and energy use, and shipped it.
- **Four body paragraphs at 380 to 450 words fits one page.** Five paragraphs
  usually overflows because each paragraph gap costs a line. If it runs to two
  pages, merge two paragraphs before cutting content.
- Target fill is **88 to 94%** for a cover letter. `verify_resume_pdf.py`
  prints `SHORT` below 95% because it is calibrated for resumes. For a cover
  letter, SHORT on one page is correct. **Only `pages=1` matters.**
- Export through a folder Word already has permission for, then move the PDF
  back. `applications/2026-09-20-metriport-design-engineer/` works. Exporting
  into a fresh folder hits a macOS "Grant File Access" dialog that AppleScript
  cannot answer, and the build fails silently.

---

## 9. Before handing it over, run this

```bash
D=applications/<folder>
# 1. Page count. Only pages=1 matters; SHORT is fine for a cover letter.
python3 scripts/verify_resume_pdf.py $D/*Cover*.pdf

# 2. Did I reuse a line from any earlier letter? Pick 5 or 6 distinctive
#    phrases from the new letter and check each one. Every count must be 0.
for p in "<phrase 1>" "<phrase 2>" "<phrase 3>"; do
  echo "$(grep -rl "$p" applications/*/cover-letter*.md | grep -v "$D" | wc -l)  $p"
done

# 3. Banned strings and the stray template paragraph.
pdftotext $D/*Cover*.pdf - | grep -ciE "delve|passionate|leverage|utilize|proven track record|thank you for reading|resume has the outcomes"
pdftotext $D/*Cover*.pdf - | grep -c "utility customers"

# 4. Em dashes and the phone number.
pdftotext $D/*Cover*.pdf - | grep -c $'\xe2\x80\x94'   # em dash
pdftotext $D/*Cover*.pdf - | grep -oE "\(?[0-9]{3}\)?[ -][0-9]{3}-[0-9]{4}"   # your phone

# 5. Contractions. Should not be 0.
pdftotext $D/*Cover*.pdf - | grep -coE "n't|'re|'ll|'ve|I'm|I'd"
```

**Grep across line breaks.** PDF text wraps, so "Sun Awards" can come back as
a miss when the words sit on two lines. Flatten first:
`pdftotext file.pdf - | tr '\n' ' '`. Two false alarms have already been
raised this way.

---

## 10. One more thing

Every letter should contain at least one sentence that could not appear in
any other letter the user sends. If you cannot point to that sentence, the
letter is not finished.
