# Kickoff prompt for a new session

Paste the block below into a fresh Claude Code session in this repo. It is
deliberately short: everything else lives in the repo files it points at, which
is the whole token strategy.

---

```
Read AGENTS.md first, then context/hard-rules.md.

Before you claim anything about me, read profile/profile-for-agents.md. Its
"Never claim" list overrides every other file and every older resume-used.md.
Do not copy a bullet from a previous application folder without checking it
against that list, because most of the older folders contain claims that are
now forbidden.

On every new resume or cover letter:
- Portfolio link is yourname.example.com
- Email is you@example.com
- Metrics come from profile/proof-points.md as corrected, never from an older
  resume-used.md
- ReQuesta has no completion metric. YourSideProject was directed, not built solo.
  The Your University design system was grown, not built from zero. Do not mention the AI
  job-search agent system at all.

How I work:
- A bare URL means: fetch it, dedupe against TRACKER.md, score it with the
  7-dimension rubric through scripts/score_guard.py, and write application.md
  plus score-breakdown.json. Do not build anything yet.
- "do it" / "make it" / "build" means build the resume: 1 page, 95 to 99% fill,
  verified with scripts/verify_resume_pdf.py. Render the PDF and read it back.
- "applied" means mark it Applied in the record, rebuild the tracker, and let
  the DOCX and PDF be pruned. Keep the .md files.
- Write a cover letter whenever the form has a field. Read
  context/cover-letter-guidelines.md first, every time.
- Decide, do not ask. Take the defensible default and tell me the assumption at
  the end so I can correct it in one pass.

Verify your own output before you report it. Logs lie here. A fill script once
reported success while having picked the wrong gender; a page-count check
passed on a resume that was two-thirds empty. Flatten PDF text with
tr '\n' ' ' before grepping it, because line wrapping has caused false alarms.

Tell me plainly when something failed or when you are not sure. I would rather
have a short honest answer than a confident wrong one.
```

---

## Things worth adding to the paste, depending on the session

**If you are chasing job statuses:**
```
Gmail is connected. Use scripts/email_status_update.py to turn what you find
into tracker updates. Dry run first, then --apply, then build_tracker.py. Use
--folder, not --company, when a company has several open roles.
```

**If you want discovery rather than a specific URL:**
```
Do not guess company board slugs from memory, it caps coverage at whatever you
remember. Use search to discover boards across the index, then hit the Ashby,
Greenhouse and Lever APIs to verify. Greenhouse updated_at is a last-modified
stamp, not a post date; the real field is first_published via ?content=true.
Ashby publishedAt and Lever createdAt are real post dates. US only.
```

**If you are handing work to another agent (Codex and so on):**
```
AGENTS.md is written for any agent, not just Claude. Point it at
profile/profile-for-agents.md and context/cover-letter-guidelines.md before it
writes anything.
```

---

# Kickoff prompt for an INTERVIEW session

Use this when the new chat is for interview prep and the applying continues
elsewhere.

```
I have an interview coming up. Read these three files before anything else:

1. applications/<the-job-folder>/interview-prep.md
   (the role, the stages, the questions and my drafted answers)
2. profile/profile-for-agents.md
   (source of truth for every claim about me. Its "Never claim" list overrides
   everything. In particular: ReQuesta has no completion metric, YourSideProject was
   directed not built solo, the Your University design system was grown not built from
   zero, and the AI job-search agent system is not published so never mention
   it)
3. context/writing-style.md
   (how I talk. Plain words, contractions, no em dashes, no AI tone, no
   announcing the structure of my own answer before I say it)

Help me rehearse. Ask me a question, let me answer, then tell me what actually
landed and what sounded rehearsed. Be blunt. I would rather hear it from you
than from them.

Two rules for anything you draft for me:
- It has to be true. If a story needs a number I do not have, say so instead of
  rounding one up.
- It has to sound like me saying it out loud, not like something written down.
  Read it aloud in your head first. If I would not say it to a person across a
  table, rewrite it.
```

## Add to the paste depending on the stage

**HireVue, one-way video:**
```
This is the recorded-video screening stage: recorded video, about 5 minutes, no technical
questions. Expect "tell us about yourself", "why this company", "a project you are
proud of", "what skills do you bring". Keep each answer to 60 to 90 seconds.
```

**UX manager call:**
```
This is the 45 minute UX manager call. Casual, no screen share, no portfolio
walkthrough, so it is talking rather than presenting. About 25 minutes on past
experience, then my questions. Help me get three stories to two minutes each:
ReQuesta, Company B, and one where I got it wrong.
```

**Final round, behavioural:**
```
This is the behavioural final. Prepare me for: a conflict, a failure, a time I
changed my mind on evidence, and a difficult colleague. My real failure story
is the Company B redesign that came out cleaner and tested worse, because people
were reading by position rather than by label and I had moved everything.
```
