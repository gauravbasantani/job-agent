#!/usr/bin/env node

import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";


const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_STATE = resolve(REPO_ROOT, ".job-agent", "browser-tabs.json");
const DEFAULT_AUDIT = resolve(REPO_ROOT, ".job-agent", "browser-audit.jsonl");
const ALLOWED_STATES = new Set([
  "opened",
  "inspecting",
  "filling",
  "verifying",
  "awaiting_submit",
  "submitted",
  "blocked_account",
  "blocked_credentials",
  "blocked_captcha",
  "blocked_unknown_field",
  "technical_failure",
  "technical_retry",
]);
const SENSITIVE_QUERY_KEYS = /(auth|code|credential|key|otp|password|secret|session|signature|token)/i;

// A tab may only move forward through the fill lifecycle, or sideways into a
// blocked/failure state. Anything that lands in a blocked state leaves the
// tab mapped and waits for the human — it is never a retry condition.
const TRANSITIONS = {
  opened: ["inspecting", "filling"],
  inspecting: ["filling", "verifying"],
  filling: ["verifying", "inspecting"],
  verifying: ["awaiting_submit", "filling"],
  awaiting_submit: ["submitted", "filling", "verifying"],
  submitted: [],
  technical_retry: ["inspecting", "filling", "verifying", "technical_failure"],
  technical_failure: ["technical_retry", "inspecting"],
};
const BLOCKED_STATES = new Set([
  "blocked_account",
  "blocked_credentials",
  "blocked_captcha",
  "blocked_unknown_field",
]);
export const MAX_TECHNICAL_RETRIES = 2;

/**
 * The only Chrome profiles this runtime may drive.
 *
 * `the user` is the real everyday profile. Chrome 136+ refuses remote debugging
 * on the default user-data-dir, so in practice automation runs as
 * `the user Automation` — a dedicated profile in its own data directory. It is
 * named distinctly on purpose: a second profile also called `the user` would
 * satisfy this check by impersonation and turn the guarantee into a formality.
 * Your University, Work, Viresh, Guest and anything else stay off-limits either way.
 */
export const ALLOWED_PROFILE_NAMES = new Set(["the user", "the user Automation"]);
export const DEFAULT_PROFILE_NAME = "the user Automation";


export function parseArgs(argv) {
  const [command = "list", ...rest] = argv;
  const options = {};
  for (let index = 0; index < rest.length; index += 1) {
    const item = rest[index];
    if (!item.startsWith("--")) throw new Error(`Unexpected argument: ${item}`);
    const key = item.slice(2).replaceAll("-", "_");
    const next = rest[index + 1];
    if (!next || next.startsWith("--")) options[key] = true;
    else {
      options[key] = next;
      index += 1;
    }
  }
  return { command, options };
}


export function sanitizeUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    for (const key of [...url.searchParams.keys()]) {
      if (SENSITIVE_QUERY_KEYS.test(key)) url.searchParams.delete(key);
    }
    url.hash = "";
    return url.toString();
  } catch {
    return String(value).slice(0, 1000);
  }
}


export function validJobKey(value) {
  return typeof value === "string" && /^[a-z0-9][a-z0-9._-]{1,119}$/i.test(value);
}


export function isBlockedState(state) {
  return BLOCKED_STATES.has(String(state));
}


/** A blocked tab waits for the user; only technical failures may be retried. */
export function isRetryable(job) {
  if (!job || isBlockedState(job.state)) return false;
  if (!["technical_failure", "technical_retry", "opened", "inspecting", "filling"].includes(job.state)) return false;
  return Number(job.retry_count || 0) < MAX_TECHNICAL_RETRIES;
}


export function canTransition(from, to) {
  if (!ALLOWED_STATES.has(String(to))) return false;
  if (isBlockedState(to)) return String(from) !== "submitted";
  if (isBlockedState(from)) return ["inspecting", "filling", "verifying"].includes(String(to));
  return (TRANSITIONS[String(from)] || []).includes(String(to));
}


class CdpConnection {
  constructor(url) {
    this.url = url;
    this.nextId = 1;
    this.pending = new Map();
    this.socket = null;
  }

