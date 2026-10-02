#!/usr/bin/env node

import { readFile, writeFile } from "node:fs/promises";

const mode = process.argv[2] ?? "inspect";
const targetUrlPart = process.argv[3];
const debugPort = Number(process.argv[4] ?? 9222);

if (!targetUrlPart) {
  throw new Error("Usage: ashby_cdp.mjs <mode> <target-url-part> [debug-port]");
}

const targets = await fetch(`http://127.0.0.1:${debugPort}/json/list`).then((response) => response.json());
const target = targets.find((item) => item.type === "page" && item.url.includes(targetUrlPart));
if (!target) throw new Error(`Ashby Chrome tab not found for ${targetUrlPart}`);

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
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}

await send("Runtime.enable");
await send("DOM.enable");

if (mode === "inspect") {
  const data = await evaluate(`(() => ({
    title: document.title,
    url: location.href,
    controls: [...document.querySelectorAll('input, textarea, select, button')].map((element, index) => {
      const idLabel = element.id ? document.querySelector('label[for="' + CSS.escape(element.id) + '"]') : null;
      const surrounding = element.closest('[class*="field" i], label') || element.parentElement?.parentElement;
      return {
        index,
        tag: element.tagName,
        type: element.type || null,
        id: element.id || null,
        name: element.name || null,
        required: element.required || element.getAttribute('aria-required') === 'true',
        label: (idLabel?.innerText || element.closest('label')?.innerText || surrounding?.innerText || '').trim().slice(0, 500),
        placeholder: element.placeholder || null,
        value: element.type === 'file' ? [...element.files].map((file) => file.name) : element.value,
        options: element.tagName === 'SELECT' ? [...element.options].map((option) => option.text) : null,
        text: element.tagName === 'BUTTON' ? element.innerText.trim() : null
      };
    })
  }))()`);
  process.stdout.write(JSON.stringify(data, null, 2));
} else if (mode === "fill") {
  const configPath = process.argv[5];
  if (!configPath) throw new Error("Fill mode requires a JSON config path");
  const config = JSON.parse(await readFile(configPath, "utf8"));

  const filledFields = await evaluate(`(() => {
    const fields = ${JSON.stringify(config.fields ?? [])};
    const setValue = (element, value) => {
      const prototype = element.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, 'value').set.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
      element.dispatchEvent(new Event('blur', { bubbles: true }));
    };
    return fields.map(({ selector, value }) => {
      const element = document.querySelector(selector);
      if (!element) throw new Error('Field not found: ' + selector);
      setValue(element, value);
      return { selector, value: element.value };
    });
  })()`);

  const autocompleteResults = [];
  for (const autocomplete of config.autocomplete ?? []) {
    await evaluate(`(() => {
      const item = ${JSON.stringify(autocomplete)};
      const element = document.querySelector(item.selector);
      if (!element) throw new Error('Autocomplete not found: ' + item.selector);
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(element, item.query);
      element.dispatchEvent(new Event('input', { bubbles: true }));
      element.dispatchEvent(new Event('change', { bubbles: true }));
      element.focus();
      return true;
    })()`);

    let selected = false;
    for (let attempt = 0; attempt < 20 && !selected; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      selected = await evaluate(`(() => {
        const item = ${JSON.stringify(autocomplete)};
        const options = [...document.querySelectorAll('[role="option"]')];
        const option = options.find((candidate) => candidate.innerText.trim() === item.option);
        if (!option) return false;
        option.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        option.click();
        return true;
      })()`);
    }
    if (!selected) throw new Error(`Autocomplete option not found: ${autocomplete.option}`);
    await new Promise((resolve) => setTimeout(resolve, 500));
    autocompleteResults.push(await evaluate(`document.querySelector(${JSON.stringify(autocomplete.selector)}).value`));
  }

  const documentNode = await send("DOM.getDocument", { depth: -1, pierce: true });
  const attachedFiles = [];
  for (const file of config.files ?? []) {
    const fileNode = await send("DOM.querySelector", {
      nodeId: documentNode.root.nodeId,
      selector: file.selector,
    });
    if (!fileNode.nodeId) throw new Error(`File input not found: ${file.selector}`);
    await send("DOM.setFileInputFiles", { nodeId: fileNode.nodeId, files: [file.path] });
    attachedFiles.push(file.path);
  }

  await new Promise((resolve) => setTimeout(resolve, 1200));
  const verification = await evaluate(`(() => ({
    fields: ${JSON.stringify(config.fields ?? [])}.map(({ selector }) => ({
      selector,
      value: document.querySelector(selector)?.value || ''
    })),
    autocomplete: ${JSON.stringify(config.autocomplete ?? [])}.map(({ selector }) => ({
      selector,
      value: document.querySelector(selector)?.value || ''
    })),
    files: [...document.querySelectorAll('input[type="file"]')].map((element) => ({
      id: element.id || null,
      files: [...element.files].map((file) => ({ name: file.name, size: file.size, type: file.type }))
    })).filter((item) => item.files.length),
    submit: [...document.querySelectorAll('button')].filter((button) => button.innerText.trim() === 'Submit Application').map((button) => ({
      text: button.innerText.trim(),
      disabled: button.disabled
    }))
  }))()`);
  process.stdout.write(JSON.stringify({ filledFields, autocompleteResults, attachedFiles, verification }, null, 2));
} else if (mode === "submit") {
  const preflight = await evaluate(`(() => {
    const requiredSelectors = [
      '#_systemfield_name',
      '#_systemfield_email',
      '[id="10f4ec6e-bc90-4c7f-a159-f5b3f68442dd"]',
      'input[placeholder="Start typing..."]'
    ];
    const missing = requiredSelectors.filter((selector) => !document.querySelector(selector)?.value.trim());
    const resume = document.querySelector('#_systemfield_resume')?.files?.[0];
    const coverLetter = document.querySelector('[id="fccbe9ae-5fdc-4ec1-bc07-3c11006aae3b"]')?.files?.[0];
    const submit = [...document.querySelectorAll('button')].find((button) => button.innerText.trim() === 'Submit Application');
    return {
      missing,
      resume: resume ? { name: resume.name, size: resume.size } : null,
      coverLetter: coverLetter ? { name: coverLetter.name, size: coverLetter.size } : null,
      submitFound: Boolean(submit),
      submitDisabled: submit?.disabled ?? true
    };
  })()`);
  if (preflight.missing.length || !preflight.resume || !preflight.coverLetter || !preflight.submitFound || preflight.submitDisabled) {
    throw new Error(`Submission preflight failed: ${JSON.stringify(preflight)}`);
  }

  await evaluate(`(() => {
    const submit = [...document.querySelectorAll('button')].find((button) => button.innerText.trim() === 'Submit Application');
    submit.click();
    return true;
  })()`);

  let result;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    result = await evaluate(`(() => ({
      url: location.href,
      title: document.title,
      text: document.body.innerText.slice(0, 3000),
      submitPresent: [...document.querySelectorAll('button')].some((button) => button.innerText.trim() === 'Submit Application')
    }))()`);
    if (!result.submitPresent || /thank you|application (?:has been )?submitted|received your application/i.test(result.text)) break;
  }
  process.stdout.write(JSON.stringify({ preflight, result }, null, 2));
} else if (mode === "screenshot") {
  await send("Page.enable");
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  const outputPath = "/private/tmp/ashby-application.png";
  await writeFile(outputPath, Buffer.from(shot.data, "base64"));
  process.stdout.write(outputPath);
} else {
  throw new Error(`Unknown mode: ${mode}`);
}

socket.close();
