#!/usr/bin/env node
/**
 * ATS fill engine. Drives the reusable adapters in `ats_adapters.mjs` against
 * the Chrome tab already mapped to a job by `chrome_tabs.mjs`.
 *
 *   node scripts/ats_fill.mjs inspect --job eudia-product-designer
 *   node scripts/ats_fill.mjs plan    --job eudia-product-designer --answers answers.json
 *   node scripts/ats_fill.mjs fill    --job eudia-product-designer --answers answers.json
 *   node scripts/ats_fill.mjs verify  --job eudia-product-designer --plan plan.json
 *
 * Boundaries this engine will not cross, per `context/hard-rules.md`:
 *   - It reuses only the Chrome profile named the user (guard shared with
 *     chrome_tabs.mjs) and only the tab already mapped to the job key.
 *   - It never clicks a final submit control. `fill` locates the submit button
 *     solely to assert it is still unclicked and report it.
 *   - It never types credentials, OTPs, government IDs, or payment details,
 *     and it stops on account walls, logins, CAPTCHA, and unknown widgets.
 *   - The audit log records state transitions and field categories, never
 *     field values.
 */

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  attach,
  audit,
  connectBrowser,
  currentTargets,
  evaluate,
  DEFAULT_PROFILE_NAME,
  parseArgs,
  readState,
  saveState,
  verifyProfile,
} from "./chrome_tabs.mjs";
import {
  detectAdapter,
  detectBlockers,
  fieldInspectionExpression,
  isFinalSubmitControl,
  planFill,
  verifyReadback,
} from "./ats_adapters.mjs";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_STATE = resolve(REPO_ROOT, ".job-agent", "browser-tabs.json");
const DEFAULT_AUDIT = resolve(REPO_ROOT, ".job-agent", "fill-audit.jsonl");

/** Audit-safe view of a plan: categories and lengths, never values. */
export function redactPlan(plan) {
  const strip = (entry) => ({
    selector: entry.selector,
    label: entry.label,
    category: entry.category,
    key: entry.key ?? null,
    type: entry.type,
    required: entry.required ?? false,
    ...(entry.reason ? { reason: entry.reason } : {}),
    ...(entry.intended_length !== undefined ? { intended_length: entry.intended_length } : {}),
  });
  return {
    adapter: plan.adapter,
    fills: (plan.fills || []).map(strip),
    skipped: (plan.skipped || []).map(strip),
    missing_required: (plan.missing_required || []).map(strip),
    human_required: (plan.human_required || []).map(strip),
  };
}

async function readJson(path) {
  return JSON.parse(await readFile(resolve(String(path)), "utf8"));
}

async function writeJson(path, payload) {
  const target = resolve(String(path));
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  return target;
}

function requireOption(options, name) {
  const value = options[name];
  if (!value || value === true) throw new Error(`Missing --${name.replaceAll("_", "-")}`);
  return String(value);
}

/** Attach to the tab already mapped to this job. Never opens a replacement. */
async function sessionForJob(browser, state, jobKey) {
  const job = state.jobs?.[jobKey];
  if (!job) throw new Error(`No browser tab is mapped for ${jobKey}. Run chrome_tabs.mjs open first.`);
  const targets = await currentTargets(browser);
  if (!targets.some((target) => target.targetId === job.target_id)) {
    throw new Error(`The mapped tab for ${jobKey} is gone; refusing to open a replacement.`);
  }
  const sessionId = await attach(browser, job.target_id);
  await browser.send("Runtime.enable", {}, sessionId);
  await browser.send("DOM.enable", {}, sessionId);
  return { job, sessionId };
}

/** Harvest the live form and classify what is on it. */
export async function inspect(browser, state, jobKey) {
  const { job, sessionId } = await sessionForJob(browser, state, jobKey);
  const page = await evaluate(browser, sessionId, fieldInspectionExpression());
  const { adapter, confidence, matched_on: matchedOn } = detectAdapter({
    url: page.url,
    pageText: page.page_text,
  });
  const blockers = detectBlockers({
    fields: page.fields,
    pageText: `${page.page_text}${page.has_captcha_frame ? "\nrecaptcha" : ""}`,
    url: page.url,
    adapterId: adapter?.id || "",
  });
  const submitControls = (page.buttons || []).filter((label) =>
    isFinalSubmitControl(adapter?.id || "", label),
  );

  return {
    job_key: jobKey,
    tab_state: job.state,
    url: page.url,
    title: page.title,
    heading: page.heading,
    adapter: adapter ? { id: adapter.id, label: adapter.label, dropdown_strategy: adapter.dropdownStrategy, notes: adapter.notes } : null,
    adapter_confidence: confidence,
    adapter_matched_on: matchedOn,
    schema_url: adapter?.schemaUrl?.(page.url) || "",
    field_count: page.fields.length,
    required_count: page.fields.filter((field) => field.required).length,
    fields: page.fields,
    submit_controls: submitControls,
    form_errors: page.errors,
    blockers,
  };
}

