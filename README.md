# Job Agent

A file-based system for running a job search with an AI coding agent
(Claude Code, Codex, or anything that can read a repo and run scripts).

It finds postings, scores them honestly against your actual experience, tailors
a resume to the specific job description, drafts the screening answers, and
tracks every application. **A human confirms before anything is submitted.**

Point your agent at `AGENTS.md` and it will know what to do.

---

## Why this exists

Most AI resume tools generate plausible text. The problem is not generating
text, it is that plausible text contains claims you cannot defend in an
interview, and you will not notice until you are in one.

So the design is built around three ideas:

**Your evidence is a file, not a prompt.** Every claim comes from
`profile/proof-points.md`, which you write once, with defensibility ratings and
an explicit list of things you must never claim. The agent cannot invent a
number it was not given.

**Scores are checked by a script, not by a model.** `scripts/score_guard.py`
validates every job score across seven dimensions and **refuses to let four of
them improve through tailoring.** Your years of experience, the domain, your
work authorization and how fresh the posting is are facts. Rewriting a resume
does not change them, and a model left unsupervised will quietly raise them.

**The agent reads as little as possible.** Each task loads only the files it
needs. A generated `TRACKER.md` answers status questions without opening any
application folder.

---

## What it does

| | |
|---|---|
| **Find** | Searches ATS boards (Greenhouse, Ashby, Lever), company sites, job boards |
| **Score** | Seven dimensions, 100 points, with four locked against tailoring |
| **Tailor** | Rewrites a resume for one posting, from your evidence file only |
| **Answer** | Drafts screening questions, cover letters, salary answers |
| **Track** | Every application in one generated table |
| **Stop** | Never submits. That gate is deliberate and it is a hard rule |

---

## Getting started

```bash
git clone <your fork>
cd job-agent-template
./scripts/run_tests.sh      # should pass on a clean machine
```

Then **read [`SETUP.md`](SETUP.md)**. It walks through the four files that make
this yours, with examples of weak versus strong input. About an hour.

Open the folder in your agent and say:

```
Read AGENTS.md, then help me apply to <posting URL>
```

---

## Layout

```
AGENTS.md              entry point. Your agent reads this first
SETUP.md               how to make it yours
context/               the rules: hard rules, writing voice, resume standards,
                       cover letter guidelines
agents/                one file per job: discovery, matching, tailoring,
                       application, tracker, cover letter
scripts/               deterministic tooling. Python and Node, no frameworks
tests/                 unittest and node --test
profile/               YOUR DATA. gitignored
applications/          one folder per job. gitignored
```

---

## Requirements

- Python 3 and Node, both standard library only. **No third-party packages.**
- An AI coding agent that can read files and run shell commands
- macOS if you want Word-based PDF export. Everything else is cross-platform

---

## What this is not

- **Not an auto-applier.** It stops before submission, every time, whatever the
  match score. Keep that rule.
- **Not a resume writer that works without input.** Thin evidence file, thin
  resumes.
- **Not a way to claim things you have not done.** The structure is actively
  built to prevent that, which is the point.

---

## License

MIT. Fork it, change the rules, make it yours.

If you improve the scoring rubric or add an ATS adapter, a pull request is
welcome.
