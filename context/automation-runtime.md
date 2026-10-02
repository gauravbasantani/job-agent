# Automation Runtime

Runtime rules for browser tabs, retries, account handoffs, Gmail assistance,
and remote commands. Read this with `context/hard-rules.md`; this file does not
relax any hard rule.

## Chrome ownership

- Automate only a profile on the allowlist in `scripts/chrome_tabs.mjs`:
  `the user` or `the user Automation`. Never attach to Your University, Work, Viresh, Guest,
  or an unverified profile.
- **Chrome 136+ refuses `--remote-debugging-port` on the default user-data-dir**
  (verified here on Chrome 150: the flag is accepted and no port opens). The
  everyday `the user` profile therefore cannot be driven over CDP. Automation
  runs as `the user Automation` in `~/.job-agent/chrome-profile`, started by
  `./scripts/chrome_bridge.sh start`.
- The automation profile is named distinctly on purpose. A second profile also
  called `the user` would satisfy the guard by impersonation.
- CDP is acceptable only when the runtime can verify the actual profile path
  against Chrome's profile metadata, and the path must be absolute — a relative
  path would resolve `Local State` against the working directory.
- Keep one controlled job window. Each distinct job gets one browser job key
  and one tab in that window.
- Persist only non-secret tab metadata: job key, target/tab ID, canonical URL,
  company, title, state, retry count, and last verification time.

## Tab state machine

`opened -> inspecting -> filling -> verifying -> awaiting_submit -> submitted`

Side states are `blocked_account`, `blocked_credentials`, `blocked_captcha`,
`blocked_unknown_field`, and `technical_failure`.

- A new job opens a new tab.
- Retry and `continue` always reuse the mapped tab.
- Before every fill/resume/submit, verify the page company/title or canonical
  requisition matches the browser job key.
- A technical navigation/timeout failure may retry twice with bounded backoff.
  Reload or navigate the same target; do not create a replacement tab.
- Form validation, account walls, credentials, OTPs, CAPTCHA, and unknown
  controls are not technical retry conditions.
- Default live-fill concurrency is three. Each job holds an exclusive tab,
  answer-map, and upload lock.

## Form inspection and filling

`scripts/ats_adapters.mjs` holds one reusable adapter per supported platform
(Greenhouse, Ashby, Lever, Workday, iCIMS, ADP, SmartRecruiters, LinkedIn Easy
Apply) plus all field-classification and verification logic. It is pure and
unit-tested, so the safety decisions do not depend on a live page.
`scripts/ats_fill.mjs` is the CDP driver: it reuses the same the user-only
profile guard, attaches only to the tab already mapped to the job key, and
refuses to open a replacement tab. See `agents/04-application.md` for the
command sequence and the rules the engine enforces.

## Gmail-assisted handoff

A Gmail connector may be available to the agent session (it is an MCP tool, not
a repository dependency — no OAuth token is ever stored here). When one is
connected it is used for exactly one purpose: confirming that a verification
message *arrived*. It is never used to read a code, open a body, or follow a
link. When no connector is available, everything below still works; the agent
just reports the search query instead of running it.

The user creates accounts, enters passwords and one-time codes, follows
magic-login links, and completes CAPTCHA. The agent keeps the application tab
mapped and resumes only after `continue {job}`.

`scripts/verification_handoff.py` makes the pause durable:

```
python3 scripts/verification_handoff.py open --job {job} --type otp --url {url}
python3 scripts/verification_handoff.py list --pending
python3 scripts/verification_handoff.py gmail-query --job {job}
python3 scripts/verification_handoff.py record-email --job {job} --payload-json '{...}'
python3 scripts/verification_handoff.py resolve --job {job}
```

`gmail-query` returns a narrow search (recent, sender- or company-scoped) plus
the required view mode. **Call the connector with
`view=THREAD_VIEW_METADATA_ONLY`.** The default view returns snippets, and a
verification email's snippet routinely contains the code itself — reading it
would break the guarantee even if the code were never written down.

Pipe the connector's response to `record-email`. That command rebuilds the
record from an allowlist of non-content fields (sender address, timestamp,
thread id, labels) and discards everything else, so a subject, snippet or body
cannot reach disk even if the call was made in the wrong mode. A code smuggled
into a sender display name is dropped too — only the address survives. An empty
result is an error, never a false confirmation.