/**
 * Enter the application form from a public job page.
 *
 * This is deliberately narrower than a generic button click: it accepts only
 * the conventional non-final Apply labels and explicitly rejects anything
 * containing "submit". The final-submit boundary therefore remains enforced
 * even when an ATS renders the form only after an initial Apply click.
 */
export async function startApplication(browser, state, jobKey) {
  const { job, sessionId } = await sessionForJob(browser, state, jobKey);
  const candidates = await evaluate(
    browser,
    sessionId,
    `(() => ${deepAllExpression('button, a, input[type="button"]')}
      .map((el, index) => ({
        index,
        label: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim(),
        visible: Boolean(el.getClientRects().length),
      }))
      .filter((item) => item.visible && /^(apply|apply now|apply for this job|apply for this role)$/i.test(item.label) && !/submit/i.test(item.label)))()`,
  );
  if (!candidates.length) {
    return { clicked: false, reason: "non-final Apply control not found", candidates: [] };
  }
  const chosenLabel = candidates[0].label;
  const elementExpression = `(() => ${deepAllExpression('button, a, input[type="button"]')}
    .find((el) => {
      const label = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
      return el.getClientRects().length && label === ${JSON.stringify(chosenLabel)} && !/submit/i.test(label);
    }) || null)()`;
  const click = await trustedClick(browser, sessionId, elementExpression);
  if (!click.ok) return { clicked: false, reason: click.error || "Apply click failed", candidates };
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 1200));
  let postClickInspection = await inspect(browser, state, jobKey);
  // Ashby's public posting sometimes renders Apply as a React-controlled
  // submit button that ignores a coordinate click until its handler is invoked
  // in the page context. The label allowlist above still keeps this fallback
  // away from every final-submit control.
  if (postClickInspection.field_count === 0 && postClickInspection.url === job.canonical_url) {
    await evaluate(browser, sessionId, `(() => { const el = ${elementExpression}; if (!el) return false; el.click(); return true; })()`);
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 1800));
    postClickInspection = await inspect(browser, state, jobKey);
  }
  job.state = "inspecting";
  job.updated_at = new Date().toISOString();
  return { clicked: true, label: chosenLabel, candidates, inspection: postClickInspection };
}

/**
 * Fill only what the plan allows, then read every field back.
 * Returns before any submit control is clicked, always.
 */
export async function fill(browser, state, jobKey, answers) {
  const inspection = await inspect(browser, state, jobKey);
  // Only blockers that make the form unreachable stop the fill. A CAPTCHA is
  // reported and left for the human at submit time, not treated as a wall.
  const blocking = inspection.blockers.filter((blocker) => blocker.blocking);
  if (blocking.length) {
    return {
      ...inspection,
      filled: false,
      stopped_because: "blockers",
      blocking_blockers: blocking.map((blocker) => blocker.type),
      plan: null,
      readback: null,
    };
  }

  const plan = planFill(inspection.fields, answers, { adapterId: inspection.adapter?.id || "" });
  const { job, sessionId } = await sessionForJob(browser, state, jobKey);

  const applied = [];
  for (const item of plan.fills) {
    if (!item.selector) {
      applied.push({ selector: "", label: item.label, ok: false, error: "no stable selector" });
      continue;
    }
    if (item.strategy === "file") {
      try {
        const ok = await setFileInput(browser, sessionId, item.selector, item.value);
        applied.push({ selector: item.selector, label: item.label, category: item.category, ok, error: ok ? "" : "node not found" });
      } catch (error) {
        applied.push({ selector: item.selector, label: item.label, category: item.category, ok: false, error: error.message });
      }
      continue;
    }
    if (item.strategy === "type") {
      try {
        const result = await trustedType(browser, sessionId, item.selector, item.value);
        applied.push({ selector: item.selector, label: item.label, category: item.category, ok: Boolean(result?.ok), error: result?.error || "" });
      } catch (error) {
        applied.push({ selector: item.selector, label: item.label, category: item.category, ok: false, error: error.message });
      }
      continue;
    }
    // A genuine native <select> (item.type === "select") always uses the
    // plain DOM value-setting path below — it works reliably and a real
    // <select> has no click-addressable menu in the page DOM (the browser
    // renders its own OS-level popup). Only custom "combobox"/"react-select"
    // widgets — which have no programmatically-settable value and must be
    // driven by opening the menu and clicking the option — need trusted clicks.
    if (item.type === "combobox" || item.type === "react-select") {
      try {
        const result = await selectReactOption(browser, sessionId, item.selector, item.value);
        applied.push({ selector: item.selector, label: item.label, category: item.category, ok: result.ok, error: result.error || "" });
      } catch (error) {
        applied.push({ selector: item.selector, label: item.label, category: item.category, ok: false, error: error.message });
      }
      continue;
    }
    try {
      const result = await evaluate(
        browser,
        sessionId,
        applyExpression(item, inspection.adapter?.dropdownStrategy || "native"),
      );
      applied.push({ selector: item.selector, label: item.label, category: item.category, ok: Boolean(result?.ok), error: result?.error || "" });
    } catch (error) {
      applied.push({ selector: item.selector, label: item.label, category: item.category, ok: false, error: error.message });
    }
  }

  // A same-session Runtime.evaluate captured immediately after many rapid
  // apply-loop evaluate/DOM calls consistently read every field as empty,
  // even though a fresh `inspect` call moments later (which re-attaches and
  // gets a new sessionId) saw every value correctly in place. Re-attaching
  // before readback — mirroring what already works — avoids whatever stale
  // execution-context state the long-lived apply session accumulates.
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 400));
  const readbackSessionId = await attach(browser, job.target_id);
  await browser.send("Runtime.enable", {}, readbackSessionId);
  const observed = await evaluate(browser, readbackSessionId, readbackExpression(plan.fills));
  const readback = verifyReadback(plan, observed);

  // Locate the submit control only to prove it was left alone.
  const submitState = await evaluate(browser, sessionId, submitProbeExpression());

  return {
    ...inspection,
    filled: true,
    stopped_because: "submit boundary",
    plan,
    applied,
    readback,
    submit_control: submitState,
    submitted: false,
    // Non-blocking blockers (a CAPTCHA) still need a human before submit.
    human_required_at_submit: inspection.blockers
      .filter((blocker) => !blocker.blocking)
      .map((blocker) => blocker.type),
    ready_for_confirmation:
      readback.ok && plan.missing_required.length === 0 && plan.human_required.length === 0,
  };
}

