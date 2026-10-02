#!/usr/bin/env node
/**
 * Read the full job description from a LinkedIn job page already mapped by
 * chrome_tabs.mjs. Read only: it expands the "see more" description and
 * extracts text. It never fills a field, clicks apply, or submits.
 *
 * Usage: node scripts/linkedin_scrape_job.mjs --job <jobKey>
 */

import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { connectBrowser, verifyProfile, DEFAULT_PROFILE_NAME } from "./chrome_tabs.mjs";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_STATE = resolve(REPO_ROOT, ".job-agent", "browser-tabs.json");

function parseArgs(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token.startsWith("--")) {
      const key = token.slice(2);
      const next = argv[i + 1];
      if (next && !next.startsWith("--")) {
        options[key] = next;
        i += 1;
      } else options[key] = true;
    }
  }
  return options;
}

const EXPAND = `(() => {
  const btn = document.querySelector('.jobs-description__footer-button, button.show-more-less-html__button, .artdeco-card__actions button');
  if (btn) btn.click();
  return true;
})()`;

const EXTRACT = `(() => {
  const t = (sel) => {
    const el = document.querySelector(sel);
    return el ? el.innerText.trim().replace(/\\n{3,}/g, '\\n\\n') : '';
  };
  const title = t('.job-details-jobs-unified-top-card__job-title') || t('h1');
  const company = t('.job-details-jobs-unified-top-card__company-name');
  const meta = t('.job-details-jobs-unified-top-card__primary-description-container') ||
               t('.job-details-jobs-unified-top-card__tertiary-description-container');
  const insight = t('.job-details-jobs-unified-top-card__job-insight');
  const desc = t('#job-details') || t('.jobs-description__content') || t('.jobs-box__html-content');
  return JSON.stringify({ title, company, meta, insight, description: desc.slice(0, 9000) });
})()`;

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const jobKey = options.job;
  if (!jobKey) throw new Error("--job is required");

  const state = JSON.parse(await readFile(DEFAULT_STATE, "utf8"));
  const mapped = state.jobs?.[jobKey];
  if (!mapped) throw new Error(`No tab mapped for ${jobKey}`);

  const browser = await connectBrowser(9222);
  try {
    await verifyProfile(browser, DEFAULT_PROFILE_NAME);
    const { sessionId } = await browser.send("Target.attachToTarget", {
      targetId: mapped.target_id,
      flatten: true,
    });
    const evaluate = async (expression) => {
      const res = await browser.send(
        "Runtime.evaluate",
        { expression, returnByValue: true, awaitPromise: true },
        sessionId,
      );
      if (res.exceptionDetails) {
        throw new Error(res.exceptionDetails.exception?.description || "evaluate failed");
      }
      return res.result?.value;
    };
    await evaluate(EXPAND);
    await new Promise((r) => setTimeout(r, 700));
    process.stdout.write(`${await evaluate(EXTRACT)}\n`);
  } finally {
    browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
