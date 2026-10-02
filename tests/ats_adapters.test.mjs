import assert from "node:assert/strict";
import test from "node:test";

import {
  ADAPTERS,
  NEVER_FILL_CATEGORIES,
  classifyField,
  detectAdapter,
  detectBlockers,
  fieldInspectionExpression,
  getAdapter,
  isFinalSubmitControl,
  isRequired,
  matchOption,
  normalizeLabel,
  planFill,
  verifyReadback,
} from "../scripts/ats_adapters.mjs";


test("every platform in the plan has an adapter", () => {
  const ids = ADAPTERS.map((adapter) => adapter.id).sort();
  assert.deepEqual(ids, [
    "adp",
    "ashby",
    "greenhouse",
    "icims",
    "lever",
    "linkedin_easy_apply",
    "smartrecruiters",
    "workday",
  ]);
});


test("detectAdapter matches on host", () => {
  assert.equal(detectAdapter({ url: "https://job-boards.greenhouse.io/discord/jobs/7845" }).adapter.id, "greenhouse");
  assert.equal(detectAdapter({ url: "https://jobs.ashbyhq.com/eudia/abc" }).adapter.id, "ashby");
  assert.equal(detectAdapter({ url: "https://jobs.lever.co/preql/xyz" }).adapter.id, "lever");
  assert.equal(detectAdapter({ url: "https://ramp.wd1.myworkdayjobs.com/en-US/ramp/job/x" }).adapter.id, "workday");
  assert.equal(detectAdapter({ url: "https://careers-nisc.icims.com/jobs/3210/job" }).adapter.id, "icims");
  assert.equal(detectAdapter({ url: "https://workforcenow.adp.com/mascsr/default/mdf/x" }).adapter.id, "adp");
  assert.equal(detectAdapter({ url: "https://jobs.smartrecruiters.com/Acme/74400" }).adapter.id, "smartrecruiters");
  assert.equal(detectAdapter({ url: "https://www.linkedin.com/jobs/view/4123" }).adapter.id, "linkedin_easy_apply");
});


test("detectAdapter finds an ATS embedded in a company careers page", () => {
  const result = detectAdapter({
    url: "https://careers.example.com/open-roles/product-designer",
    html: '<iframe src="https://boards.greenhouse.io/embed/job_app?for=example"></iframe>',
  });
  assert.equal(result.adapter.id, "greenhouse");
  assert.equal(result.confidence, "embedded");
});


test("detectAdapter returns nothing for an unknown page", () => {
  assert.equal(detectAdapter({ url: "https://example.com/apply", html: "<form></form>" }).adapter, null);
});


test("greenhouse adapter builds its board API schema url", () => {
  const adapter = getAdapter("greenhouse");
  assert.equal(
    adapter.schemaUrl("https://job-boards.greenhouse.io/discord/jobs/7845123"),
    "https://boards-api.greenhouse.io/v1/boards/discord/jobs/7845123?questions=true",
  );
});


test("normalizeLabel strips required markers and punctuation", () => {
  assert.equal(normalizeLabel("First Name *"), "first name");
  assert.equal(normalizeLabel("Email (required)"), "email");
});


test("credential, OTP, ID, payment and CAPTCHA fields are never fillable", () => {
  const unsafe = [
    { label: "Password", type: "password" },
    { label: "Create a password", type: "text" },
    { label: "Enter the verification code", type: "text" },
    { label: "Social Security Number", type: "text" },
    { label: "Card number", type: "text" },
    { label: "reCAPTCHA", type: "text" },
  ];
  for (const field of unsafe) {
    const result = classifyField(field);
    assert.equal(result.safe, false, `${field.label} should not be safe`);
    assert.ok(NEVER_FILL_CATEGORIES.has(result.category), `${field.label} -> ${result.category}`);
  }
});


