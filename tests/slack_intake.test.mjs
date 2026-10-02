import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  checkConfig,
  chunkForSlack,
  configFromEnv,
  deriveSlackIdempotencyKey,
  enqueueCommand,
  formatQueueNotification,
  notificationMessages,
  handleSlackInput,
  inputFromMessageEvent,
  inputFromSlashPayload,
  normalizeCommandText,
  redact,
  sendPendingSlackNotifications,
  triggerDispatchForResult,
} from "../scripts/slack_intake.mjs";


function testConfig(extra = {}) {
  return {
    appToken: "",
    botToken: "",
    slashCommand: "/jobagent",
    allowedUsers: ["U_ALLOWED"],
    allowedTeams: [],
    allowedChannels: [],
    queueFile: path.join(os.tmpdir(), "job-agent-slack-test-queue.json"),
    auditFile: path.join(os.tmpdir(), "job-agent-slack-test-audit.jsonl"),
    autoRun: true,
    notifyResults: true,
    notifyPollMs: 5000,
    dispatchScript: "/tmp/job-agent-dispatch-test.sh",
    ...extra,
  };
}


test("Slack link wrapping is normalized before command parsing", () => {
  assert.equal(
    normalizeCommandText("JOBAGENT: apply <https://jobs.lever.co/acme/123|Acme role>"),
    "apply https://jobs.lever.co/acme/123",
  );
});


test("config check requires a Slack user allowlist", () => {
  const config = configFromEnv({
    SLACK_APP_TOKEN: "xapp-test",
    SLACK_BOT_TOKEN: "xoxb-test",
  });
  const result = checkConfig(config);
  assert.equal(result.ok, false);
  assert.deepEqual(result.missing, ["JOB_AGENT_SLACK_ALLOWED_USERS"]);
});


test("unauthorized Slack users cannot queue commands", () => {
  const result = handleSlackInput(
    { text: "apply https://example.com/job", user: "U_OTHER", team: "T1", channel: "D1" },
    testConfig(),
  );
  assert.equal(result.ok, false);
  assert.match(result.text, /not allowed/);
});


test("unsupported verbs are rejected before enqueue", () => {
  let called = false;
  const result = handleSlackInput(
    { text: "delete everything", user: "U_ALLOWED", team: "T1", channel: "D1" },
    testConfig(),
    { enqueue: () => { called = true; } },
  );
  assert.equal(result.ok, false);
  assert.equal(called, false);
});


test("help and queue status are local helper commands", () => {
  const help = handleSlackInput(
    { text: "help", user: "U_ALLOWED", team: "T1", channel: "D1" },
    testConfig(),
  );
  assert.equal(help.ok, true);
  assert.match(help.text, /apply \{url\}/);

  const status = handleSlackInput(
    { text: "status", user: "U_ALLOWED", team: "T1", channel: "D1" },
    testConfig({ queueFile: "/tmp/definitely-not-a-job-agent-queue.json" }),
  );
  assert.equal(status.ok, true);
  assert.match(status.text, /0 pending/);
});


test("Slack can ask for one queued command by id", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "job-agent-slack-status-"));
  const queueFile = path.join(tmp, "queue.json");
  fs.writeFileSync(queueFile, JSON.stringify({
    items: [
      {
        id: 12,
        status: "failed",
        command: "apply https://example.com/job",
        result: "blocked_credentials code: 123456",
      },
    ],
  }));

  const result = handleSlackInput(
    { text: "status #12", user: "U_ALLOWED", team: "T1", channel: "D1" },
    testConfig({ queueFile }),
  );
  assert.equal(result.ok, true);
  assert.match(result.text, /#12 is failed/);
  assert.doesNotMatch(result.text, /123456/);
});


test("allowed job commands are enqueued through the injected queue writer", () => {
  const seen = [];
  const result = handleSlackInput(
    {
      text: "JOBAGENT: check <https://job-boards.greenhouse.io/acme/jobs/456>",
      user: "U_ALLOWED",
      team: "T1",
      channel: "D1",
      eventId: "Ev123",
    },
    testConfig(),
    {
      enqueue: (input) => {
        seen.push(input);
        return { duplicate: false, item: { id: 41 } };
      },
    },
  );

  assert.equal(result.ok, true);
  assert.equal(result.queued, true);
  assert.equal(result.queueId, 41);
  assert.equal(seen[0].text, "check https://job-boards.greenhouse.io/acme/jobs/456");
});


