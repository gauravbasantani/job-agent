# Mobile Workflow

How the user queues job applications from a phone while the Mac does the work.
Read with `context/automation-runtime.md` and `context/hard-rules.md`.

## The constraint, stated plainly

A phone cannot drive Chrome. Form filling happens over CDP against a local
Chrome, and `profile/` and `applications/` live on local disk. A cloud agent
has none of that.

**The Mac must be awake, the Chrome bridge running, and an agent session
draining the queue.** A command sent while the Mac is asleep sits `pending`
until a session picks it up. That is correct behaviour, not a failure.

## Preferred transport: Slack

Slack is the primary phone channel. It uses Socket Mode, so the Mac opens an
outbound WebSocket to Slack and no public HTTP endpoint is exposed. Official
Slack references:

- Socket Mode: https://docs.slack.dev/apis/events-api/using-socket-mode/
- Slash commands: https://docs.slack.dev/interactivity/implementing-slash-commands/

Repository pieces:

| Piece | Purpose |
|---|---|
| `scripts/slack_intake.mjs` | Receives Slack slash commands or DMs, checks the Slack user allowlist, and enqueues commands |
| `scripts/slack_daemon.sh` | Keeps the Slack Socket Mode listener alive with launchd |
| `scripts/command_queue.py` | Shared local queue consumed by Claude/Codex drain sessions |
| `scripts/drain_daemon.sh` | Starts the Chrome bridge when needed and runs the expensive agent drain only when work is pending |

One-time Slack app setup:

1. Create a Slack app at https://api.slack.com/apps.
2. Enable Socket Mode.
3. Create an app-level token with `connections:write`.
4. Add bot scopes: `commands`, `chat:write`, `im:write`, `im:history`,
   `im:read`.
5. Create slash command `/jobagent`. In Socket Mode, no public Request URL is
   needed.
6. Under **App Home**, enable the **Messages Tab** and turn on **Allow users to
   send Slash commands and messages from the messages tab** if direct messages
   to the bot should work.
7. Subscribe to bot event `message.im` if direct messages to the bot should
   also queue commands.
8. Install or reinstall the app to the workspace.
9. Find the user's Slack user ID and allow only that user.

Create `~/.job-agent/slack.env` on the Mac:

```bash
export SLACK_APP_TOKEN=xapp-...
export SLACK_BOT_TOKEN=xoxb-...
export JOB_AGENT_SLACK_ALLOWED_USERS=U1234567890
```

Then lock it down:

```bash
chmod 600 ~/.job-agent/slack.env
```

Start Slack intake:

```bash
./scripts/slack_daemon.sh arm
```

Check status:

```bash
./scripts/slack_daemon.sh status
node scripts/slack_intake.mjs check-env
```

## Why automation uses its own Chrome profile

Since Chrome 136, `--remote-debugging-port` is refused on the default
user-data-dir. Verified on this machine at Chrome 150: Chrome accepts the flag
and silently listens on nothing. There is no flag combination around it.

The block is deliberate — CDP on a profile exposes that profile's cookies and
logged-in sessions to any local process. So automation runs as a separate
profile, `the user Automation`, in `~/.job-agent/chrome-profile`.

The name is distinct on purpose. A second profile also called `the user` would
pass the profile guard by impersonation and reduce the check to a formality.
`ALLOWED_PROFILE_NAMES` in `scripts/chrome_tabs.mjs` accepts `the user` and
`the user Automation` and nothing else — Your University, Work, Viresh and Guest stay
off-limits.

Logging in there is a **one-time** cost. Sessions persist like any Chrome
profile; they do not need re-entering each run.

## One-time setup

```bash
./scripts/chrome_bridge.sh start
```

In the window that opens, sign in to LinkedIn and any ATS platforms you use
(Greenhouse, Ashby, Lever, Workday, iCIMS, ADP, SmartRecruiters). Sign in to
nothing else — the blast radius of a CDP-exposed profile should stay limited to
job sites.

## Before leaving the laptop

```bash
./scripts/slack_daemon.sh arm         # phone -> queue
./scripts/drain_daemon.sh arm         # queue -> agent work, also keeps Mac awake
./scripts/chrome_bridge.sh start      # idempotent; verifies the profile
```