Finding the email does not clear the blocker. It upgrades "go look" into "it
arrived at 17:31 from no-reply@ashbyhq.com"; the user still types the code and
still sends `continue {job}`. Opening the same blocker repeatedly, and
resolving twice, are both no-ops.

## Phone and asynchronous commands

Slack is the preferred phone interface. `scripts/slack_intake.mjs` listens with
Slack Socket Mode, accepts `/jobagent ...` slash commands or direct messages to
the bot, checks `JOB_AGENT_SLACK_ALLOWED_USERS`, and enqueues only supported
verbs. After a successful enqueue it starts one matching drain cycle through
`scripts/queue_dispatch.sh`; the drain worker, not Slack intake, handles
Chrome, resumes, and applications. Terminal results are posted back to Slack
from the queue notification metadata.

```
node scripts/slack_intake.mjs setup
./scripts/slack_daemon.sh arm
/jobagent apply https://...
/jobagent status #12
```

To route work to one local LLM, put the label at the end of the command:

```
/jobagent apply https://... worker:claude
/jobagent check https://... worker:codex
```

Unlabeled commands are claimed by the Claude drain. `scripts/codex_drain.sh`
claims only `worker:codex` or `:codex` items. Slack starts only the matching
worker for the new queue item. Do not run both workers through live form
filling at the same time unless the browser job keys and tabs are separate.
Codex away-mode runs with local Chrome/CDP access by default so queued live
application fills can reach the `the user Automation` browser on port 9222.
Claude/default runs a Chrome/CDP preflight before starting `/drain`; broad
Claude permission bypass is available only when explicitly opted in with
`JOB_AGENT_CLAUDE_PERMISSION_MODE=bypassPermissions`. These settings change
OS/browser access only; hard application rules still apply inside each worker:
no credentials, OTP, CAPTCHA, account creation, payment/government ID, or final
submit without explicit confirmation.

The same command text also works from the local agent conversation with
commands such as `check {url}`, `apply {url}`, `continue {job}`, and
`submit {job}`.

`scripts/command_queue.py` accepts those commands asynchronously:

```
python3 scripts/command_queue.py enqueue "apply https://..." --idempotency-key phone-001
python3 scripts/command_queue.py list --status pending
python3 scripts/command_queue.py claim --worker mac-session
python3 scripts/command_queue.py complete --id 3 --result "prepared, awaiting submit"
```

`scripts/gmail_intake.py` is the phone transport: the user emails himself with
the command in the **subject line** prefixed `JOBAGENT:`, and intake enqueues
it. Subject lines only, sender allowlisted to his own address, verb allowlisted,
idempotent by Gmail message id. `/drain` runs one intake+execute cycle; put it
on `/loop 10m /drain`. Gmail is now the fallback transport; Slack is faster
because it enqueues immediately. Full runbook in `context/mobile-workflow.md`.

Every item carries an idempotency key — explicit, or derived from the
normalized command text — so a phone retrying on a flaky connection enqueues
once. Claim/complete/fail/release transitions are append-only audited, and
finishing an already-terminal item never overwrites the first outcome.

**Enqueuing is not authorization.** A queued `submit {job}` is intent to
submit; the confirmation gate in `context/hard-rules.md` rule 1 still applies
when the agent drains it.

**A remote trigger can enqueue work, but it cannot run Chrome.** Local browser
automation requires the Mac awake, the `the user` Chrome profile open, and the
CDP bridge listening. A command sent from a phone while the Mac is asleep stays
`pending` until an agent session drains the queue — that is the intended
behavior, not a failure.

A published Workspace Agent API channel can later accept asynchronous intake.
Use a stable conversation key per job and an idempotency key per phone event.
Treat HTTP 202 as queued, not completed: that API does not currently return a
run ID or retrievable response, so keep results in the agent conversation or a
separate local status surface. Never expose the local browser bridge directly
to the public internet and never put access tokens in prompts, files, or logs.

## Audit record

Record state transitions, not secrets. Each event includes timestamp, job key,
canonical URL, action, result, retry count, and a screenshot/DOM artifact path
when relevant. Never log passwords, OTPs, cookies, authorization headers,
government IDs, or full Gmail message bodies.

Audit trails live in `.job-agent/` (gitignored) and are written by the scripts
themselves: `browser-audit.jsonl` (tab lifecycle), `fill-audit.jsonl` (form
inspection and filling — field categories and lengths, never values),
`verification-audit.jsonl`, and `command-audit.jsonl`.