  async connect() {
    this.socket = new WebSocket(this.url);
    this.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const { resolve: done, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(JSON.stringify(message.error)));
      else done(message.result);
    };
    await new Promise((done, reject) => {
      this.socket.onopen = done;
      this.socket.onerror = reject;
    });
    return this;
  }

  send(method, params = {}, sessionId = undefined) {
    const id = this.nextId++;
    const message = { id, method, params };
    if (sessionId) message.sessionId = sessionId;
    this.socket.send(JSON.stringify(message));
    return new Promise((done, reject) => this.pending.set(id, { resolve: done, reject }));
  }

  close() {
    this.socket?.close();
  }
}


async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Chrome debug endpoint returned ${response.status}`);
  return response.json();
}


export async function connectBrowser(port) {
  const version = await fetchJson(`http://127.0.0.1:${port}/json/version`);
  if (!version.webSocketDebuggerUrl) throw new Error("Chrome browser debugger URL is missing");
  return new CdpConnection(version.webSocketDebuggerUrl).connect();
}


export async function attach(browser, targetId) {
  const result = await browser.send("Target.attachToTarget", { targetId, flatten: true });
  return result.sessionId;
}


export async function evaluate(browser, sessionId, expression) {
  const result = await browser.send(
    "Runtime.evaluate",
    { expression, returnByValue: true, awaitPromise: true },
    sessionId,
  );
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Evaluation failed");
  return result.result?.value;
}


async function profilePathFromChrome(browser) {
  const created = await browser.send("Target.createTarget", {
    url: "chrome://version/",
    newWindow: false,
    background: true,
  });
  const targetId = created.targetId;
  try {
    const sessionId = await attach(browser, targetId);
    await browser.send("Runtime.enable", {}, sessionId);
    for (let attempt = 0; attempt < 30; attempt += 1) {
      // chrome://version fills in asynchronously. Reading too early returns an
      // empty #profile_path, and the innerText fallback then matches whatever
      // row happens to have rendered ("Linker  lld" on one real run). Wait for
      // the document to finish, and only accept an absolute path.
      const profilePath = await evaluate(
        browser,
        sessionId,
        `(() => {
          if (document.readyState !== 'complete') return '';
          const direct = document.querySelector('#profile_path')?.textContent?.trim();
          if (direct && direct.startsWith('/')) return direct;
          const text = document.body?.innerText || '';
          const match = text.match(/Profile Path[\\s\\t]*(\\/[^\\n]+)/i);
          return match ? match[1].trim() : '';
        })()`,
      );
      if (profilePath && profilePath.startsWith("/")) return profilePath;
      await new Promise((done) => setTimeout(done, 100));
    }
    throw new Error("Could not read Chrome profile path from chrome://version");
  } finally {
    await browser.send("Target.closeTarget", { targetId }).catch(() => {});
  }
}


export async function verifyProfile(browser, expectedName) {
  if (!ALLOWED_PROFILE_NAMES.has(expectedName)) {
    throw new Error(
      `This runtime is restricted to the Chrome profile named the user (allowed: ${[...ALLOWED_PROFILE_NAMES].join(", ")}); refusing ${JSON.stringify(expectedName)}`,
    );
  }
  const profilePath = await profilePathFromChrome(browser);
  // A relative path would make `Local State` resolve against the current
  // working directory, so a file sitting in the repo could satisfy the profile
  // check. The verification is only meaningful against Chrome's real path.
  if (!isAbsolute(profilePath)) {
    throw new Error(`Chrome reported a non-absolute profile path: ${profilePath || "(empty)"}`);
  }
  const profileDirectory = basename(profilePath);
  const localStatePath = resolve(dirname(profilePath), "Local State");
  let localState;
  try {
    localState = JSON.parse(await readFile(localStatePath, "utf8"));
  } catch (error) {
    throw new Error(`Cannot verify Chrome profile metadata at ${localStatePath}: ${error.message}`);
  }
  const metadata = localState?.profile?.info_cache?.[profileDirectory];
  const actualName = metadata?.name || metadata?.shortcut_name || "";
  if (actualName.trim().toLowerCase() !== expectedName.toLowerCase()) {
    throw new Error(
      `Chrome profile mismatch: expected the user, got ${actualName || "unverified"} (${profileDirectory})`,
    );
  }
  return { profile_name: actualName, profile_directory: profileDirectory, profile_path: profilePath };
}


export async function readState(path) {
  try {
    const data = JSON.parse(await readFile(path, "utf8"));
    return { version: 1, profile: {}, window_id: null, jobs: {}, ...data };
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    return { version: 1, profile: {}, window_id: null, jobs: {} };
  }
}