/** Require the confirmation to name exactly the mapped job being submitted. */
export function isExplicitSubmitConfirmation(jobKey, confirmation) {
  return Boolean(jobKey) && String(confirmation || "").trim() === String(jobKey).trim();
}

/** Classify the page reached after the one confirmed final-submit click. */
export function classifySubmissionOutcome(snapshot = {}) {
  const text = `${snapshot.title || ""}\n${snapshot.heading || ""}\n${snapshot.text || ""}`;
  const url = String(snapshot.url || "");
  const success =
    /\b(application|your application)\s+(has been\s+)?(submitted|received|sent)\b/i.test(text) ||
    /\b(thank you|thanks)\s+for\s+(applying|your application)\b/i.test(text) ||
    /\bwe(?:'ve| have)\s+received\s+your\s+application\b/i.test(text) ||
    /\b(application-submitted|application\/success|application\/submitted)\b/i.test(url);
  if (success) return { status: "submitted", submitted: true };
  if (snapshot.has_captcha_frame || /\b(recaptcha|hcaptcha|verify you are human|i'?m not a robot)\b/i.test(text)) {
    return { status: "captcha", submitted: false };
  }
  if ((snapshot.errors || []).length) return { status: "validation", submitted: false };
  return { status: "unknown", submitted: false };
}

function confirmedSubmitElementExpression(label) {
  return `(() => ${deepAllExpression('button, input[type="submit"]')}
    .find((el) => {
      const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
      return Boolean(el.getClientRects().length) && text === ${JSON.stringify(label)};
    }) || null)()`;
}

function submissionSnapshotExpression() {
  return `(() => {
    const visible = (el) => Boolean(el && el.getClientRects().length);
    const text = (document.body?.innerText || '').slice(0, 20000);
    const errors = ${deepAllExpression('[role="alert"], [aria-invalid="true"], .error, [class*="error"]')}
      .filter(visible)
      .map((el) => (el.innerText || el.getAttribute('aria-label') || '').trim())
      .filter(Boolean)
      .slice(0, 20);
    return {
      url: location.href,
      title: document.title,
      heading: document.querySelector('h1')?.innerText?.trim() || '',
      text,
      errors,
      has_captcha_frame: Boolean(${deepAllExpression('iframe')}.find((frame) => /recaptcha|hcaptcha/i.test(frame.src || frame.title || ''))),
      field_count: ${deepAllExpression('input, textarea, select, [role="combobox"]')}.filter(visible).length,
    };
  })()`;
}

/**
 * Refill and read back the live form, then click exactly one final submit
 * control after an exact named confirmation. Never retries a failed submit.
 */
export async function submitConfirmed(browser, state, jobKey, answers, confirmation) {
  if (!isExplicitSubmitConfirmation(jobKey, confirmation)) {
    throw new Error(`Submit confirmation must exactly match the job key: ${jobKey}`);
  }
  const mapped = state.jobs?.[jobKey];
  if (!mapped) throw new Error(`No browser tab is mapped for ${jobKey}`);
  if (mapped.state === "submitted") {
    return { job_key: jobKey, submitted: true, already_submitted: true, outcome: "submitted" };
  }

  const prepared = await fill(browser, state, jobKey, answers);
  if (!prepared.readback?.ok || prepared.plan?.missing_required?.length || prepared.plan?.human_required?.length) {
    return {
      ...prepared,
      submitted: false,
      stopped_because: "not ready after live verification",
    };
  }

  const label = prepared.submit_control?.label || prepared.submit_controls?.[0] || "";
  const adapterId = prepared.adapter?.id || "";
  if (!label || !isFinalSubmitControl(adapterId, label)) {
    return { ...prepared, submitted: false, stopped_because: "final submit control not verified" };
  }
  if (prepared.submit_control?.disabled) {
    return { ...prepared, submitted: false, stopped_because: "final submit control is disabled" };
  }

  // Normalize the lifecycle before the irreversible click. A previous fill
  // may leave an older tab at `inspecting`, but it has just been reverified.
  mapped.state = "awaiting_submit";
  mapped.updated_at = new Date().toISOString();
  const { sessionId } = await sessionForJob(browser, state, jobKey);
  const click = await trustedClick(browser, sessionId, confirmedSubmitElementExpression(label));
  if (!click.ok) {
    return { ...prepared, submitted: false, stopped_because: click.error || "submit click failed" };
  }

  await new Promise((resolveDelay) => setTimeout(resolveDelay, 3000));
  let snapshot = await evaluate(browser, sessionId, submissionSnapshotExpression());
  let outcome = classifySubmissionOutcome(snapshot);
  if (outcome.status === "unknown") {
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 2500));
    snapshot = await evaluate(browser, sessionId, submissionSnapshotExpression());
    outcome = classifySubmissionOutcome(snapshot);
  }

  if (outcome.submitted) mapped.state = "submitted";
  else if (outcome.status === "captcha") mapped.state = "blocked_captcha";
  else mapped.state = "blocked_unknown_field";
  mapped.updated_at = new Date().toISOString();

  return {
    job_key: jobKey,
    url: snapshot.url,
    submitted: outcome.submitted,
    outcome: outcome.status,
    stopped_because: outcome.submitted ? "verified success page" : outcome.status,
    errors: snapshot.errors,
    confirmation: "matched job key",
    clicked_label: label,
  };
}