`drain_daemon.sh arm` runs `/drain` through Claude Code only when Slack/Gmail
intake or the local queue has pending work. In an interactive Claude session,
`/loop 10m /drain` is still fine for manual monitoring.

## From the phone with Slack

Use the slash command from any Slack client:

```
/jobagent check https://...
/jobagent apply https://...
/jobagent force tailor https://...
/jobagent continue eudia-product-designer
/jobagent submit eudia-product-designer
/jobagent find job_title:"Product Designer" jobboard:"workday" not_on_linkedin:true
/jobagent status
/jobagent status #12
```

Route a command to a specific local LLM by adding a worker label at the end:

```
/jobagent check https://... worker:claude
/jobagent check https://... worker:codex
/jobagent find Product Designer jobs :codex
```

Unlabeled commands are treated as Claude work because `drain_daemon.sh` runs
Claude Code. Codex work is handled only by `scripts/codex_drain.sh`.

Or DM the bot the same command without the slash prefix:

```
apply https://job-boards.greenhouse.io/acme/jobs/123
```

Slack immediately replies with a queue id, for example `Queued as #12`.
`/jobagent status #12` reads the local queue result. It never prints secrets;
the same redaction rules used by `command_queue.py` apply to Slack replies.

Sending from any Slack user not in `JOB_AGENT_SLACK_ALLOWED_USERS` is rejected.
Unsupported verbs are rejected before they reach the queue.

## Gmail fallback from the phone

Email yourself. Put `JOBAGENT:` in the subject — that is the gate — and write
the command as the **first line of the body**:

```
Subject:  JOBAGENT:
Body:     find Product Designer jobs from the past 24 hours and apply
          Best, the user
```

A command in the subject also works (`JOBAGENT: apply {url}`), and the body
wins when both carry one. Your signature is stripped automatically — `Best,`,
`Thanks,`, `Sent from my iPhone` and similar all terminate the command — and
quoted reply lines beginning with `>` are skipped.

| Command | Effect |
|---|---|
| `JOBAGENT: check {url}` | Duplicate/live/source check plus initial ATS score. Cheap — send it the moment a posting looks interesting |
| `JOBAGENT: apply {url}` | Full pipeline: dedupe, score, tailor, generate DOCX/PDF, fill the form, stop before submit |
| `JOBAGENT: force tailor {url}` | Tailor even when reuse was the normal call |
| `JOBAGENT: continue {job}` | Resume the mapped tab after clearing a human step |
| `JOBAGENT: submit {job}` | Confirmation for that one named job |
| `JOBAGENT: find job_title:"Product Designer" jobboard:"workday"` | Queued search |

Sending twice is safe. Intake is idempotent by Gmail message id, and the queue
is idempotent by command text, so retries on bad signal enqueue once.

## What makes this safe to point at a mailbox

`scripts/gmail_intake.py` applies three independent gates:

1. **Sender allowlist.** Only mail from the user's own address is considered.
   Anyone can email him; nobody else can queue work on his machine.
2. **Subject gate.** The subject must carry `JOBAGENT:`. A forwarded thread or
   a recruiter email whose body happens to contain a command does nothing,
   because the subject was never marked.
3. **Verb allowlist.** The command must start with a verb the agent already
   supports. Anything else is reported as rejected, never attempted.

All three must line up. Signature blocks and `>` quoted lines are stripped
before the command is read, so a reply chain cannot smuggle in an old
instruction.

## How the user knows anything happened

Slack confirms intake immediately because `slack_intake.mjs` writes directly
to the local queue. It also starts one matching worker cycle through
`scripts/queue_dispatch.sh`, so a Slack message begins work without waiting for
the next timer poll. `drain_daemon.sh arm` is still useful as a backup poller
and keep-awake layer.

When a queued command reaches `completed` or `failed`, the Slack listener posts
the terminal result back to the Slack DM/channel that created it. The result
uses the same redaction rules as the queue, so pasted passwords, OTPs, tokens,
SSNs, and card-shaped values are not echoed back.

