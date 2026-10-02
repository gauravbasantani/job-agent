import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_TECHNICAL_RETRIES,
  canTransition,
  isBlockedState,
  isRetryable,
  parseArgs,
  sanitizeUrl,
  validJobKey,
  verifyProfile,
} from "../scripts/chrome_tabs.mjs";


test("automation refuses every Chrome profile except the user", async () => {
  // `null` as the browser proves the refusal happens before any CDP call:
  // if the guard were reached later, this would throw a TypeError instead.
  for (const name of ["Your University", "Work", "Default", "Guest", "the user "]) {
    await assert.rejects(
      () => verifyProfile(null, name),
      /restricted to the Chrome profile named the user/,
      `profile ${JSON.stringify(name)} must be refused`,
    );
  }
});


test("parseArgs normalizes option names", () => {
  assert.deepEqual(
    parseArgs(["open", "--job", "eudia-product-designer", "--state-file", "/tmp/state"]),
    {
      command: "open",
      options: { job: "eudia-product-designer", state_file: "/tmp/state" },
    },
  );
});

test("sanitizeUrl strips credentials and fragments", () => {
  assert.equal(
    sanitizeUrl("https://example.com/job/1?source=career&token=secret#apply"),
    "https://example.com/job/1?source=career",
  );
});

test("job keys are bounded stable slugs", () => {
  assert.equal(validJobKey("eudia-product-designer"), true);
  assert.equal(validJobKey("bad key"), false);
  assert.equal(validJobKey("x"), false);
});


test("a tab walks the fill lifecycle forward", () => {
  assert.equal(canTransition("opened", "inspecting"), true);
  assert.equal(canTransition("inspecting", "filling"), true);
  assert.equal(canTransition("filling", "verifying"), true);
  assert.equal(canTransition("verifying", "awaiting_submit"), true);
  assert.equal(canTransition("awaiting_submit", "submitted"), true);
});


test("a tab cannot skip verification or reopen after submitting", () => {
  // Submitting straight from a fill would bypass the read-back check.
  assert.equal(canTransition("filling", "awaiting_submit"), false);
  assert.equal(canTransition("opened", "submitted"), false);
  assert.equal(canTransition("submitted", "filling"), false);
  assert.equal(canTransition("verifying", "not_a_state"), false);
});


test("any live state can become blocked, and a blocked tab resumes in place", () => {
  for (const blocked of ["blocked_account", "blocked_credentials", "blocked_captcha", "blocked_unknown_field"]) {
    assert.equal(isBlockedState(blocked), true);
    assert.equal(canTransition("filling", blocked), true);
    // `continue {job}` resumes the same tab rather than opening a new one.
    assert.equal(canTransition(blocked, "filling"), true);
    assert.equal(canTransition(blocked, "submitted"), false);
  }
  assert.equal(canTransition("submitted", "blocked_account"), false);
});


test("only technical failures retry, and only twice", () => {
  assert.equal(isRetryable({ state: "technical_failure", retry_count: 0 }), true);
  assert.equal(isRetryable({ state: "technical_failure", retry_count: MAX_TECHNICAL_RETRIES }), false);
  // Account walls, credentials and CAPTCHA wait for a human; they are not
  // retryable no matter how many attempts remain.
  assert.equal(isRetryable({ state: "blocked_account", retry_count: 0 }), false);
  assert.equal(isRetryable({ state: "blocked_captcha", retry_count: 0 }), false);
  assert.equal(isRetryable({ state: "awaiting_submit", retry_count: 0 }), false);
});