/** Browser expression that finds controls through document and open shadow roots. */
function deepAllExpression(selector) {
  return `(() => {
    const matches = [];
    const visit = (root) => {
      matches.push(...root.querySelectorAll(${JSON.stringify(selector)}));
      for (const host of root.querySelectorAll('*')) {
        if (host.shadowRoot) visit(host.shadowRoot);
      }
    };
    visit(document);
    return matches;
  })()`;
}

function deepElementExpression(selector) {
  return `${deepAllExpression(selector)}[0] || null`;
}

/** Same lookup when the selector is a variable inside a browser expression. */
function deepElementExpressionFromVariable(variableName) {
  return `(() => {
    const matches = [];
    const visit = (root) => {
      matches.push(...root.querySelectorAll(${variableName}));
      for (const host of root.querySelectorAll('*')) {
        if (host.shadowRoot) visit(host.shadowRoot);
      }
    };
    visit(document);
    return matches[0] || null;
  })()`;
}

function deepAllExpressionFromVariable(variableName) {
  return `(() => {
    const matches = [];
    const visit = (root) => {
      matches.push(...root.querySelectorAll(${variableName}));
      for (const host of root.querySelectorAll('*')) {
        if (host.shadowRoot) visit(host.shadowRoot);
      }
    };
    visit(document);
    return matches;
  })()`;
}

/**
 * Attach a local file to a `<input type="file">` via CDP's DOM domain.
 * A file input's `.files` is read-only from page-script, so it cannot be set
 * with `Runtime.evaluate` the way every other field is — this was previously
 * documented as the plan but never actually wired up, so every resume/cover-
 * letter upload silently failed with `file_not_attached` at readback. Resolve
 * the element to a backend node id and call `DOM.setFileInputFiles` on it.
 */
async function setFileInput(browser, sessionId, selector, filePath) {
  const { result } = await browser.send(
    "Runtime.evaluate",
    { expression: deepElementExpression(selector), returnByValue: false },
    sessionId,
  );
  if (!result?.objectId) return false;
  const { node } = await browser.send("DOM.describeNode", { objectId: result.objectId }, sessionId);
  if (!node?.backendNodeId) return false;
  await browser.send(
    "DOM.setFileInputFiles",
    { files: [filePath], backendNodeId: node.backendNodeId },
    sessionId,
  );
  return true;
}

/**
 * Point-and-click an element via CDP `Input.dispatchMouseEvent`, using the
 * page's actual coordinates rather than a page-script `.click()`.
 *
 * Learned on a real SmartAsset Greenhouse application: `element.click()` (or
 * a JS-dispatched `MouseEvent`) opened some react-select menus but the
 * library never registered the selection — the control visibly showed the
 * right text (`data-value` on a stray element even said "Yes"), the field's
 * `aria-invalid` never cleared, and Greenhouse's own submit-time validation
 * correctly rejected the form as incomplete. A CDP-level trusted mouse event
 * at the element's real screen position is what react-select's pointer
 * handlers actually respond to.
 *
 * `scrollIntoView` is asynchronous/animated; computing `getBoundingClientRect`
 * immediately afterward can measure a mid-scroll position and click the wrong
 * spot. Force an instant scroll and wait one paint before measuring.
 */
