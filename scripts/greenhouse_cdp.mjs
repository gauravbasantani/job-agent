#!/usr/bin/env node

import { writeFile } from "node:fs/promises";

const mode = process.argv[2] ?? "submit";
const targetUrlPart = process.argv[3];
const debugPort = Number(process.argv[4] ?? 9222);
const screenshotPath = process.argv[5] ?? "/private/tmp/greenhouse-submit.png";

if (!targetUrlPart) {
  throw new Error("Usage: greenhouse_cdp.mjs <mode> <target-url-part> [debug-port] [screenshot-path]");
}

const targets = await fetch(`http://127.0.0.1:${debugPort}/json/list`).then((response) => response.json());
const target = targets.find((item) => item.type === "page" && item.url.includes(targetUrlPart));
if (!target) throw new Error(`Greenhouse Chrome tab not found for ${targetUrlPart}`);

const socket = new WebSocket(target.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();

socket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (!message.id || !pending.has(message.id)) return;
  const { resolve, reject } = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) reject(new Error(JSON.stringify(message.error)));
  else resolve(message.result);
};

await new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});

function send(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evaluate(expression) {
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  }
  return result.result.value;
}

async function screenshot(path) {
  await send("Page.enable");
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await writeFile(path, Buffer.from(shot.data, "base64"));
  return path;
}

await send("Runtime.enable");
await send("DOM.enable");

if (mode === "screenshot") {
  process.stdout.write(await screenshot(screenshotPath));
} else if (mode === "submit") {
  const preflight = await evaluate(`(() => {
    const value = (selector) => document.querySelector(selector)?.value?.trim() || "";
    const pageText = document.body.innerText;
    const submit = [...document.querySelectorAll('button, input[type="submit"]')].find((element) =>
      (element.innerText || element.value || "").trim().toLowerCase() === "submit application"
    );
    const errors = [...document.querySelectorAll('[role="alert"], .field-error, .error-message, .input-error, [aria-invalid="true"]')]
      .map((element) => element.innerText.trim())
      .filter(Boolean);
    const required = {
      firstName: value("#first_name"),
      lastName: value("#last_name"),
      email: value("#email"),
      phone: value("#phone"),
      linkedin: value("#question_6757241009"),
      website: value("#question_6757242009")
    };
    return {
      url: location.href,
      title: document.title,
      required,
      resumePresent: pageText.includes("Your_Name_Product_Designer_Resume.pdf"),
      coverLetterPresent: pageText.includes("Your_Name_Product_Designer_Cover_Letter.pdf"),
      submitFound: Boolean(submit),
      submitDisabled: submit ? Boolean(submit.disabled || submit.getAttribute("aria-disabled") === "true") : true,
      errors
    };
  })()`);

  const missing = Object.entries(preflight.required).filter(([, value]) => !value).map(([key]) => key);
  if (missing.length || !preflight.resumePresent || !preflight.coverLetterPresent || !preflight.submitFound || preflight.submitDisabled || preflight.errors.length) {
    throw new Error(`Greenhouse submit preflight failed: ${JSON.stringify({ ...preflight, missing })}`);
  }

  await evaluate(`(() => {
    const submit = [...document.querySelectorAll('button, input[type="submit"]')].find((element) =>
      (element.innerText || element.value || "").trim().toLowerCase() === "submit application"
    );
    submit.click();
    return true;
  })()`);

  let result;
  for (let attempt = 0; attempt < 45; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    result = await evaluate(`(() => {
      const text = document.body.innerText;
      const submitPresent = [...document.querySelectorAll('button, input[type="submit"]')].some((element) =>
        (element.innerText || element.value || "").trim().toLowerCase() === "submit application"
      );
      const errors = [...document.querySelectorAll('[role="alert"], .field-error, .error-message, .input-error, [aria-invalid="true"]')]
        .map((element) => element.innerText.trim())
        .filter(Boolean);
      return {
        url: location.href,
        title: document.title,
        text: text.slice(0, 3000),
        submitPresent,
        errors,
        confirmed: /thank you|application (has been )?(received|submitted)|thanks for applying/i.test(text)
      };
    })()`);
    if (result.confirmed || result.errors.length) break;
  }

  const savedScreenshot = await screenshot(screenshotPath);
  process.stdout.write(JSON.stringify({ preflight, result, screenshot: savedScreenshot }, null, 2));
} else {
  throw new Error(`Unknown mode: ${mode}`);
}

socket.close();