test("submit command reply reminds that the application is re-verified", () => {
  const result = handleSlackInput(
    { text: "submit eudia-product-designer", user: "U_ALLOWED", team: "T1", channel: "D1" },
    testConfig(),
    { enqueue: () => ({ duplicate: false, item: { id: 8 } }) },
  );
  assert.match(result.text, /re-verify/);
});


test("Slack event ids become stable idempotency keys", () => {
  assert.equal(
    deriveSlackIdempotencyKey({ team: "T1", eventId: "Ev123", text: "apply x" }),
    "slack:T1:Ev123",
  );
  assert.equal(
    deriveSlackIdempotencyKey({ team: "T1", eventId: "Ev123", text: "apply y" }),
    "slack:T1:Ev123",
  );
});


test("slash payloads are mapped to Slack input", () => {
  assert.deepEqual(
    inputFromSlashPayload({
      command: "/jobagent",
      text: "apply https://example.com/job",
      user_id: "U1",
      team_id: "T1",
      channel_id: "C1",
      trigger_id: "Trig1",
    }),
    {
      kind: "slash",
      text: "apply https://example.com/job",
      user: "U1",
      team: "T1",
      channel: "C1",
      triggerId: "Trig1",
      commandName: "/jobagent",
    },
  );
});


test("only Slack DMs from real users become message commands", () => {
  assert.equal(inputFromMessageEvent({ event: { type: "message", channel_type: "channel" } }), null);
  assert.equal(inputFromMessageEvent({ event: { type: "message", channel_type: "im", bot_id: "B1" } }), null);

  const input = inputFromMessageEvent({
    event_id: "Ev1",
    team_id: "T1",
    authorizations: [{ user_id: "U1" }],
    event: {
      type: "message",
      channel_type: "im",
      text: "check https://example.com",
      user: "U1",
      channel: "D1",
      ts: "123.456",
    },
  });
  assert.equal(input.eventId, "Ev1");
  assert.equal(input.user, "U1");
});


test("enqueueCommand writes to the existing local command queue format", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "job-agent-slack-"));
  const config = testConfig({
    queueFile: path.join(tmp, "queue.json"),
    auditFile: path.join(tmp, "audit.jsonl"),
  });

  const result = enqueueCommand(
    { text: "apply https://jobs.lever.co/acme/abc", user: "U_ALLOWED", team: "T1", channel: "D1", eventId: "Ev1" },
    config,
  );

  assert.equal(result.enqueued, true);
  const queue = JSON.parse(fs.readFileSync(config.queueFile, "utf8"));
  assert.equal(queue.items[0].source, "slack:U_ALLOWED");
  assert.equal(queue.items[0].idempotency_key, "slack:T1:Ev1");
  assert.equal(queue.items[0].notify.type, "slack");
  assert.equal(queue.items[0].notify.channel, "D1");
  assert.equal(queue.items[0].notify.user, "U_ALLOWED");
});


test("redaction catches secrets before Slack replies or logs echo them", () => {
  const value = redact("continue job code: 481920 password hunter2 https://x.test/?magic=secret");
  assert.doesNotMatch(value, /481920|hunter2|magic=secret/);
  assert.match(value, /\[redacted\]/);
});


test("dispatch starts the worker assigned to a queued result", () => {
  const calls = [];
  const dispatch = triggerDispatchForResult(
    { ok: true, queued: true, item: { id: 7, assigned_worker: "codex" } },
    testConfig({ dispatchScript: "/tmp/dispatch.sh" }),
    (cmd, args, options) => {
      calls.push({ cmd, args, options });
      return { unref() {} };
    },
  );

  assert.equal(dispatch.started, true);
  assert.equal(dispatch.worker, "codex");
  assert.equal(calls[0].cmd, "/tmp/dispatch.sh");
  assert.deepEqual(calls[0].args, ["codex"]);
  assert.equal(calls[0].options.detached, true);
});


test("dispatch is skipped when autorun is disabled", () => {
  const dispatch = triggerDispatchForResult(
    { ok: true, queued: true, item: { id: 7 } },
    testConfig({ autoRun: false }),
    () => {
      throw new Error("should not run");
    },
  );
  assert.equal(dispatch.started, false);
  assert.equal(dispatch.reason, "autorun_disabled");
});


