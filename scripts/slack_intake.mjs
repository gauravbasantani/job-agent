#!/usr/bin/env node
/*
 * Slack Socket Mode intake for Job Agent commands.
 *
 * This script is intentionally only a doorbell. It accepts a Slack command,
 * authenticates the Slack user against an allowlist, and enqueues the text in
 * scripts/command_queue.py. It does not run Chrome, read resumes, or submit
 * applications.
 *
 * Required environment for `start`:
 *   SLACK_APP_TOKEN=xapp-...                 app-level token, connections:write
 *   SLACK_BOT_TOKEN=xoxb-...                 bot token, commands/chat:write/im:write/im:history
 *   JOB_AGENT_SLACK_ALLOWED_USERS=U123,U456  Slack user id allowlist
 *
 * Common commands:
 *   node scripts/slack_intake.mjs setup
 *   node scripts/slack_intake.mjs check-env
 *   node scripts/slack_intake.mjs start
 *   node scripts/slack_intake.mjs enqueue --user U123 --team T123 --channel D123 "check https://..."
 */

import { spawn, spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");
const DEFAULT_QUEUE = path.join(REPO_ROOT, ".job-agent", "command-queue.json");
const DEFAULT_AUDIT = path.join(REPO_ROOT, ".job-agent", "command-audit.jsonl");
const DEFAULT_SLASH_COMMAND = "/jobagent";
const DEFAULT_DISPATCH_SCRIPT = path.join(REPO_ROOT, "scripts", "queue_dispatch.sh");
const SLACK_API = "https://slack.com/api";

const ALLOWED_COMMANDS = /^(check|apply|force\s+tailor|continue|submit|find|search)\b/i;
const LOCAL_HELPERS = /^(help|status|queue)\b/i;

const SECRET_PATTERNS = [
  /\b(?:password|passcode|otp|pin|token|secret|api[_-]?key)\b\s*[:=]?\s*\S+/gi,
  /\b(?:code)\b\s*[:=]\s*\S+/gi,
  /https?:\/\/\S*(?:token|magic|auth|verify|reset)=\S*/gi,
  /\b\d{3}[- ]?\d{2}[- ]?\d{4}\b/g,
  /\b(?:\d[ -]?){13,19}\b/g,
];

function splitList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function enabled(value, defaultValue = true) {
  if (value === undefined || value === null || value === "") return defaultValue;
  return !/^(0|false|no|off)$/i.test(String(value).trim());
}

export function redact(text, limit = 2000) {
  let value = String(text || "");
  for (const pattern of SECRET_PATTERNS) {
    value = value.replace(pattern, "[redacted]");
  }
  return value.trim().slice(0, limit);
}

export function unwrapSlackLinks(text) {
  return String(text || "")
    .replace(/<((?:https?|mailto):[^>|]+)(?:\|[^>]+)?>/g, "$1")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

export function normalizeCommandText(text) {
  return unwrapSlackLinks(text)
    .replace(/^\s*JOBAGENT\s*:?\s*/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function deriveSlackIdempotencyKey(input) {
  const stableId = input.eventId || input.triggerId || input.messageTs || "";
  if (stableId) {
    return `slack:${input.team || "team"}:${stableId}`;
  }
  const digest = crypto
    .createHash("sha256")
    .update(`${input.team || ""}\n${input.channel || ""}\n${input.user || ""}\n${normalizeCommandText(input.text)}`)
    .digest("hex")
    .slice(0, 16);
  return `slack:${digest}`;
}

export function configFromEnv(env = process.env) {
  return {
    appToken: env.SLACK_APP_TOKEN || env.SLACK_APP_LEVEL_TOKEN || "",
    botToken: env.SLACK_BOT_TOKEN || "",
    slashCommand: env.JOB_AGENT_SLACK_COMMAND || DEFAULT_SLASH_COMMAND,
    allowedUsers: splitList(env.JOB_AGENT_SLACK_ALLOWED_USERS),
    allowedTeams: splitList(env.JOB_AGENT_SLACK_ALLOWED_TEAMS),
    allowedChannels: splitList(env.JOB_AGENT_SLACK_ALLOWED_CHANNELS),
    queueFile: env.JOB_AGENT_QUEUE_FILE || DEFAULT_QUEUE,
    auditFile: env.JOB_AGENT_AUDIT_FILE || DEFAULT_AUDIT,
    autoRun: enabled(env.JOB_AGENT_SLACK_AUTORUN, true),
    notifyResults: enabled(env.JOB_AGENT_SLACK_NOTIFY_RESULTS, true),
    notifyPollMs: Math.max(1000, Number(env.JOB_AGENT_SLACK_NOTIFY_POLL_MS || 5000)),
    dispatchScript: env.JOB_AGENT_DISPATCH_SCRIPT || DEFAULT_DISPATCH_SCRIPT,
  };
}

export function checkConfig(config, { requireTokens = true } = {}) {
  const missing = [];
  if (requireTokens && !config.appToken) missing.push("SLACK_APP_TOKEN");
  if (requireTokens && !config.botToken) missing.push("SLACK_BOT_TOKEN");
  if (!config.allowedUsers.length) missing.push("JOB_AGENT_SLACK_ALLOWED_USERS");
  return {
    ok: missing.length === 0,
    missing,
    slash_command: config.slashCommand,
    queue_file: config.queueFile,
    audit_file: config.auditFile,
    allowed_users_count: config.allowedUsers.length,
    allowed_teams_count: config.allowedTeams.length,
    allowed_channels_count: config.allowedChannels.length,
  };
}

function authorizationFailure(input, config) {
  if (!config.allowedUsers.length) {
    return "Slack user allowlist is empty. Set JOB_AGENT_SLACK_ALLOWED_USERS to your Slack user id.";
  }
  if (!config.allowedUsers.includes(input.user)) {
    return "This Slack user is not allowed to queue Job Agent work.";
  }
  if (config.allowedTeams.length && !config.allowedTeams.includes(input.team)) {
    return "This Slack workspace is not allowed for Job Agent work.";
  }
  if (config.allowedChannels.length && !config.allowedChannels.includes(input.channel)) {
    return "This Slack channel is not allowed for Job Agent work.";
  }
  return "";
}

function loadQueue(queueFile) {
  try {
    return JSON.parse(fs.readFileSync(queueFile, "utf8"));
  } catch {
    return { items: [] };
  }
}

function queueStatusText(command, queueFile) {
  const data = loadQueue(queueFile);
  const idMatch = /\b(?:status|queue)\s+#?(\d+)\b/i.exec(command);
  if (idMatch) {
    const item = (data.items || []).find((candidate) => String(candidate.id) === idMatch[1]);
    if (!item) return `No queued command #${idMatch[1]}.`;
    const result = item.result ? ` Result: ${redact(item.result)}` : "";
    return `#${item.id} is ${item.status}: ${redact(item.command)}.${result}`;
  }

  const counts = { pending: 0, in_progress: 0, completed: 0, failed: 0 };
  for (const item of data.items || []) {
    if (Object.hasOwn(counts, item.status)) counts[item.status] += 1;
  }
  return `Queue: ${counts.pending} pending, ${counts.in_progress} in progress, ${counts.completed} done, ${counts.failed} failed.`;
}

export function helpText(config = configFromEnv({})) {
  return [
    `Use ${config.slashCommand || DEFAULT_SLASH_COMMAND} with one command:`,
    "`check {url}`",
    "`apply {url}`",
    "`force tailor {url}`",
    "`continue {job}`",
    "`submit {job}`",
    '`find job_title:"Product Designer" jobboard:"workday" not_on_linkedin:true`',
    "",
    "Queued work still runs on the Mac, in the approved Chrome profile, and final submit still needs the named submit command.",
  ].join("\n");
}

export function enqueueCommand(input, config = configFromEnv({}), runner = spawnSync) {
  const command = normalizeCommandText(input.text);
  const key = deriveSlackIdempotencyKey(input);
  const source = `slack:${input.user || "unknown"}`;
  const args = [
    path.join(REPO_ROOT, "scripts", "command_queue.py"),
    "--queue-file",
    config.queueFile,
    "--audit-file",
    config.auditFile,
    "enqueue",
    command,
    "--idempotency-key",
    key,
    "--source",
    source,
    "--notify-team",
    input.team || "",
    "--notify-channel",
    input.channel || "",
    "--notify-user",
    input.user || "",
    "--notify-thread-ts",
    input.messageTs || "",
  ];
  const result = runner("python3", args, { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || "command_queue.py failed").trim());
  }
  return JSON.parse(result.stdout);
}

function workerForItem(item = {}) {
  return String(item.assigned_worker || "").toLowerCase() === "codex" ? "codex" : "claude";
}

export function triggerDispatchForResult(result, config = configFromEnv({}), runner = spawn) {
  if (!result?.ok || !result?.queued || !result?.item) {
    return { attempted: false, started: false, reason: "not_queued" };
  }
  if (!config.autoRun) {
    return { attempted: false, started: false, reason: "autorun_disabled" };
  }
  const worker = workerForItem(result.item);
  try {
    const child = runner(config.dispatchScript, [worker], {
      cwd: REPO_ROOT,
      detached: true,
      stdio: "ignore",
      env: {
        ...process.env,
        JOB_AGENT_QUEUE_FILE: config.queueFile,
        JOB_AGENT_AUDIT_FILE: config.auditFile,
      },
    });
    if (typeof child?.unref === "function") child.unref();
    return { attempted: true, started: true, worker };
  } catch (error) {
    return {
      attempted: true,
      started: false,
      worker,
      reason: error?.message || String(error),
    };
  }
}

function dispatchText(result, dispatch) {
  if (!result?.queued || !dispatch?.attempted) return result.text;
  if (dispatch.started) return `${result.text} Starting ${dispatch.worker} worker.`;
  return `${result.text} Worker auto-start failed; check the Mac logs.`;
}

export function handleSlackInput(input, config = configFromEnv({}), options = {}) {
  const command = normalizeCommandText(input.text);
  const authFailure = authorizationFailure(input, config);
  if (authFailure) {
    return { ok: false, queued: false, text: authFailure };
  }

  if (!command || /^help$/i.test(command) || LOCAL_HELPERS.test(command)) {
    if (/^(status|queue)\b/i.test(command)) {
      return {
        ok: true,
        queued: false,
        text: queueStatusText(command, config.queueFile),
      };
    }
    return { ok: true, queued: false, text: helpText(config) };
  }

  if (!ALLOWED_COMMANDS.test(command)) {
    return {
      ok: false,
      queued: false,
      text: "Rejected. Start with check, apply, force tailor, continue, submit, find, or search.",
    };
  }

  const enqueue = options.enqueue || enqueueCommand;
  const result = enqueue({ ...input, text: command }, config);
  const item = result.item || {};
  const label = result.duplicate ? "Already queued" : "Queued";
  const submitNote = /^submit\b/i.test(command)
    ? " I will still re-verify the prepared application before any click."
    : "";
  return {
    ok: true,
    queued: !result.duplicate,
    duplicate: Boolean(result.duplicate),
    queueId: item.id,
    item,
    worker: workerForItem(item),
    text: `${label} as #${item.id}.${submitNote}`,
  };
}

export function inputFromSlashPayload(payload) {
  return {
    kind: "slash",
    text: payload.text || "",
    user: payload.user_id || "",
    team: payload.team_id || "",
    channel: payload.channel_id || "",
    triggerId: payload.trigger_id || "",
    commandName: payload.command || "",
  };
}

export function inputFromMessageEvent(payload) {
  const event = payload.event || {};
  if (event.subtype || event.bot_id) {
    return null;
  }
  if (event.type !== "message") return null;
  if (event.channel_type !== "im") return null;
  return {
    kind: "message",
    text: event.text || "",
    user: event.user || "",
    team: payload.team_id || payload.authorizations?.[0]?.team_id || "",
    channel: event.channel || "",
    messageTs: event.ts || "",
    eventId: payload.event_id || "",
  };
}

async function slackFetch(method, token, body = {}) {
  const response = await fetch(`${SLACK_API}/${method}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json; charset=utf-8",
    },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!data.ok) {
    throw new Error(`${method} failed: ${data.error || response.status}`);
  }
  return data;
}

function queueCommand(config, args, runner = spawnSync) {
  const result = runner("python3", [
    path.join(REPO_ROOT, "scripts", "command_queue.py"),
    "--queue-file",
    config.queueFile,
    "--audit-file",
    config.auditFile,
    ...args,
  ], { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || "command_queue.py failed").trim());
  }
  return JSON.parse(result.stdout);
}

/** Slack rejects very long messages, so a full answer is split, not cut. */
export const SLACK_MESSAGE_LIMIT = 3500;

/**
 * Split text into Slack-sized chunks on the friendliest boundary available:
 * a blank line, then a newline, then a hard cut. Truncating a tailoring
 * summary or a job table at 3200 characters silently loses the part the user
 * most needs — usually what is still waiting on him, which comes last.
 */
export function chunkForSlack(text, limit = SLACK_MESSAGE_LIMIT) {
  const body = String(text ?? "");
  if (body.length <= limit) return body ? [body] : [];

  const chunks = [];
  let rest = body;
  while (rest.length > limit) {
    const window = rest.slice(0, limit);
    let cut = window.lastIndexOf("\n\n");
    if (cut < limit * 0.5) cut = window.lastIndexOf("\n");
    if (cut < limit * 0.5) cut = limit;
    chunks.push(rest.slice(0, cut).trimEnd());
    rest = rest.slice(cut).replace(/^\n+/, "");
  }
  if (rest.trim()) chunks.push(rest);
  return chunks;
}

export function formatQueueNotification(item) {
  const status = item.status === "completed" ? "completed" : "blocked";
  const worker = workerForItem(item);
  const command = redact(item.command || "");
  // No cap here: the queue already bounded and marked the stored text, and
  // chunkForSlack splits it. Re-capping would silently drop the tail again.
  const result = redact(item.result_details || item.result || "No result text recorded.", Infinity);
  return `#${item.id} ${status} by ${worker}: ${command}\n${result}`;
}

/** The message(s) to post for one finished item, in order. */
export function notificationMessages(item) {
  const chunks = chunkForSlack(formatQueueNotification(item));
  if (chunks.length <= 1) return chunks;
  return chunks.map((chunk, index) => `${chunk}\n_(${index + 1}/${chunks.length})_`);
}

async function replyChannelForItem(item, config, fetcher) {
  const notify = item.notify || {};
  const channel = notify.channel || "";
  if (channel.startsWith("D")) return channel;
  if (notify.user) {
    const data = await fetcher("conversations.open", config.botToken, { users: notify.user });
    return data.channel?.id || channel;
  }
  return channel;
}

export async function sendPendingSlackNotifications(config = configFromEnv({}), options = {}) {
  if (!config.notifyResults || !config.botToken) return { sent: 0, skipped: true };
  const runner = options.runner || spawnSync;
  const fetcher = options.fetcher || ((method, token, body) => slackFetch(method, token, body));
  const listed = queueCommand(config, ["list", "--needs-notification"], runner);
  let sent = 0;
  for (const item of listed.items || []) {
    const channel = await replyChannelForItem(item, config, fetcher);
    if (!channel) continue;
    // Post every chunk before marking notified: if the run dies halfway, the
    // item stays unnotified and the whole answer is re-sent, rather than
    // leaving the user with the first half and no way to get the rest.
    for (const text of notificationMessages(item)) {
      await fetcher("chat.postMessage", config.botToken, { channel, text });
    }
    queueCommand(config, ["mark-notified", "--id", String(item.id), "--status", item.status], runner);
    sent += 1;
  }
  return { sent, skipped: false };
}

function startNotificationWatcher(config) {
  if (!config.notifyResults) return;
  let running = false;
  const poll = async () => {
    if (running) return;
    running = true;
    try {
      const result = await sendPendingSlackNotifications(config);
      if (result.sent) console.log(`Slack result notifications sent: ${result.sent}`);
    } catch (error) {
      console.error(error.stack || String(error));
    } finally {
      running = false;
    }
  };
  setTimeout(poll, 1000);
  setInterval(poll, config.notifyPollMs);
}

async function openSocketUrl(appToken) {
  const response = await fetch(`${SLACK_API}/apps.connections.open`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${appToken}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
  });
  const data = await response.json();
  if (!data.ok || !data.url) {
    throw new Error(`apps.connections.open failed: ${data.error || response.status}`);
  }
  return data.url;
}

function ackPayload(envelopeId, text = "") {
  if (!text) return JSON.stringify({ envelope_id: envelopeId });
  return JSON.stringify({
    envelope_id: envelopeId,
    payload: {
      response_type: "ephemeral",
      text,
    },
  });
}

async function handleEnvelope(ws, envelope, config) {
  if (envelope.type === "hello") {
    console.log("Slack Socket Mode connected.");
    return;
  }
  if (envelope.type === "disconnect") {
    console.log(`Slack requested reconnect: ${envelope.reason || "unknown reason"}`);
    ws.close();
    return;
  }

  const envelopeId = envelope.envelope_id;
  const payload = envelope.payload || {};

  try {
    if (envelope.type === "slash_commands") {
      const input = inputFromSlashPayload(payload);
      if (input.commandName && input.commandName !== config.slashCommand) {
        ws.send(ackPayload(envelopeId));
        return;
      }
      const result = handleSlackInput(input, config);
      const dispatch = triggerDispatchForResult(result, config);
      const text = dispatchText(result, dispatch);
      ws.send(ackPayload(envelopeId, text));
      console.log(`${result.ok ? "accepted" : "rejected"} slash command from ${input.user}: ${text}`);
      return;
    }

    if (envelope.type === "events_api") {
      ws.send(ackPayload(envelopeId));
      const input = inputFromMessageEvent(payload);
      if (!input) return;
      const result = handleSlackInput(input, config);
      const dispatch = triggerDispatchForResult(result, config);
      await slackFetch("chat.postMessage", config.botToken, {
        channel: input.channel,
        text: dispatchText(result, dispatch),
      });
      console.log(`${result.ok ? "accepted" : "rejected"} DM from ${input.user}: ${dispatchText(result, dispatch)}`);
      return;
    }

    if (envelopeId) ws.send(ackPayload(envelopeId));
  } catch (error) {
    if (envelopeId) ws.send(ackPayload(envelopeId, "Job Agent Slack intake hit an error. Check the Mac logs."));
    console.error(error.stack || String(error));
  }
}

async function start(config) {
  const check = checkConfig(config, { requireTokens: true });
  if (!check.ok) {
    throw new Error(`Missing required environment: ${check.missing.join(", ")}`);
  }
  if (typeof WebSocket !== "function") {
    throw new Error("This Node runtime does not provide WebSocket. Use Node 22+ or install a Socket Mode SDK.");
  }

  startNotificationWatcher(config);

  let attempt = 0;
  for (;;) {
    attempt += 1;
    try {
      const url = await openSocketUrl(config.appToken);
      await new Promise((resolve) => {
        const ws = new WebSocket(url);
        ws.addEventListener("message", (event) => {
          try {
            handleEnvelope(ws, JSON.parse(event.data), config);
          } catch (error) {
            console.error(error.stack || String(error));
          }
        });
        ws.addEventListener("close", resolve);
        ws.addEventListener("error", (event) => {
          console.error(`Slack socket error: ${event.message || "unknown"}`);
          resolve();
        });
      });
    } catch (error) {
      console.error(error.stack || String(error));
    }
    const delayMs = Math.min(30000, 1000 * attempt);
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
}

function printSetup() {
  console.log(`Slack setup for Job Agent

1. Create a Slack app at https://api.slack.com/apps and choose your workspace.
2. Enable Socket Mode.
3. Create an app-level token with the connections:write scope.
4. Add bot scopes: commands, chat:write, im:write, im:history, im:read.
5. Create the slash command ${DEFAULT_SLASH_COMMAND}. In Socket Mode, no public Request URL is needed.
6. Under App Home, enable the Messages Tab and allow users to send messages from it if you want to DM the bot.
7. Under Event Subscriptions, subscribe to the bot event message.im if you want to DM the bot.
8. Install or reinstall the app to the workspace.
9. Put secrets in ~/.job-agent/slack.env:

   export SLACK_APP_TOKEN=xapp-...
   export SLACK_BOT_TOKEN=xoxb-...
   export JOB_AGENT_SLACK_ALLOWED_USERS=U1234567890

10. Start the listener:

   ./scripts/slack_daemon.sh arm

Then from Slack mobile:

   ${DEFAULT_SLASH_COMMAND} check https://...
   ${DEFAULT_SLASH_COMMAND} apply https://...
   ${DEFAULT_SLASH_COMMAND} find job_title:"Product Designer" jobboard:"workday"

The Slack listener queues commands, starts one matching drain cycle, and posts
terminal results back to Slack. The Mac still needs to be awake with the Chrome
bridge available for browser work. Set JOB_AGENT_SLACK_AUTORUN=0 or
JOB_AGENT_SLACK_NOTIFY_RESULTS=0 to disable worker starts or result replies.`);
}

function parseCli(argv) {
  const [command = "help", ...rest] = argv;
  const options = {};
  const positional = [];
  for (let index = 0; index < rest.length; index += 1) {
    const part = rest[index];
    if (part.startsWith("--")) {
      const key = part.slice(2).replace(/-/g, "_");
      options[key] = rest[index + 1] || "";
      index += 1;
    } else {
      positional.push(part);
    }
  }
  return { command, options, positional };
}

async function main(argv = process.argv.slice(2)) {
  const { command, options, positional } = parseCli(argv);
  const config = configFromEnv();

  if (command === "setup" || command === "help") {
    printSetup();
    return 0;
  }
  if (command === "check-env") {
    console.log(JSON.stringify(checkConfig(config), null, 2));
    return checkConfig(config).ok ? 0 : 2;
  }
  if (command === "start") {
    await start(config);
    return 0;
  }
  if (command === "enqueue") {
    const input = {
      kind: "cli",
      text: positional.join(" "),
      user: options.user || "",
      team: options.team || "",
      channel: options.channel || "",
      eventId: options.event_id || "",
    };
    const result = handleSlackInput(input, config);
    console.log(JSON.stringify(result, null, 2));
    return result.ok ? 0 : 2;
  }

  console.error("Usage: slack_intake.mjs {setup|check-env|start|enqueue}");
  return 2;
}

if (fileURLToPath(import.meta.url) === path.resolve(process.argv[1] || "")) {
  main().then((code) => process.exit(code)).catch((error) => {
    console.error(error.stack || String(error));
    process.exit(1);
  });
}