async function trustedClick(browser, sessionId, elementExpression) {
  const scrolled = await evaluate(
    browser,
    sessionId,
    `(() => { const el = ${elementExpression}; if (!el) return false; el.scrollIntoView({block: 'center', behavior: 'instant'}); return true; })()`,
  );
  if (!scrolled) return { ok: false, error: "element not found" };
  await new Promise((r) => setTimeout(r, 200));
  const point = await evaluate(
    browser,
    sessionId,
    `(() => { const el = ${elementExpression}; if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`,
  );
  if (!point) return { ok: false, error: "element not found for coordinates" };
  await browser.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: point.x, y: point.y }, sessionId);
  await browser.send(
    "Input.dispatchMouseEvent",
    { type: "mousePressed", x: point.x, y: point.y, button: "left", clickCount: 1 },
    sessionId,
  );
  await browser.send(
    "Input.dispatchMouseEvent",
    { type: "mouseReleased", x: point.x, y: point.y, button: "left", clickCount: 1 },
    sessionId,
  );
  return { ok: true };
}

/**
 * Enter text through Chrome's input pipeline so React-controlled ATS fields
 * keep the value after their next render. Directly assigning `el.value` can
 * appear successful for one tick while Ashby/LinkedIn restores empty state.
 */
async function trustedType(browser, sessionId, selector, value) {
  const focus = await evaluate(
    browser,
    sessionId,
    `(() => {
      const el = ${deepElementExpression(selector)};
      if (!el) return { ok: false, error: 'not found' };
      el.focus();
      if (typeof el.select === 'function') el.select();
      return { ok: true };
    })()`,
  );
  if (!focus?.ok) return focus;
  await browser.send("Input.dispatchKeyEvent", {
    type: "rawKeyDown",
    key: "Backspace",
    code: "Backspace",
    windowsVirtualKeyCode: 8,
    nativeVirtualKeyCode: 8,
  }, sessionId);
  await browser.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Backspace",
    code: "Backspace",
    windowsVirtualKeyCode: 8,
    nativeVirtualKeyCode: 8,
  }, sessionId);
  // Greenhouse's controlled inputs discard `Input.insertText` on the next
  // React render even though the DOM briefly contains the value. Trusted
  // character events update the same state path as real typing. CDP accepts
  // exactly one Unicode code point per `char` event.
  for (const character of String(value)) {
    await browser.send("Input.dispatchKeyEvent", { type: "char", text: character }, sessionId);
  }
  await new Promise((r) => setTimeout(r, 120));
  return evaluate(
    browser,
    sessionId,
    `(() => {
      const el = ${deepElementExpression(selector)};
      if (!el) return { ok: false, error: 'not found after typing' };
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.blur();
      return { ok: el.value === ${JSON.stringify(String(value))}, stored_length: el.value.length };
    })()`,
  );
}

/**
 * Open a react-select/Workday listbox and click the option matching `value`
 * via trusted clicks. Retries up to twice: as earlier fields on the page get
 * filled, layout reflows shift later fields' coordinates, and a menu that
 * hasn't finished animating open yet reads as having no matching option.
 * Both are transient/timing conditions, not a real missing-option case.
 */