test("classifyField assigns canonical keys to ordinary application fields", () => {
  const cases = [
    [{ label: "First Name *", type: "text" }, "identity", "first_name"],
    [{ label: "Email", type: "email" }, "identity", "email"],
    [{ label: "LinkedIn Profile", type: "url" }, "links", "linkedin"],
    [{ label: "Resume/CV", type: "file" }, "document", "resume"],
    [{ label: "Are you legally authorized to work in the US?", type: "select" }, "work_authorization", "work_authorization"],
    [{ label: "Will you now or in the future require sponsorship?", type: "select" }, "work_authorization", "sponsorship"],
    [{ label: "Gender", type: "select" }, "eeo", "gender"],
    [{ label: "Veteran Status", type: "select" }, "eeo", "veteran_status"],
    [{ label: "Desired salary", type: "text" }, "compensation", "salary_expectation"],
  ];
  for (const [field, category, key] of cases) {
    const result = classifyField(field);
    assert.equal(result.category, category, field.label);
    assert.equal(result.key, key, field.label);
    assert.equal(result.safe, true);
  }
});

test("classifyField does not reuse a website answer for Twitter URL fields", () => {
  assert.deepEqual(
    classifyField({ name: "urls[Twitter]", label: "Twitter URL", type: "text" }),
    { category: "links", key: "twitter", safe: true, reason: "" },
  );
});


// --- Regressions found by running against Discord's live Greenhouse form ---

test("a portfolio field that mentions a password is not a credential", () => {
  // Real label on Discord's form. Reading it as a credential made the agent
  // declare a login wall and refuse to fill the entire application.
  const result = classifyField({
    id: "question_37601261002",
    label: "Website/Portfolio (please include password when applicable)",
    type: "text",
  });
  assert.equal(result.category, "links");
  assert.equal(result.safe, true);
});


test("a real password input is still refused", () => {
  assert.equal(classifyField({ label: "Password", type: "password" }).safe, false);
  assert.equal(classifyField({ label: "Create a password", type: "text" }).safe, false);
});

test("a generic ATS file control defaults to the resume upload", () => {
  assert.deepEqual(classifyField({ type: "file", id: "file-input", label: "Choose a file" }), {
    category: "document",
    key: "resume",
    safe: true,
    reason: "",
  });
});


test("custom dropdowns classify as answerable, not unknown widgets", () => {
  // Modern ATS screening questions render as react-select comboboxes. Leaving
  // `combobox` out of the choice types marked every one an unknown widget.
  for (const type of ["combobox", "react-select", "listbox", "select"]) {
    const result = classifyField({ label: "Are you currently located in the US?", type });
    assert.equal(result.category, "screening", type);
    assert.equal(result.safe, true, type);
  }
});


test("a CAPTCHA does not block filling, but an account wall does", () => {
  // Greenhouse and Ashby attach an invisible reCAPTCHA to nearly every
  // posting. Treating it as blocking meant refusing to fill any of them.
  const captcha = detectBlockers({ fields: [], pageText: "protected by reCAPTCHA", url: "https://x.test" });
  const captchaBlocker = captcha.find((blocker) => blocker.type === "captcha");
  assert.equal(captchaBlocker.blocking, false);

  const wall = detectBlockers({
    fields: [{ label: "Create a password", type: "password" }],
    pageText: "Create an account to apply",
  });
  assert.equal(wall[0].type, "account_wall");
  assert.equal(wall[0].blocking, true);
});


test("widget internals with no label and no selector are not a blocker", () => {
  // Greenhouse's phone control ships a required, unlabeled, unaddressable
  // input. A genuine question always has a label.
  const blockers = detectBlockers({
    fields: [{ label: "", selector: "", id: "", type: "text", required: true }],
    pageText: "Apply for Product Designer",
    url: "https://job-boards.greenhouse.io/x/jobs/1",
  });
  assert.deepEqual(blockers, []);
});


test("an unlabeled exotic widget is unknown, not guessed", () => {
  const result = classifyField({ label: "", type: "canvas-signature" });
  assert.equal(result.category, "unknown");
  assert.equal(result.safe, false);
});


test("isRequired reads the attribute, aria, and the asterisk convention", () => {
  assert.equal(isRequired({ required: true }), true);
  assert.equal(isRequired({ ariaRequired: "true" }), true);
  assert.equal(isRequired({ label: "First Name *" }), true);
  assert.equal(isRequired({ label: "Website" }), false);
});


test("matchOption refuses the loose substring that once picked the wrong gender", () => {
  const options = ["Cisgender man", "Cisgender woman", "Non-binary", "I don't wish to answer"];
  // The real bug: a hasText "Man" filter matched "Cisgender woman" because
  // "woman" contains "man". Anchoring at a word boundary is what prevents it.
  const loose = matchOption(options, "Man");
  assert.notEqual(loose.option, "Cisgender woman");

  const exact = matchOption(options, "Cisgender man");
  assert.equal(exact.ok, true);
  assert.equal(exact.option, "Cisgender man");
});