export async function saveState(path, state) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}


export async function audit(path, event) {
  await mkdir(dirname(path), { recursive: true });
  const safe = {
    timestamp: new Date().toISOString(),
    ...event,
    url: sanitizeUrl(event.url),
  };
  await appendFile(path, `${JSON.stringify(safe)}\n`, "utf8");
}


export async function currentTargets(browser) {
  const result = await browser.send("Target.getTargets", { filter: [{ type: "page" }] });
  return result.targetInfos || [];
}


async function windowForTarget(browser, targetId) {
  const result = await browser.send("Browser.getWindowForTarget", { targetId });
  return result.windowId;
}


async function chooseAnchor(browser, state, targets) {
  const alive = new Map(targets.map((target) => [target.targetId, target]));

  // Window ids do not survive a Chrome restart. A stored id whose window no
  // longer exists would reject every candidate below and deadlock the anchor
  // permanently, so drop it once nothing live belongs to it.
  if (state.window_id) {
    let stillOpen = false;
    for (const target of targets) {
      if ((await windowForTarget(browser, target.targetId)) === state.window_id) {
        stillOpen = true;
        break;
      }
    }
    if (!stillOpen) state.window_id = null;
  }
  for (const job of Object.values(state.jobs)) {
    if (!alive.has(job.target_id)) continue;
    const windowId = await windowForTarget(browser, job.target_id);
    if (!state.window_id || windowId === state.window_id) return job.target_id;
  }
  // Prefer a real page, but fall back to any page target. A freshly started
  // bridge only has chrome://newtab open, and refusing it made the very first
  // job impossible to open. The anchor exists only to identify the controlled
  // window, so an internal page serves that purpose fine.
  for (const preferReal of [true, false]) {
    for (const target of targets) {
      if (target.url.startsWith("devtools://")) continue;
      if (preferReal && target.url.startsWith("chrome://")) continue;
      const windowId = await windowForTarget(browser, target.targetId);
      if (!state.window_id || windowId === state.window_id) return target.targetId;
    }
  }
  throw new Error("No Chrome page is available as the controlled-window anchor");
}