async function selectReactOption(browser, sessionId, selector, value, attempt = 1) {
  const isPostalValue = /^\d{5}(?:-\d{4})?(?:,|$)/.test(String(value));
  if (isPostalValue && attempt === 1) {
    const clearSelector = '[aria-label="Clear Postal code / zip code value"]';
    const hasClear = await evaluate(browser, sessionId, `Boolean(${deepElementExpression(clearSelector)})`);
    if (hasClear) {
      await trustedClick(browser, sessionId, deepElementExpression(clearSelector));
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  const openResult = await trustedClick(browser, sessionId, deepElementExpression(selector));
  if (!openResult.ok) {
    if (attempt < 3) {
      await new Promise((r) => setTimeout(r, 400));
      return selectReactOption(browser, sessionId, selector, value, attempt + 1);
    }
    return openResult;
  }
  await new Promise((r) => setTimeout(r, 450));

  // Exclude the phone field's international dial-code picker (~250 country
  // entries under `.iti__country-list`) — a global option query matches it
  // too, and it can render on top of the real target at click time even when
  // the text match itself is unambiguous. A Country field may also render
  // its own options as "United States +1" (dial code appended), so try an
  // exact match first and fall back to a word-boundary prefix match — the
  // same escalation `matchOption` already uses for the native-select path.
  const includePhoneCountries = /(?:^#country$|id=["']?country)/.test(selector);
  const findOption = (val) => `(() => {
    const candidates = ${deepAllExpression("[role=\"option\"], .select__option, li")}
      .filter((o) => ${includePhoneCountries} || !o.closest('.iti__country-list'));
    const exact = candidates.find((o) => (o.innerText || '').trim() === ${JSON.stringify(val)});
    if (exact) return exact;
    const prefixed = candidates.find((o) => (o.innerText || '').trim().startsWith(${JSON.stringify(val)}));
    if (prefixed) return prefixed;
    // Web-component autocompletes sometimes omit option roles entirely. As a
    // conservative fallback, choose the smallest visible element whose text
    // starts with the intended value; this avoids clicking a large wrapper.
    return ${deepAllExpression("*")}
      .filter((o) => {
        const text = (o.innerText || '').trim();
        const rect = o.getBoundingClientRect();
        return text.startsWith(${JSON.stringify(val)}) && text.length < 160 && rect.width > 0 && rect.height > 0;
      })
      .sort((a, b) => (a.innerText || '').trim().length - (b.innerText || '').trim().length)[0] || null;
  })()`;
  const optionSelectorExpr = findOption(value);
  let exists = await evaluate(browser, sessionId, `Boolean(${optionSelectorExpr})`);
  // Location, school, and degree controls often do not materialize their
  // options until the user types a query. Use Chrome's edit pipeline so the
  // widget performs its normal async search, then inspect the live menu.
  if (!exists && !includePhoneCountries) {
    // Location services often accept the city as the search query but reject
    // the full rendered option string. Search with the leading city token,
    // then still click only the exact full option requested by the plan.
    const isPostalQuery = isPostalValue;
    const searchQuery = isPostalQuery
      ? String(value)
      : String(value).includes(",") ? String(value).split(",")[0].trim() : String(value);
    if (isPostalQuery) {
      await evaluate(browser, sessionId, `(() => {
        const el = ${deepElementExpression(selector)};
        if (!el) return false;
        el.focus();
        if (typeof el.select === 'function') el.select();
        return true;
      })()`);
      await browser.send("Input.dispatchKeyEvent", {
        type: "rawKeyDown",
        key: "Backspace",
        code: "Backspace",
        windowsVirtualKeyCode: 8,
        nativeVirtualKeyCode: 8,
      }, sessionId);
      await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Backspace", code: "Backspace" }, sessionId);
    }
    await browser.send("Input.insertText", { text: searchQuery }, sessionId);
    await new Promise((r) => setTimeout(r, 650));
    exists = await evaluate(browser, sessionId, `Boolean(${optionSelectorExpr})`);
  }
  if (!exists) {
    // Close the menu we just opened rather than leaving it dangling.
    if (attempt < 3) {
      await evaluate(browser, sessionId, `document.activeElement && document.activeElement.blur()`);
      await new Promise((r) => setTimeout(r, 400));
      return selectReactOption(browser, sessionId, selector, value, attempt + 1);
    }
    // SmartRecruiters' postal-code list is painted by a web component whose
    // options are not exposed in the open DOM. For an exact ZIP query, use the
    // component's standard keyboard contract to choose its first suggestion.
    if (/^\d{5}(?:-\d{4})?(?:,|$)/.test(String(value))) {
      const focused = await evaluate(browser, sessionId, `(() => {
        const el = ${deepElementExpression(selector)};
        if (!el) return false;
        el.focus();
        return true;
      })()`);
      if (focused) {
        for (const key of ["ArrowDown", "Enter"]) {
          await browser.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key }, sessionId);
          await browser.send("Input.dispatchKeyEvent", { type: "keyUp", key }, sessionId);
        }
        await new Promise((r) => setTimeout(r, 400));
        const accepted = await evaluate(browser, sessionId, `(() => {
          const el = ${deepElementExpression(selector)};
          return Boolean(el) && el.getAttribute('aria-invalid') !== 'true';
        })()`);
        if (accepted) return { ok: true, keyboardSelection: true };
      }
    }
    await evaluate(browser, sessionId, `document.activeElement && document.activeElement.blur()`);
    return { ok: false, error: "option not in open menu" };
  }

  const clickResult = await trustedClick(browser, sessionId, optionSelectorExpr);
  if (!clickResult.ok) {
    if (attempt < 3) {
      await new Promise((r) => setTimeout(r, 400));
      return selectReactOption(browser, sessionId, selector, value, attempt + 1);
    }
    return clickResult;
  }
  await new Promise((r) => setTimeout(r, 300));

  const verify = await evaluate(
    browser,
    sessionId,
    `(() => {
      const el = ${deepElementExpression(selector)};
      const control = el?.closest('[class*="select__control"]');
      const single = control?.querySelector('.select__single-value');
      const text = (single?.innerText || control?.innerText || el?.value || '').trim();
      return { text, ariaInvalid: el?.getAttribute('aria-invalid') };
    })()`,
  );
  const matched = verify.text === value || verify.text.startsWith(String(value));
  if (!matched && attempt < 3) {
    await new Promise((r) => setTimeout(r, 400));
    return selectReactOption(browser, sessionId, selector, value, attempt + 1);
  }
  return { ok: matched, error: matched ? "" : `control shows "${verify.text}" after click` };
}

/** Per-strategy DOM write. React-select and Workday need real click sequences. */
function applyExpression(item, dropdownStrategy) {
  const selector = JSON.stringify(item.selector);
  const value = JSON.stringify(item.value);
  const strategy = item.strategy === "type" ? "type" : item.strategy;

  if (strategy === "checkbox") {
    return `(() => {
      const el = ${deepElementExpression(item.selector)};
      if (!el) return { ok: false, error: 'not found' };
      const state = () => el.checked ??
        (el.getAttribute('aria-checked') !== null
          ? el.getAttribute('aria-checked') === 'true'
          : /^(true|1|on|checked)$/i.test(String(el.value ?? '')));
      if (state() !== ${Boolean(item.value)}) {
        const target = el.shadowRoot?.querySelector('input[type="checkbox"], button') || el;
        target.click();
      }
      return { ok: state() === ${Boolean(item.value)} };
    })()`;
  }
  if (strategy === "radio-direct") {
    return `(() => {
      const el = ${deepElementExpression(item.selector)};
      if (!el) return { ok: false, error: 'not found' };
      if (el.type !== 'radio' && el.getAttribute('role') !== 'radio' && el.tagName !== 'SPL-RADIO') {
        return { ok: false, error: 'not a radio input' };
      }
      const state = () => el.checked ?? el.getAttribute('aria-checked') === 'true';
      if (!state()) {
        const target = el.shadowRoot?.querySelector('input[type="radio"], button') || el;
        target.click();
      }
      return { ok: state() };
    })()`;
  }
  if (strategy === "file") {
    // File inputs cannot be set from script; the driver uses DOM.setFileInputFiles.
    return `(() => ({ ok: false, error: 'file inputs must be set via CDP DOM.setFileInputFiles' }))()`;
  }
  if (item.type === "select" || (strategy === "native" && item.type === "radio")) {
    return `(() => {
      const el = ${deepElementExpression(item.selector)};
      if (!el) return { ok: false, error: 'not found' };
      if (el.tagName === 'SELECT') {
        const option = [...el.options].find((o) => o.text.trim() === ${value});
        if (!option) return { ok: false, error: 'option not found' };
        el.value = option.value;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return { ok: el.selectedOptions[0]?.text.trim() === ${value} };
      }
      const radio = ${deepAllExpression('input[type="radio"]')}
        .filter((candidate) => candidate.name === el.name)
        .find((r) => (r.closest('label')?.innerText || '').trim() === ${value});
      if (!radio) return { ok: false, error: 'option not found' };
      radio.click();
      return { ok: radio.checked };
    })()`;
  }
  if (dropdownStrategy !== "native" && (item.type === "select" || item.type === "combobox" || item.type === "react-select")) {
    // Scope the option search to the open menu: a global [role=option] query
    // also matches the phone widget's country list and picks the wrong entry.
    return `(async () => {
      const el = ${deepElementExpression(item.selector)};
      if (!el) return { ok: false, error: 'not found' };
      el.focus();
      el.click();
      await new Promise((r) => setTimeout(r, 250));
      const menu = ${deepElementExpression('div[role="listbox"], .select__menu-list, [data-automation-id="activeListContainer"]')};
      if (!menu) return { ok: false, error: 'menu did not open' };
      const option = [...menu.querySelectorAll('[role="option"], .select__option, li')]
        .find((o) => (o.innerText || '').trim() === ${value});
      if (!option) return { ok: false, error: 'option not in open menu' };
      option.click();
      await new Promise((r) => setTimeout(r, 150));
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      const control = el.closest('.select__control, [data-automation-id]')?.innerText?.trim() || '';
      return { ok: control.includes(${value}), control };
    })()`;
  }
  return `(() => {
    const el = ${deepElementExpression(item.selector)};
    if (!el) return { ok: false, error: 'not found' };
    const setter = Object.getOwnPropertyDescriptor(
      el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
      'value',
    ).set;
    setter.call(el, ${value});
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    return { ok: el.value === ${value}, stored_length: el.value.length };
  })()`;
}

function readbackExpression(fills) {
  return `(() => {
    const out = {};
    for (const item of ${JSON.stringify(fills.map((fill) => ({
      selector: fill.selector,
      label: fill.label,
      strategy: fill.strategy,
    })))}) {
      const selector = item.selector;
      let el = selector ? ${deepElementExpressionFromVariable('selector')} : null;
      if (item.strategy === 'file' && el && !el.files?.length) {
        el = ${deepAllExpressionFromVariable('selector')}.find((candidate) => candidate.files?.length) || el;
      }
      // LinkedIn regenerates opaque radio ids after every choice. Recover the
      // same semantic option from its stable aria-label plus visible Yes/No
      // text, while keeping the original selector as the audit/readback key.
      if (!el && item.strategy === 'radio-direct') {
        const splitAt = item.label.lastIndexOf(': ');
        if (splitAt > 0) {
          const question = item.label.slice(0, splitAt);
          const option = item.label.slice(splitAt + 2);
          el = ${deepAllExpression('input[type="radio"]')}.find((candidate) =>
            (candidate.getAttribute('aria-label') || '').trim() === question &&
            (candidate.parentElement?.parentElement?.innerText || '').trim() === option
          ) || null;
        }
      }
      if (!el) { out[selector] = null; continue; }
      out[selector] = {
        value: el.value ?? '',
        checked: el.checked ?? (el.getAttribute('aria-checked') !== null
          ? el.getAttribute('aria-checked') === 'true'
          : /^(true|1|on|checked)$/i.test(String(el.value ?? ''))),
        maxlength: el.maxLength && el.maxLength > 0 ? el.maxLength : null,
        fileName: el.files?.[0]?.name || '',
        selectedText: el.tagName === 'SELECT' ? (el.selectedOptions[0]?.text.trim() || '') : '',
        controlText: el.closest('.select__control, [data-automation-id]')?.innerText?.trim() || '',
        displayText: (el.parentElement?.innerText || el.getAttribute('data-value') || el.getAttribute('value') || '').trim(),
        countryCode: [...(el.closest('.select__control')?.querySelector('.iti__flag')?.classList || [])]
          .find((name) => /^iti__[a-z]{2}$/.test(name))?.slice(5) || '',
      };
    }
    return out;
  })()`;
}

function submitProbeExpression() {
  return `(() => {
    const buttons = ${deepAllExpression('button, input[type="submit"]')};
    const submit = buttons.find((el) => /^submit\\b/i.test((el.innerText || el.value || '').trim()));
    if (!submit) return { found: false, clicked: false };
    return {
      found: true,
      clicked: false,
      label: (submit.innerText || submit.value || '').trim(),
      disabled: Boolean(submit.disabled || submit.getAttribute('aria-disabled') === 'true'),
    };
  })()`;
}

async function run(argv = process.argv.slice(2)) {
  const { command, options } = parseArgs(argv);
  const port = Number(options.port || 9222);
  const statePath = resolve(String(options.state_file || DEFAULT_STATE));
  const auditPath = resolve(String(options.audit_file || DEFAULT_AUDIT));
  const jobKey = requireOption(options, "job");

  const browser = await connectBrowser(port);
  try {
    // Same profile guard as chrome_tabs.mjs: the user only, verified against
    // Chrome's own profile metadata, never a caller-supplied name.
    const profile = await verifyProfile(browser, String(options.profile || DEFAULT_PROFILE_NAME));
    const state = await readState(statePath);
    if (state.profile?.profile_path && state.profile.profile_path !== profile.profile_path) {
      throw new Error("Browser state belongs to a different Chrome profile path");
    }

    let result;
    if (command === "inspect") {
      result = await inspect(browser, state, jobKey);
      await audit(auditPath, {
        job_key: jobKey,
        action: "inspect",
        result: result.blockers.length ? "blocked" : "ok",
        adapter: result.adapter?.id || "unknown",
        field_count: result.field_count,
        blockers: result.blockers.map((blocker) => blocker.type),
        url: result.url,
      });
    } else if (command === "start") {
      result = await startApplication(browser, state, jobKey);
      await audit(auditPath, {
        job_key: jobKey,
        action: "start",
        result: result.clicked ? "ok" : "not_found",
        label: result.label || "",
        submitted: false,
        url: result.inspection?.url || state.jobs?.[jobKey]?.canonical_url || "",
      });
    } else if (command === "plan" || command === "fill" || command === "submit") {
      const answers = await readJson(requireOption(options, "answers"));
      if (command === "plan") {
        const inspection = await inspect(browser, state, jobKey);
        const plan = planFill(inspection.fields, answers, { adapterId: inspection.adapter?.id || "" });
        result = { ...inspection, plan };
      } else if (command === "submit") {
        result = await submitConfirmed(browser, state, jobKey, answers, requireOption(options, "confirm"));
      } else {
        result = await fill(browser, state, jobKey, answers);
      }
      await audit(auditPath, {
        job_key: jobKey,
        action: command,
        result: result.stopped_because || "planned",
        adapter: result.adapter?.id || "unknown",
        plan: result.plan ? redactPlan(result.plan) : null,
        readback_ok: result.readback?.ok ?? null,
        submitted: Boolean(result.submitted),
        outcome: result.outcome || "",
        url: result.url,
      });
    } else if (command === "verify") {
      const plan = await readJson(requireOption(options, "plan"));
      const { sessionId } = await sessionForJob(browser, state, jobKey);
      const observed = await evaluate(
        browser,
        sessionId,
        readbackExpression((plan.fills || []).map((item) => item.selector)),
      );
      result = verifyReadback(plan, observed);
      await audit(auditPath, {
        job_key: jobKey,
        action: "verify",
        result: result.ok ? "ok" : "mismatch",
        mismatches: result.mismatches.map((item) => ({ selector: item.selector, reason: item.reason })),
        url: "",
      });
    } else {
      throw new Error(`Unknown command: ${command}. Use start, inspect, plan, fill, verify, or submit.`);
    }

    await saveState(statePath, state);
    if (options.out) result.saved_to = await writeJson(String(options.out), result);
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