test("matchOption rejects a genuinely ambiguous answer", () => {
  // No exact option, and "Asian" anchors inside two of them. Guessing here is
  // how a South Asian candidate gets recorded as East Asian.
  const result = matchOption(["South Asian", "East Asian", "White"], "Asian");
  assert.equal(result.ok, false);
  assert.equal(result.reason, "option_ambiguous");
});


test("an exact option wins over its near neighbours", () => {
  const result = matchOption(["Asian", "South Asian", "East Asian"], "Asian");
  assert.equal(result.ok, true);
  assert.equal(result.option, "Asian");
  assert.equal(result.match, "exact");
});


test("EEO and work-authorization dropdowns require a verbatim option", () => {
  const options = ["Cisgender man", "Cisgender woman", "Non-binary"];
  // Fuzzy matching is allowed generally...
  assert.equal(matchOption(options, "Man").ok, true);
  // ...but never for a demographic answer.
  assert.equal(matchOption(options, "Man", { exactOnly: true }).ok, false);

  const plan = planFill(
    [{ selector: "#gender", id: "gender", label: "Gender", type: "select", required: true, options }],
    { gender: "Man" },
    { adapterId: "greenhouse" },
  );
  assert.equal(plan.fills.length, 0);
  assert.equal(plan.missing_required[0].reason, "option_not_found_exact");

  const exact = planFill(
    [{ selector: "#gender", id: "gender", label: "Gender", type: "select", required: true, options }],
    { gender: "Cisgender man" },
    { adapterId: "greenhouse" },
  );
  assert.equal(exact.fills[0].value, "Cisgender man");
});


test("matchOption reports a missing option instead of inventing one", () => {
  const result = matchOption(["Yes", "No"], "Maybe");
  assert.equal(result.ok, false);
  assert.equal(result.reason, "option_not_found");
});


test("planFill fills only fields with an explicit answer", () => {
  const fields = [
    { selector: "#first_name", id: "first_name", label: "First Name *", type: "text", required: true },
    { selector: "#email", id: "email", label: "Email *", type: "email", required: true },
    { selector: "#phone", id: "phone", label: "Phone", type: "tel" },
  ];
  const plan = planFill(fields, { first_name: "the user", email: "you@example.com" }, { adapterId: "greenhouse" });

  assert.equal(plan.fills.length, 2);
  assert.deepEqual(plan.fills.map((fill) => fill.value), ["the user", "you@example.com"]);
  // Phone had no answer: skipped, not invented.
  assert.equal(plan.skipped.length, 1);
  assert.equal(plan.skipped[0].reason, "no answer supplied");
  assert.equal(plan.missing_required.length, 0);
});

test("planFill ignores required framework internals with no addressable identity", () => {
  const plan = planFill([{ type: "text", required: true, label: "", selector: "", id: "", name: "" }], {});
  assert.equal(plan.missing_required.length, 0);
  assert.equal(plan.skipped[0].reason, "unaddressable widget internal");
});


test("planFill never fills an unsafe field even when an answer is supplied", () => {
  const fields = [
    { selector: "#password", id: "password", label: "Password", type: "password", required: true },
    { selector: "#otp", id: "otp", label: "Verification code", type: "text", required: true },
  ];
  const plan = planFill(fields, { password: "hunter2", otp: "123456" }, { adapterId: "workday" });

  assert.equal(plan.fills.length, 0);
  assert.equal(plan.human_required.length, 2);
  assert.ok(plan.skipped.every((entry) => /human/.test(entry.reason)));
});


test("planFill refuses an answer that maxlength would silently truncate", () => {
  const answer = "x".repeat(300);
  const fields = [{
    selector: "#question_1255",
    id: "question_1255",
    label: "What is your go-to game right now?",
    type: "text",
    required: true,
    maxlength: 255,
  }];
  const plan = planFill(fields, { "what is your go-to game right now": answer }, { adapterId: "greenhouse" });

  assert.equal(plan.fills.length, 0);
  assert.equal(plan.missing_required.length, 1);
  assert.equal(plan.missing_required[0].reason, "answer_exceeds_maxlength");
  assert.equal(plan.missing_required[0].maxlength, 255);
});