test("terminal queue notifications are sent to Slack once", async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "job-agent-slack-notify-"));
  const queueFile = path.join(tmp, "queue.json");
  const auditFile = path.join(tmp, "audit.jsonl");
  fs.writeFileSync(queueFile, JSON.stringify({
    version: 1,
    next_id: 2,
    items: [
      {
        id: 1,
        command: "check https://example.com/job",
        assigned_worker: "codex",
        status: "completed",
        result: "short summary",
        result_details: "Full ATS table\ncode: 123456\nBowerbird 88%",
        notify: {
          type: "slack",
          channel: "D1",
          user: "U_ALLOWED",
          notified_status: "",
          notified_at: "",
        },
      },
    ],
  }));

  const posts = [];
  const result = await sendPendingSlackNotifications(
    testConfig({ botToken: "xoxb-test", queueFile, auditFile }),
    {
      fetcher: async (method, token, body) => {
        posts.push({ method, token, body });
        return { ok: true };
      },
    },
  );

  assert.equal(result.sent, 1);
  assert.equal(posts[0].method, "chat.postMessage");
  assert.equal(posts[0].body.channel, "D1");
  assert.match(posts[0].body.text, /#1 completed by codex/);
  assert.match(posts[0].body.text, /Full ATS table/);
  assert.match(posts[0].body.text, /Bowerbird 88%/);
  assert.doesNotMatch(posts[0].body.text, /123456/);

  const queue = JSON.parse(fs.readFileSync(queueFile, "utf8"));
  assert.equal(queue.items[0].notify.notified_status, "completed");
});


test("queue notification formatting redacts secrets", () => {
  const text = formatQueueNotification({
    id: 9,
    command: "continue eudia password hunter2",
    assigned_worker: "claude",
    status: "failed",
    result: "blocked code: 481920",
  });
  assert.match(text, /#9 blocked by claude/);
  assert.doesNotMatch(text, /hunter2|481920/);
});


// --- A full answer must reach Slack intact, not truncated at 3200 chars ---

test("a short result posts as one message", () => {
  const messages = notificationMessages({
    id: 7, status: "completed", assigned_worker: "claude",
    command: "check https://a.test/1", result_details: "Initial ATS: 84% | Decision: Proceed",
  });
  assert.equal(messages.length, 1);
  assert.match(messages[0], /Initial ATS: 84%/);
});

test("a long tailoring answer is split, never cut", () => {
  // The old formatter sliced at 3200/3500. The part the user most needs —
  // what is still waiting on him — is written last, so a cut lost exactly it.
  const body = `${"Scored job table row.\n".repeat(400)}\nSTILL WAITING ON YOU: CAPTCHA on Eudia`;
  const messages = notificationMessages({
    id: 8, status: "completed", assigned_worker: "claude",
    command: "find product designer jobs", result_details: body,
  });

  assert.ok(messages.length > 1, "expected the answer to be split");
  for (const message of messages) {
    assert.ok(message.length <= 3600, `chunk too long: ${message.length}`);
  }
  const joined = messages.join("\n");
  assert.match(joined, /STILL WAITING ON YOU: CAPTCHA on Eudia/);
  assert.match(messages[0], /\(1\/\d\)/);
});

test("chunking prefers paragraph then line boundaries", () => {
  const text = `${"a".repeat(300)}\n\n${"b".repeat(300)}`;
  const chunks = chunkForSlack(text, 400);
  assert.equal(chunks.length, 2);
  assert.ok(chunks[0].endsWith("a"));
  assert.ok(chunks[1].startsWith("b"));
});

test("chunking still terminates when there is no boundary to find", () => {
  const chunks = chunkForSlack("x".repeat(1000), 100);
  assert.equal(chunks.length, 10);
  assert.equal(chunks.join(""), "x".repeat(1000));
});

test("the full detail is preferred over the one-line result", () => {
  const text = formatQueueNotification({
    id: 9, status: "completed", assigned_worker: "claude",
    command: "apply https://a.test/1",
    result: "prepared",
    result_details: "Tailored resume: 84% -> 91% (+7)\nCover letter written\nStopped before submit",
  });
  assert.match(text, /Stopped before submit/);
  assert.doesNotMatch(text, /^#9 completed by claude: apply https:\/\/a\.test\/1\nprepared$/);
});