async function openJob(browser, state, jobKey, rawUrl) {
  if (!validJobKey(jobKey)) throw new Error("--job must be a stable slug with 2-120 characters");
  if (!/^https?:\/\//i.test(rawUrl || "")) throw new Error("--url must be an HTTP(S) job URL");
  const targets = await currentTargets(browser);
  const aliveIds = new Set(targets.map((target) => target.targetId));
  const existing = state.jobs[jobKey];
  if (existing && aliveIds.has(existing.target_id)) {
    await browser.send("Target.activateTarget", { targetId: existing.target_id });
    return { reused: true, job: existing };
  }

  const anchorId = await chooseAnchor(browser, state, targets);
  await browser.send("Target.activateTarget", { targetId: anchorId });
  const anchorWindow = await windowForTarget(browser, anchorId);
  if (state.window_id && state.window_id !== anchorWindow) {
    throw new Error("The available anchor is not in the controlled Chrome window");
  }
  state.window_id = anchorWindow;

  const created = await browser.send("Target.createTarget", {
    url: rawUrl,
    newWindow: false,
    background: false,
  });
  const targetWindow = await windowForTarget(browser, created.targetId);
  if (targetWindow !== state.window_id) {
    await browser.send("Target.closeTarget", { targetId: created.targetId }).catch(() => {});
    throw new Error("Chrome opened the job outside the controlled window; the new tab was closed");
  }
  const job = {
    target_id: created.targetId,
    window_id: targetWindow,
    canonical_url: sanitizeUrl(rawUrl),
    state: "opened",
    retry_count: 0,
    updated_at: new Date().toISOString(),
  };
  state.jobs[jobKey] = job;
  return { reused: false, job };
}


async function inspectJob(browser, state, jobKey) {
  const job = state.jobs[jobKey];
  if (!job) throw new Error(`No browser tab is mapped for ${jobKey}`);
  const targets = await currentTargets(browser);
  if (!targets.some((target) => target.targetId === job.target_id)) {
    throw new Error(`The mapped tab for ${jobKey} is gone; refusing to create a replacement`);
  }
  const sessionId = await attach(browser, job.target_id);
  await browser.send("Runtime.enable", {}, sessionId);
  const page = await evaluate(
    browser,
    sessionId,
    `(() => ({
      title: document.title,
      url: location.href,
      ready_state: document.readyState,
      heading: document.querySelector('h1')?.innerText?.trim() || ''
    }))()`,
  );
  return { job_key: jobKey, state: job.state, retry_count: job.retry_count, ...page };
}


async function retryJob(browser, state, jobKey) {
  const job = state.jobs[jobKey];
  if (!job) throw new Error(`No browser tab is mapped for ${jobKey}`);
  const targets = await currentTargets(browser);
  if (!targets.some((target) => target.targetId === job.target_id)) {
    throw new Error(`The mapped tab for ${jobKey} is gone; retry will not open a new tab`);
  }
  if (job.retry_count >= 2) throw new Error(`Retry limit reached for ${jobKey}`);
  const sessionId = await attach(browser, job.target_id);
  await browser.send("Page.enable", {}, sessionId);
  await browser.send("Page.reload", { ignoreCache: true }, sessionId);
  job.retry_count += 1;
  job.state = "technical_retry";
  job.updated_at = new Date().toISOString();
  return job;
}


function requireOption(options, name) {
  const value = options[name];
  if (!value || value === true) throw new Error(`Missing --${name.replaceAll("_", "-")}`);
  return String(value);
}


async function run(argv = process.argv.slice(2)) {
  const { command, options } = parseArgs(argv);
  const port = Number(options.port || 9222);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid --port");
  const statePath = resolve(String(options.state_file || DEFAULT_STATE));
  const auditPath = resolve(String(options.audit_file || DEFAULT_AUDIT));
  const expectedProfile = String(options.profile || DEFAULT_PROFILE_NAME);

  const browser = await connectBrowser(port);
  try {
    const profile = await verifyProfile(browser, expectedProfile);
    const state = await readState(statePath);
    if (state.profile?.profile_path && state.profile.profile_path !== profile.profile_path) {
      throw new Error("Browser state belongs to a different Chrome profile path");
    }
    state.profile = profile;

    let result;
    if (command === "verify") result = { verified: true, profile };
    else if (command === "list") {
      const targets = await currentTargets(browser);
      const alive = new Set(targets.map((target) => target.targetId));
      result = {
        profile,
        window_id: state.window_id,
        jobs: Object.fromEntries(
          Object.entries(state.jobs).map(([key, job]) => [key, { ...job, alive: alive.has(job.target_id) }]),
        ),
      };
    } else if (command === "open") {
      const jobKey = requireOption(options, "job");
      const rawUrl = requireOption(options, "url");
      result = await openJob(browser, state, jobKey, rawUrl);
      await audit(auditPath, { job_key: jobKey, action: "open", result: result.reused ? "reused" : "created", url: rawUrl });
    } else if (command === "inspect" || command === "activate") {
      const jobKey = requireOption(options, "job");
      if (command === "activate") await browser.send("Target.activateTarget", { targetId: state.jobs[jobKey]?.target_id });
      result = await inspectJob(browser, state, jobKey);
      await audit(auditPath, { job_key: jobKey, action: command, result: "ok", url: result.url });
    } else if (command === "retry") {
      const jobKey = requireOption(options, "job");
      result = await retryJob(browser, state, jobKey);
      await audit(auditPath, { job_key: jobKey, action: "retry", result: "reloaded", retry_count: result.retry_count, url: result.canonical_url });
    } else if (command === "mark") {
      const jobKey = requireOption(options, "job");
      const nextState = requireOption(options, "state");
      if (!ALLOWED_STATES.has(nextState)) throw new Error(`Unsupported browser state: ${nextState}`);
      const job = state.jobs[jobKey];
      if (!job) throw new Error(`No browser tab is mapped for ${jobKey}`);
      if (!canTransition(job.state, nextState)) {
        throw new Error(`Illegal tab transition for ${jobKey}: ${job.state} -> ${nextState}`);
      }
      job.state = nextState;
      job.updated_at = new Date().toISOString();
      result = job;
      await audit(auditPath, { job_key: jobKey, action: "mark", result: nextState, url: job.canonical_url });
    } else {
      throw new Error(`Unknown command: ${command}`);
    }
    await saveState(statePath, state);
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } finally {
    browser.close();
  }
}


const isMain = process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  run().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