test("planFill reports a required dropdown whose answer is not an option", () => {
  const fields = [{
    selector: "#degree",
    id: "degree",
    label: "Discipline *",
    type: "select",
    required: true,
    options: ["Computer Science", "Information Systems", "Business"],
  }];
  const plan = planFill(fields, { discipline: "Human Computer Interaction" }, { adapterId: "greenhouse" });
  assert.equal(plan.fills.length, 0);
  assert.equal(plan.missing_required[0].reason, "option_not_found");
});


test("planFill resolves dropdown answers to the exact option text", () => {
  const fields = [{
    selector: "#degree",
    id: "degree",
    label: "Discipline *",
    type: "select",
    required: true,
    options: ["Computer Science", "Information Systems"],
  }];
  const plan = planFill(fields, { discipline: "computer science" }, { adapterId: "greenhouse" });
  assert.equal(plan.fills[0].value, "Computer Science");
  assert.equal(plan.fills[0].strategy, "react-select");
});


test("planFill can target an exact Ashby radio input without inventing a group option", () => {
  const fields = [{
    selector: "#eeoc_gender-labeled-radio-0",
    id: "eeoc_gender-labeled-radio-0",
    name: "eeoc_gender",
    label: "Gender: Male",
    type: "radio",
    required: false,
    options: [],
  }];
  const answers = { "eeoc_gender-labeled-radio-0": true };
  const plan = planFill(fields, answers, { adapterId: "ashby" });

  assert.equal(plan.fills.length, 1);
  assert.equal(plan.fills[0].strategy, "radio-direct");
  assert.equal(plan.fills[0].value, true);
});


test("planFill treats one selected radio as satisfying its required group", () => {
  const fields = [
    { selector: "#yes", id: "yes", name: "onsite", label: "On-site?: Yes", type: "radio", required: true, options: [] },
    { selector: "#no", id: "no", name: "onsite", label: "On-site?: No", type: "radio", required: true, options: [] },
  ];
  const plan = planFill(fields, { yes: true }, { adapterId: "linkedin_easy_apply" });
  assert.equal(plan.fills.length, 1);
  assert.equal(plan.missing_required.length, 0);
});


test("detectBlockers catches account walls, logins, CAPTCHA and OTP", () => {
  const accountWall = detectBlockers({
    fields: [{ label: "Create a password", type: "password" }],
    pageText: "Create an account to apply for this role",
  });
  assert.deepEqual(accountWall.map((blocker) => blocker.type), ["account_wall"]);

  const login = detectBlockers({
    fields: [{ label: "Password", type: "password" }],
    pageText: "Sign in to continue",
  });
  assert.equal(login[0].type, "login");

  const captcha = detectBlockers({ fields: [], pageText: "Please complete the reCAPTCHA below", url: "https://x.test" });
  assert.ok(captcha.some((blocker) => blocker.type === "captcha"));

  const otp = detectBlockers({ fields: [], pageText: "We emailed you a code. Enter the verification code.", url: "https://x.test" });
  assert.ok(otp.some((blocker) => blocker.type === "otp"));
});


test("detectBlockers flags a required widget it cannot classify", () => {
  const blockers = detectBlockers({
    fields: [{ label: "", type: "signature-pad", required: true, selector: "#sig" }],
    pageText: "Apply now",
  });
  assert.equal(blockers[0].type, "unknown_widget");
});


test("detectBlockers stays quiet on a clean form", () => {
  const blockers = detectBlockers({
    fields: [{ label: "First Name *", type: "text", required: true }],
    pageText: "Apply for Product Designer",
    url: "https://job-boards.greenhouse.io/x/jobs/1",
    adapterId: "greenhouse",
  });
  assert.deepEqual(blockers, []);
});


test("verifyReadback passes when the page holds exactly what was intended", () => {
  const plan = { fills: [{ selector: "#first_name", label: "First Name", strategy: "type", value: "Alex", intended_length: 4 }] };
  const result = verifyReadback(plan, { "#first_name": { value: "Alex", maxlength: null } });
  assert.equal(result.ok, true);
  assert.equal(result.verified.length, 1);
});


test("verifyReadback uses a text input value when its wrapper text is empty", () => {
  const plan = { fills: [{ selector: "#name", label: "Name", strategy: "type", value: "Alex", intended_length: 4 }] };
  const result = verifyReadback(plan, { "#name": { value: "Alex", controlText: "", selectedText: "" } });
  assert.equal(result.ok, true);
});

