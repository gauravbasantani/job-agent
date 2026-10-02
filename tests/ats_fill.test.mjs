import assert from "node:assert/strict";
import test from "node:test";

import {
  classifySubmissionOutcome,
  isExplicitSubmitConfirmation,
} from "../scripts/ats_fill.mjs";

test("submit confirmation must exactly name the mapped job", () => {
  assert.equal(isExplicitSubmitConfirmation("patreon-product-designer", "patreon-product-designer"), true);
  assert.equal(isExplicitSubmitConfirmation("patreon-product-designer", "all"), false);
  assert.equal(isExplicitSubmitConfirmation("patreon-product-designer", "orion-product-designer"), false);
});

test("submission outcome requires positive success-page evidence", () => {
  assert.deepEqual(
    classifySubmissionOutcome({ heading: "Thank you for applying", text: "Your application has been submitted." }),
    { status: "submitted", submitted: true },
  );
  assert.deepEqual(
    classifySubmissionOutcome({ text: "Submit Application", has_captcha_frame: true }),
    { status: "captcha", submitted: false },
  );
  assert.deepEqual(
    classifySubmissionOutcome({ text: "Submit Application", errors: ["Phone is required"] }),
    { status: "validation", submitted: false },
  );
});
