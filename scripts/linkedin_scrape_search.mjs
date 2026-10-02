#!/usr/bin/env node
/**
 * Read job cards from a LinkedIn jobs search tab already mapped by
 * chrome_tabs.mjs. Read only: it scrolls the result list and extracts card
 * metadata. It never fills, clicks apply, or submits anything.
 *
 * Usage: node scripts/linkedin_scrape_search.mjs --job search-ux-24h [--max 40]
 */

import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { connectBrowser, verifyProfile, DEFAULT_PROFILE_NAME } from "./chrome_tabs.mjs";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_STATE = resolve(REPO_ROOT, ".job-agent", "browser-tabs.json");

function validatedSearchUrl(value) {
  if (!value) return "";
  const url = new URL(String(value));
  if (url.protocol !== "https:" || url.hostname !== "www.linkedin.com" || url.pathname !== "/jobs/search/") {
    throw new Error("--url must be an https://www.linkedin.com/jobs/search/ URL");
  }
  return url.href;
}

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
      } else {
        options[key] = true;
      }
    }
  }
  return options;
}

const EXTRACT = `(() => {
  const out = [];
  const cards = document.querySelectorAll('li[data-occludable-job-id], div.job-card-container, li.jobs-search-results__list-item');
  cards.forEach((card) => {
    const text = (sel) => {
      const el = card.querySelector(sel);
      return el ? el.innerText.trim().replace(/\\s+/g, ' ') : '';
    };
    const title = text('.job-card-list__title--link') || text('a.job-card-container__link') || text('.artdeco-entity-lockup__title');
    const company = text('.artdeco-entity-lockup__subtitle') || text('.job-card-container__primary-description');
    const location = text('.job-card-container__metadata-wrapper') || text('.artdeco-entity-lockup__caption');
    const footer = text('.job-card-container__footer-wrapper') || text('.job-card-list__footer-wrapper');
    const link = card.querySelector('a.job-card-list__title--link, a.job-card-container__link');
    const id = card.getAttribute('data-occludable-job-id') || '';
    if (title) {
      out.push({
        id,
        title,
        company,
        location,
        footer,
        url: link ? new URL(link.getAttribute('href'), location.origin || 'https://www.linkedin.com').href.split('?')[0] : ''
      });
    }
  });
  return JSON.stringify({ count: out.length, jobs: out });
})()`;

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const jobKey = options.job;
  if (!jobKey) throw new Error("--job is required");
  const maxScrolls = Number(options.max_scrolls || 6);
  const searchUrl = validatedSearchUrl(options.url);

  const state = JSON.parse(await readFile(DEFAULT_STATE, "utf8"));
  const mapped = state.jobs?.[jobKey];
  if (!mapped) throw new Error(`No tab mapped for ${jobKey}`);

  const browser = await connectBrowser(9222);
  try {
    // Same profile guard the rest of the runtime uses.
    await verifyProfile(browser, DEFAULT_PROFILE_NAME);

    const { sessionId } = await browser.send("Target.attachToTarget", {
      targetId: mapped.target_id,
      flatten: true,
    });
    if (searchUrl) {
      await browser.send("Page.navigate", { url: searchUrl }, sessionId);
      await new Promise((r) => setTimeout(r, 2500));
    }
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

    // Scroll the results pane so lazy-loaded cards render.
    for (let i = 0; i < maxScrolls; i += 1) {
      await evaluate(`(() => {
        const pane = document.querySelector('.jobs-search-results-list') ||
                     document.querySelector('div.scaffold-layout__list > div') ||
                     document.scrollingElement;
        if (pane) pane.scrollBy(0, 1200);
        return true;
      })()`);
      await new Promise((r) => setTimeout(r, 900));
    }

    const raw = await evaluate(EXTRACT);
    process.stdout.write(`${raw}\n`);
  } finally {
    browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