test("verifyReadback accepts phone formatting when the national digits match", () => {
  const plan = { fills: [{
    selector: "#phone",
    label: "Phone",
    category: "identity",
    key: "phone",
    strategy: "type",
    value: "+1 (555) 123-4567",
    intended_length: 17,
  }] };
  assert.equal(verifyReadback(plan, { "#phone": { value: "555 123-4567" } }).ok, true);
});


test("verifyReadback treats a value sitting at maxlength as truncated", () => {
  const value = "y".repeat(255);
  const plan = { fills: [{ selector: "#q", label: "Q", strategy: "type", value, intended_length: 255, maxlength: 255 }] };
  const result = verifyReadback(plan, { "#q": { value, maxlength: 255 } });
  assert.equal(result.ok, false);
  assert.equal(result.mismatches[0].reason, "at_maxlength_treat_as_truncated");
});


test("verifyReadback catches the silent mid-sentence cut", () => {
  const plan = { fills: [{ selector: "#q", label: "Q", strategy: "type", value: "a".repeat(300), intended_length: 300 }] };
  const result = verifyReadback(plan, { "#q": { value: "a".repeat(255), maxlength: 255 } });
  assert.equal(result.ok, false);
  assert.equal(result.mismatches[0].reason, "length_mismatch");
});


test("verifyReadback reads react-select state from the control text, not the input value", () => {
  const plan = { fills: [{ selector: "#gender", label: "Gender", strategy: "react-select", value: "Cisgender man", intended_length: 13 }] };
  // react-select leaves input.value empty after a successful selection.
  const ok = verifyReadback(plan, { "#gender": { value: "", controlText: "Cisgender man" } });
  assert.equal(ok.ok, true);

  const wrong = verifyReadback(plan, { "#gender": { value: "", controlText: "Cisgender woman" } });
  assert.equal(wrong.ok, false);
  assert.equal(wrong.mismatches[0].reason, "selection_mismatch");
});


test("verifyReadback checks an explicitly targeted radio by checked state", () => {
  const plan = { fills: [{ selector: "#male", label: "Male", strategy: "radio-direct", value: true }] };
  assert.equal(verifyReadback(plan, { "#male": { checked: true } }).ok, true);
  const wrong = verifyReadback(plan, { "#male": { checked: false } });
  assert.equal(wrong.ok, false);
  assert.equal(wrong.mismatches[0].reason, "radio_state_mismatch");
});


test("verifyReadback validates the Greenhouse US phone-country control by flag and dial code", () => {
  const plan = { fills: [{
    selector: "#country",
    id: "country",
    label: "Country*",
    type: "combobox",
    strategy: "react-select",
    value: "United States",
  }] };
  const ok = verifyReadback(plan, { "#country": { controlText: "+1", countryCode: "us" } });
  assert.equal(ok.ok, true);
  const wrong = verifyReadback(plan, { "#country": { controlText: "+1", countryCode: "ca" } });
  assert.equal(wrong.ok, false);
});


test("verifyReadback fails an unattached file", () => {
  const plan = { fills: [{ selector: "#resume", label: "Resume", strategy: "file", value: "/x/Your_Name_Product_Designer_Resume.pdf", intended_length: 1 }] };
  assert.equal(verifyReadback(plan, { "#resume": { fileName: "" } }).ok, false);
  assert.equal(
    verifyReadback(plan, { "#resume": { fileName: "Your_Name_Product_Designer_Resume.pdf" } }).ok,
    true,
  );
});


test("isFinalSubmitControl recognises the button the agent must not click", () => {
  assert.equal(isFinalSubmitControl("greenhouse", "Submit Application"), true);
  assert.equal(isFinalSubmitControl("workday", "Submit"), true);
  assert.equal(isFinalSubmitControl("greenhouse", "Next"), false);
  assert.equal(isFinalSubmitControl("greenhouse", "Save draft"), false);
});


test("the inspection expression is syntactically valid JavaScript", () => {
  const expression = fieldInspectionExpression();
  assert.doesNotThrow(() => new Function(`return ${expression}`));
  assert.match(expression, /maxLength/);
  assert.match(expression, /shadowRoot/);
});
