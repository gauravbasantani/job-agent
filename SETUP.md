# Setup: make this yours

Four files decide everything. Fill them in and the system works for you instead
of for somebody else. Budget about an hour, and do them in this order.

Anywhere you see **`CHANGE THIS`**, it is waiting for you.

---

## 1. `profile/personal-info.md` — 15 minutes

Copy the template and fill it in:

```bash
cp profile/personal-info.template.md profile/personal-info.md
```

This file is gitignored. It never leaves your machine.

It answers the questions application forms ask over and over, so you only decide
once. The ones that matter most:

```markdown
## Contact
- Name: CHANGE THIS
- Email: CHANGE THIS          # one address, used on every application
- Phone: CHANGE THIS
- Location: CHANGE THIS
- Portfolio: CHANGE THIS
- LinkedIn: CHANGE THIS
- GitHub: CHANGE THIS

## Work Authorization
- Status: CHANGE THIS                 # e.g. US citizen, green card, F-1 OPT, H-1B
- Sponsorship needed in the future: CHANGE THIS
- **ATS answer mapping:** write the exact wording you will use when a form asks
  "do you now or will you in the future require sponsorship". Decide it once,
  sober, and never improvise it at 1am.

## Compensation
- Salary floor: CHANGE THIS           # the number you will not go below
- Salary target: CHANGE THIS
- Note: when a posting lists its own range, evaluate against that range rather
  than quoting your floor reflexively.

## Demographic and EEO answers
- Gender / Race / Veteran / Disability / Pronouns: CHANGE THIS
```

**Why the EEO section exists.** Forms ask these constantly. Recording your real
answers once means the agent fills them correctly instead of guessing, and
guessing from a name is exactly the failure to avoid. If you would rather
decline, write "prefer not to say" and it will use that every time.

---

## 2. `profile/proof-points.md` — 30 minutes, and the one that matters

```bash
cp profile/proof-points.template.md profile/proof-points.md
```

This is your evidence library. Every resume bullet the system writes comes from
here, so vague input produces vague output.

For each job and project, write:

```markdown
## Company Name — Your Title, Month Year to Month Year

### Metrics
| Metric | Defensibility | Notes |
|---|---|---|
| CHANGE THIS | Strong / Moderate / Weak | how you would defend it in an interview |

### Ready bullets
> CHANGE THIS. One sentence. What you did, how, and the number.

### Trigger signals
Words in a job description that should pull this story in.
```

**A worked example of the difference:**

> **Weak:** "Improved the checkout experience and increased conversions."
>
> **Strong:** "Increased purchase completion by 30% by redesigning search, cart
> and checkout across web and mobile, decided on A/B tests run on live traffic
> rather than on opinion."

The second one survives the question "how do you know?"

### Two sections people skip and then regret

**"What I do NOT have."** List the things you must never claim. Native mobile at
production scale, managing people, a domain you have only read about. The system
reads this and refuses to drift into them. It is the single highest-value part
of the file.

**Defensibility ratings.** Mark anything shared with a team as Moderate and say
so in the bullet. A number you cannot defend is worse than no number, because it
collapses in the interview rather than on the page.

---

## 3. `context/writing-style.md` — 10 minutes

The template describes a plain, direct voice. **Read it and change anything that
is not you.** If you write more formally, say so. If you use em dashes, remove
that rule.

The parts worth keeping whatever your style:

- **Do not announce the structure of your own message.** "Here is a quick
  summary of why I fit" is the clearest tell that a model wrote it. A person
  just says the thing.
- Keep a banned-phrase list and add to it whenever you catch yourself repeating
  something. Reused phrasing across applications is itself a signal of
  automation.

---

## 4. Your resumes — 5 minutes

Put your existing resumes here:

```
profile/resumes-md/      plain markdown, this is what the agent reads
profile/resumes-docx/    the real files, used only for final output
profile/resumes-pdf/
```

Keep two or three variants if you have them. The system picks whichever fits a
posting best. **The markdown versions are what get read**, so the docx is only
opened when a final file is generated. That is deliberate and it is why this is
cheap to run.

---

## 5. Check it before you trust it

```bash
./scripts/run_tests.sh          # everything should pass
python3 scripts/build_tracker.py # builds TRACKER.md from applications/
```

Then try one real posting end to end and read what it produces **before** you
send anything. You are looking for claims you cannot defend. If you find one,
the fix belongs in `proof-points.md`, not in the output.

---

## What is private, and how

`.gitignore` already excludes `profile/`, `applications/` and `TRACKER.md`. If
you fork this and push, check before the first commit:

```bash
git add -A
git diff --cached --name-only    # read this list carefully
```

Nothing personal should appear. If it does, fix `.gitignore` before committing,
not after, because secrets and PII persist in git history even after deletion.

---

## Honest expectations

- **It will not write a good resume from a thin `proof-points.md`.** The quality
  ceiling is set by what you put in.
- **It cannot verify your claims.** It only knows what you told it. The
  "what I do NOT have" section is the only brake.
- **Read everything before it goes out.** Scripts report success on output that
  is wrong. Render the PDF and look at it.
- **A human confirms every submission.** That is a hard rule in
  `context/hard-rules.md` and you should keep it.