Sending a Slack command does not wake a sleeping Mac. If the Mac is asleep or
the Slack listener is not running, the command waits or never arrives locally.

Slack status commands:

| Command | Meaning |
|---|---|
| `/jobagent status` | Queue totals |
| `/jobagent status #12` | Status/result for one queue item |

Codex away-mode worker:

```bash
./scripts/codex_drain.sh status
./scripts/codex_drain.sh loop
```

Slack now starts `./scripts/codex_drain.sh once` automatically for a new
Codex-routed item. Keeping `./scripts/codex_drain.sh loop` open in a Terminal
tab is optional backup. It claims only queue items assigned to Codex, so Claude
and Codex do not race for the same item.

Codex away-mode defaults to browser-capable local access because live
LinkedIn/ATS fills require Chrome/CDP on `localhost:9222`. Claude/default runs a
Chrome/CDP preflight before `/drain`; broad Claude permission bypass is only
enabled when `JOB_AGENT_CLAUDE_PERMISSION_MODE=bypassPermissions` is explicitly
set. The workers still must stop at every hard-rule boundary: no credentials,
OTP, CAPTCHA, account creation, payment/government ID, or final submit without
the user's confirmation.

Optional Slack flags in `~/.job-agent/slack.env`:

```bash
export JOB_AGENT_SLACK_AUTORUN=0          # queue only; do not start workers
export JOB_AGENT_SLACK_NOTIFY_RESULTS=0   # do not post terminal results
```

Gmail feedback still works for Gmail intake:

Feedback comes back as **Gmail labels on his own message**, because the Gmail
connector can create drafts but cannot send mail. A label appears on his phone
within seconds and needs no app, no notification setup, and no reply:

| Label | Meaning |
|---|---|
| `JobAgent/Queued` (blue) | Received and queued |
| `JobAgent/Done` (green) | Finished |
| `JobAgent/Blocked` (orange) | Needs him — account, login, OTP, CAPTCHA, or ready and awaiting submit |
| `JobAgent/Rejected` (red) | Refused — wrong sender, unknown verb, dead URL |

Searching `label:JobAgent/Blocked` in Gmail shows everything waiting on him.

`PushNotification` is also used when Claude Code Remote Control is connected,
but labels are the channel that works unconditionally.

## Portal accounts (iCIMS, Workday, ADP, SmartRecruiters)

These platforms usually require a candidate account. The agent does not create
one and does not type a password — `context/hard-rules.md` rules 2 and 3, which
hold even when the user explicitly authorizes it. No credential is ever stored in
this repo, in `.job-agent/`, in the queue, or in a log.

That costs nothing operationally, because **the login is a one-time step**:

1. `./scripts/chrome_bridge.sh start`
2. In that window, create the account or sign in yourself — once per platform.
3. The session persists in `~/.job-agent/chrome-profile` like any Chrome
   profile. Later runs reuse it; nothing asks again for months.

Use a password manager and a unique password per portal. If a run hits a login
wall anyway (session expired, new platform), the job pauses with a
`verification_handoff` record and the tab stays mapped for `continue {job}`.

If a credential is ever pasted into a Slack message or an email command, the
redaction in `command_queue.py` and `slack_intake.mjs` strips it before it
reaches the queue, the audit log, or a Slack reply — but treat any password
that touched a chat as compromised and rotate it.

## What still waits for a human

- **Account creation, login, OTP, emailed verification, CAPTCHA.** The tab is
  on the Mac, so these cannot be cleared from a phone. The job pauses with a
  handoff record and the tab stays mapped for `continue {job}`.
- **Final submit.** A queued `submit {job}` *is* explicit confirmation for that
  named job and satisfies `hard-rules.md` rule 1. But the agent re-verifies the
  packet first: if the prepared documents or the live form changed since the
  command was queued, it reports the difference and leaves the job pending
  rather than clicking on a stale approval.

## The realistic pattern

Prepare while away, submit when back. Queue three to five `apply` commands from
wherever you are; they are filled and waiting when you open the laptop. The two
failure modes worth a human eye — a form quirk and a PDF that looks wrong — are
both caught in ten seconds of looking, and neither is visible from a phone.
