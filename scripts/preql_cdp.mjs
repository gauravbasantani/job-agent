#!/usr/bin/env node

import { writeFile } from "node:fs/promises";

const mode = process.argv[2] ?? "inspect";
const debugPort = 9222;
const targetUrlPart = "jobs.ashbyhq.com/preql/889f09fb-8562-436b-9b15-30d7d56caae7";
const resumePath = "/Users/the user/job-agent-system/applications/2026-08-01-preql-product-designer/Your_Name_Product_Designer_Resume.pdf";

const targets = await fetch(`http://127.0.0.1:${debugPort}/json/list`).then((r) => r.json());
const target = targets.find((item) => item.type === "page" && item.url.includes(targetUrlPart));
if (!target) throw new Error("Preql Chrome tab not found");

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

if (mode === "open") {
  const opened = await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((item) => item.innerText.trim() === 'Apply for this Job');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  await new Promise((resolve) => setTimeout(resolve, 1500));
  process.stdout.write(JSON.stringify({ opened }));
} else if (mode === "inspect") {
  const data = await evaluate(`(() => ({
    title: document.title,
    text: document.body.innerText,
    controls: [...document.querySelectorAll('input, textarea, button')].map((el, index) => ({
      index,
      tag: el.tagName,
      type: el.type || null,
      name: el.name || null,
      placeholder: el.placeholder || null,
      ariaLabel: el.getAttribute('aria-label'),
      text: el.innerText || null,
      value: el.type === 'file' ? [...el.files].map(f => f.name) : el.value,
      outerHTML: el.outerHTML.slice(0, 800)
    }))
  }))()`);
  process.stdout.write(JSON.stringify(data, null, 2));
} else if (mode === "fill") {
  const values = {
    name: "Your Name",
    email: "you@example.com",
    linkedin: "https://www.linkedin.com/in/yourname",
    location: "Your City, United States",
    note: "Hi, I'm the user, an AI-first product designer with four years building fintech, SaaS, and AI products. I've designed complex admin workflows, LLM review experiences, scalable design systems, and React prototypes. Preql's mission to make financial data transformation understandable and trustworthy directly matches how I approach complex product systems. Portfolio: https://yourname.example.com",
  };

  const fillResult = await evaluate(`(() => {
    const values = ${JSON.stringify(values)};
    const controls = [...document.querySelectorAll('input:not([type=file]), textarea')];
    const setValue = (el, value) => {
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
    };
    const labelText = (el) => {
      const idLabel = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
      return (idLabel?.innerText || el.closest('label')?.innerText || el.parentElement?.parentElement?.innerText || '').toLowerCase();
    };
    const assigned = [];
    for (const el of controls) {
      if (el.name === 'g-recaptcha-response') continue;
      const label = labelText(el);
      let key = null;
      if (el.name === '_systemfield_name') key = 'name';
      else if (el.name === '_systemfield_email') key = 'email';
      else if (el.name === '14f5b628-3ff2-45b3-85bd-4b1fa25e5a5c') key = 'linkedin';
      else if (el.name === 'f03db3f2-3cdb-4d65-8bed-8de766c86612') key = 'location';
      else if (el.name === '43025ce5-0aca-4843-81c4-469044884a4d') key = 'note';
      if (key) {
        setValue(el, values[key]);
        assigned.push({ key, label: label.slice(0, 140), value: el.value });
      }
    }
    return assigned;
  })()`);

  const documentNode = await send("DOM.getDocument", { depth: -1, pierce: true });
  const fileNode = await send("DOM.querySelector", {
    nodeId: documentNode.root.nodeId,
    selector: '#_systemfield_resume',
  });
  if (!fileNode.nodeId) throw new Error("Resume file input not found");
  await send("DOM.setFileInputFiles", { nodeId: fileNode.nodeId, files: [resumePath] });

  await new Promise((resolve) => setTimeout(resolve, 1500));
  const verification = await evaluate(`(() => ({
    fields: [...document.querySelectorAll('input:not([type=file]), textarea')].map(el => ({
      type: el.type || el.tagName,
      value: el.value,
      label: (el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]')?.innerText : '') || el.closest('label')?.innerText || ''
    })),
    files: [...document.querySelectorAll('input[type=file]')].map(el => [...el.files].map(f => f.name)),
    submitButtons: [...document.querySelectorAll('button')].filter(b => /submit/i.test(b.innerText)).map(b => ({ text: b.innerText, disabled: b.disabled }))
  }))()`);
  process.stdout.write(JSON.stringify({ fillResult, verification }, null, 2));
} else if (mode === "verify") {
  const verification = await evaluate(`(() => {
    const field = (name) => document.querySelector('[name="' + name + '"]')?.value || '';
    const resume = document.querySelector('#_systemfield_resume')?.files?.[0];
    const submit = [...document.querySelectorAll('button')].find((button) => /submit application/i.test(button.innerText));
    return {
      url: location.href,
      name: field('_systemfield_name'),
      email: field('_systemfield_email'),
      linkedin: field('14f5b628-3ff2-45b3-85bd-4b1fa25e5a5c'),
      location: field('f03db3f2-3cdb-4d65-8bed-8de766c86612'),
      note: field('43025ce5-0aca-4843-81c4-469044884a4d'),
      resume: resume ? { name: resume.name, size: resume.size, type: resume.type } : null,
      submit: submit ? { text: submit.innerText.trim(), disabled: submit.disabled } : null
    };
  })()`);
  process.stdout.write(JSON.stringify(verification, null, 2));
} else if (mode === "submit") {
  const preflight = await evaluate(`(() => {
    const requiredNames = [
      '_systemfield_name',
      '_systemfield_email',
      '14f5b628-3ff2-45b3-85bd-4b1fa25e5a5c',
      'f03db3f2-3cdb-4d65-8bed-8de766c86612',
      '43025ce5-0aca-4843-81c4-469044884a4d'
    ];
    const missing = requiredNames.filter((name) => !document.querySelector('[name="' + name + '"]')?.value.trim());
    const resume = document.querySelector('#_systemfield_resume')?.files?.[0];
    const submit = [...document.querySelectorAll('button')].find((button) => button.innerText.trim() === 'Submit Application');
    return {
      missing,
      resume: resume ? { name: resume.name, size: resume.size } : null,
      submitFound: Boolean(submit),
      submitDisabled: submit?.disabled ?? true
    };
  })()`);
  if (preflight.missing.length || !preflight.resume || !preflight.submitFound || preflight.submitDisabled) {
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
  await evaluate("window.scrollTo(0, document.body.scrollHeight)");
  await new Promise((resolve) => setTimeout(resolve, 500));
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  const outputPath = "/private/tmp/preql-form.png";
  await writeFile(outputPath, Buffer.from(shot.data, "base64"));
  process.stdout.write(outputPath);
} else {
  throw new Error(`Unknown mode: ${mode}`);
}

socket.close();
