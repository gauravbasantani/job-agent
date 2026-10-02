# Contributing

The useful contributions, roughly in order:

**ATS adapters.** `scripts/ats_adapters.mjs` handles Greenhouse, Ashby, Lever
and Workday. Adding iCIMS, SmartRecruiters, Taleo or BambooHR would help a lot
of people. Each adapter detects its platform and classifies the form fields;
look at an existing one first.

**The scoring rubric.** The seven dimensions in `agents/02-matching.md` are a
starting point, not received wisdom. If you have a better split, open an issue
with the reasoning.

**Non-macOS PDF export.** Final files are currently produced through Word via
AppleScript. A LibreOffice or Pandoc path would make this work on Linux and
Windows.

**Writing rules.** `context/writing-style.md` and
`context/cover-letter-guidelines.md` encode one person's voice and some
research on what reads as machine-written. Corrections welcome, especially from
people who read applications for a living.

## Ground rules

- **No dependencies.** Python standard library and Node standard library only.
  This runs against your personal data; the dependency tree should be empty.
- **Tests for anything in `scripts/`.** `./scripts/run_tests.sh` must pass.
- **Never weaken the submit boundary.** A pull request that adds auto-submission
  will be closed.
- **No personal data in commits.** `profile/` and `applications/` are gitignored
  for a reason.
