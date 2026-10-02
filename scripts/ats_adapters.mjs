#!/usr/bin/env node
/**
 * Reusable ATS adapters: platform detection, field classification, fill
 * planning, and read-back verification.
 *
 * Everything in this file is pure. No network, no browser, no filesystem — so
 * the risky decisions (what is safe to type, what counts as a blocker, whether
 * an answer was truncated) are unit-testable without a live application form.
 * `scripts/ats_fill.mjs` is the CDP driver that feeds real DOM data through it.
 *
 * Two invariants this module enforces on behalf of `context/hard-rules.md`:
 *   1. Fields in NEVER_FILL_CATEGORIES are never planned for filling, even
 *      when the caller supplies an answer for them.
 *   2. A field is only filled when an explicit answer exists. Nothing is
 *      guessed, inferred from a name, or defaulted.
 */

/** Categories the agent must never type into, regardless of caller intent. */
export const NEVER_FILL_CATEGORIES = new Set([
  "credential",
  "otp",
  "government_id",
  "payment",
  "captcha",
]);

/** Field categories that pause the run for a human instead of failing. */
export const HUMAN_HANDOFF_CATEGORIES = new Set(["credential", "otp", "captcha"]);

/**
 * Blockers that make filling impossible — the form is not reachable until a
 * human clears them. A CAPTCHA is deliberately absent: Greenhouse and Ashby
 * attach an invisible reCAPTCHA to nearly every posting, and it only matters
 * at submit. Treating it as blocking meant refusing to fill any of them.
 */
export const BLOCKING_BLOCKERS = new Set(["account_wall", "login", "otp", "unknown_widget"]);

/**
 * Categories whose dropdown answers must match an option verbatim. A near-miss
 * on a demographic or work-authorization answer is a wrong answer on a real
 * application, so these never fall back to fuzzy matching.
 */
export const EXACT_OPTION_CATEGORIES = new Set(["eeo", "work_authorization"]);

const CATEGORY_RULES = [
  // --- Never fill. Order matters: these run before anything permissive. ---
  // `unless` guards against a label that merely mentions a credential word.
  // Discord's real form asks for "Website/Portfolio (please include password
  // when applicable)" — a plain text field that was being read as a login
  // wall, which blocked the whole application. An actual credential input is
  // `type="password"`, and that is matched before any rule runs.
  {
    category: "credential",
    key: null,
    pattern: /\b(password|passcode|pass phrase|passphrase|\bpin\b|security (question|answer))\b/i,
    unless: /\b(website|portfolio|url|site|link|profile)\b/i,
  },
  { category: "otp", key: null, pattern: /\b(one[- ]?time|verification|confirmation|authentication|security) code\b|\botp\b|\b2fa\b|\bmfa\b|magic link/i },
  { category: "government_id", key: null, pattern: /\b(ssn|social security|national id|passport number|driver'?s licen[cs]e|aadhaar|tax id|tin)\b/i },
  { category: "payment", key: null, pattern: /\b(card number|credit card|debit card|cvv|cvc|billing|iban|routing number|bank account)\b/i },
  { category: "captcha", key: null, pattern: /\b(captcha|recaptcha|hcaptcha|i'?m not a robot)\b/i },

  // --- Identity ---
  { category: "identity", key: "first_name", pattern: /\b(first|given)[ _-]?name\b|^fname$/i },
  { category: "identity", key: "last_name", pattern: /\b(last|family|sur)[ _-]?name\b|^lname$/i },
  { category: "identity", key: "preferred_name", pattern: /\b(preferred|nick)[ _-]?name\b/i },
  { category: "identity", key: "full_name", pattern: /\b(full|legal|your)[ _-]?name\b|^name$/i },
  { category: "identity", key: "email", pattern: /\be-?mail\b/i },
  { category: "identity", key: "phone", pattern: /\b(phone|mobile|telephone|cell)\b/i },
  { category: "identity", key: "pronouns", pattern: /\bpronouns?\b/i },

  // --- Location ---
  { category: "location", key: "location", pattern: /\b(current )?location\b|\bwhere are you (currently )?(based|located)\b/i },
  { category: "location", key: "city", pattern: /\bcity\b/i },
  { category: "location", key: "state", pattern: /\b(state|province|region)\b/i },
  { category: "location", key: "country", pattern: /\bcountry\b/i },
  { category: "location", key: "postal_code", pattern: /\b(zip|postal)[ _-]?code\b/i },
  { category: "location", key: "address", pattern: /\b(street )?address(?! book)\b|\baddress line\b/i },

  // --- Links ---
  { category: "links", key: "linkedin", pattern: /\blinked ?in\b/i },
  { category: "links", key: "portfolio", pattern: /\bportfolio\b|\bcase stud(y|ies)\b/i },
  { category: "links", key: "github", pattern: /\bgit ?hub\b/i },
  { category: "links", key: "dribbble", pattern: /\bdribbble\b|\bbehance\b/i },
  { category: "links", key: "twitter", pattern: /\btwitter\b|\bx profile\b/i },
  { category: "links", key: "website", pattern: /\b(website|personal site|web ?site|url)\b/i },

  // --- Documents ---
  { category: "document", key: "resume", pattern: /\b(resume|résumé|\bcv\b)\b/i },
  { category: "document", key: "cover_letter", pattern: /\bcover letter\b/i },

  // --- Compliance / EEO ---
  { category: "work_authorization", key: "sponsorship", pattern: /\b(sponsor|sponsorship|visa)\b/i },
  { category: "work_authorization", key: "work_authorization", pattern: /\b(legally )?authoriz(ed|ation) to work\b|\bwork authoriz/i },
  { category: "eeo", key: "gender", pattern: /\bgender\b|\bsex\b/i },
  { category: "eeo", key: "race", pattern: /\b(race|ethnicit|hispanic|latino)\b/i },
  { category: "eeo", key: "veteran_status", pattern: /\bveteran\b|\bmilitary service\b|\bprotected veteran\b/i },
  { category: "eeo", key: "disability_status", pattern: /\bdisabilit/i },

  // --- Background ---
  { category: "education", key: "school", pattern: /\b(school|university|college|institution)\b/i },
  { category: "education", key: "degree", pattern: /\bdegree\b/i },
  { category: "education", key: "discipline", pattern: /\b(discipline|major|field of study)\b/i },
  { category: "education", key: "graduation_year", pattern: /\b(graduation|end date|completion) (year|date)\b/i },
  { category: "experience", key: "current_company", pattern: /\bcurrent (company|employer)\b|\bmost recent employer\b/i },
  { category: "experience", key: "current_title", pattern: /\bcurrent (title|role|position)\b/i },
  { category: "experience", key: "years_experience", pattern: /\byears? of (relevant )?experience\b/i },
  { category: "compensation", key: "salary_expectation", pattern: /\b(salary|compensation|pay) (expectation|requirement|range)\b|\bdesired (salary|compensation)\b|\bexpected (salary|compensation)\b/i },
  { category: "referral", key: "referral_source", pattern: /\bhow did you (hear|find out)\b|\breferr?(al|ed by)\b/i },
  { category: "consent", key: "consent", pattern: /\b(consent|agree to|privacy policy|terms|gdpr|data processing)\b/i },
  { category: "start_date", key: "start_date", pattern: /\b(start date|available to start|earliest start|notice period)\b/i },
];

/** Free-text controls with no category match are screening questions. */
const FREE_TEXT_TYPES = new Set(["textarea", "text", "email", "tel", "url", "search"]);

/** Controls that present a fixed option list, native or custom-rendered. */
const CHOICE_TYPES = new Set(["select", "radio", "checkbox", "combobox", "react-select", "listbox"]);

const ADAPTER_DEFINITIONS = [
  {
    id: "greenhouse",
    label: "Greenhouse",
    hosts: [/(^|\.)greenhouse\.io$/i, /(^|\.)grnh\.se$/i],
    htmlHints: [/boards\.greenhouse\.io/i, /job-boards\.greenhouse\.io/i, /greenhouse_iframe/i],
    dropdownStrategy: "react-select",
    submitLabels: [/^submit application$/i],
    accountWallCommon: false,
    // The board API returns questions/options as JSON with no JS rendering.
    // It is incomplete: Country, EEO, GDPR consent and reCAPTCHA are DOM-only.
    schemaUrl(url) {
      const match = String(url).match(/greenhouse\.io\/(?:embed\/job_app\?for=)?([^/?#]+)(?:\/jobs)?\/(\d+)/i);
      return match
        ? `https://boards-api.greenhouse.io/v1/boards/${match[1]}/jobs/${match[2]}?questions=true`
        : "";
    },
    notes: "react-select dropdowns; scope option queries to the open menu; verify via .select__control innerText.",
  },
  {
    id: "ashby",
    label: "Ashby",
    hosts: [/(^|\.)ashbyhq\.com$/i],
    htmlHints: [/jobs\.ashbyhq\.com/i, /_ashby_embed/i],
    dropdownStrategy: "react-select",
    submitLabels: [/^submit application$/i, /^submit$/i],
    accountWallCommon: false,
    schemaUrl() {
      return "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting";
    },
    notes: "Public GraphQL preflight exposes form sections; final submit may need a browser reCAPTCHA token.",
  },
  {
    id: "lever",
    label: "Lever",
    hosts: [/(^|\.)lever\.co$/i],
    htmlHints: [/jobs\.lever\.co/i, /lever-application/i],
    dropdownStrategy: "native",
    submitLabels: [/^submit application$/i],
    accountWallCommon: false,
    schemaUrl(url) {
      const match = String(url).match(/lever\.co\/([^/?#]+)\/([0-9a-f-]{36})/i);
      return match ? `https://api.lever.co/v0/postings/${match[1]}/${match[2]}` : "";
    },
    notes: "Mostly plain inputs and native selects; custom cards use name=\"cards[...]\" grouping.",
  },
  {
    id: "workday",
    label: "Workday",
    hosts: [/(^|\.)myworkdayjobs\.com$/i, /(^|\.)myworkdaysite\.com$/i, /(^|\.)wd\d+\.myworkdayjobs\.com$/i],
    htmlHints: [/data-automation-id/i, /workday/i],
    dropdownStrategy: "workday-listbox",
    submitLabels: [/^submit$/i],
    accountWallCommon: true,
    schemaUrl() {
      return "";
    },
    notes: "Nearly always account-walled. Target data-automation-id, not CSS classes; multi-step wizard.",
  },
  {
    id: "icims",
    label: "iCIMS",
    hosts: [/(^|\.)icims\.com$/i],
    htmlHints: [/icims/i, /icims_content_iframe/i],
    dropdownStrategy: "native",
    submitLabels: [/^submit$/i, /^submit application$/i],
    accountWallCommon: true,
    schemaUrl() {
      return "";
    },
    notes: "Form lives inside #icims_content_iframe; account/profile creation is the norm.",
  },
  {
    id: "adp",
    label: "ADP",
    hosts: [/(^|\.)adp\.com$/i, /workforcenow\.adp\.com$/i],
    htmlHints: [/workforcenow\.adp\.com/i, /adp-careers/i],
    dropdownStrategy: "native",
    submitLabels: [/^submit$/i, /^submit application$/i],
    accountWallCommon: true,
    schemaUrl() {
      return "";
    },
    notes: "Recruitment module often requires a candidate account before the form renders.",
  },
  {
    id: "smartrecruiters",
    label: "SmartRecruiters",
    hosts: [/(^|\.)smartrecruiters\.com$/i],
    htmlHints: [/smartrecruiters/i, /sr-jobad/i],
    dropdownStrategy: "native",
    submitLabels: [/^submit application$/i, /^apply$/i],
    accountWallCommon: false,
    schemaUrl(url) {
      const match = String(url).match(/smartrecruiters\.com\/([^/?#]+)\/(\d+)/i);
      return match ? `https://api.smartrecruiters.com/v1/companies/${match[1]}/postings/${match[2]}` : "";
    },
    notes: "Public posting API exposes the JD; the apply form still needs DOM reconciliation.",
  },
  {
    id: "linkedin_easy_apply",
    label: "LinkedIn Easy Apply",
    hosts: [/(^|\.)linkedin\.com$/i],
    htmlHints: [/jobs-easy-apply/i, /easy apply/i],
    dropdownStrategy: "linkedin-typeahead",
    submitLabels: [/^submit application$/i],
    accountWallCommon: false,
    schemaUrl() {
      return "";
    },
    notes: "Modal wizard. Short-answer fields carry visible character counters; verify counts, not just values.",
  },
];

export const ADAPTERS = ADAPTER_DEFINITIONS.map((adapter) => Object.freeze({ ...adapter }));

const ADAPTER_BY_ID = new Map(ADAPTERS.map((adapter) => [adapter.id, adapter]));

export function getAdapter(id) {
  return ADAPTER_BY_ID.get(String(id || "").toLowerCase()) || null;
}

function hostOf(url) {
  try {
    return new URL(String(url)).hostname.toLowerCase();
  } catch {
    return "";
  }
}

/**
 * Identify the ATS behind a posting. Host match is authoritative; HTML hints
 * catch the common case of a company careers domain embedding an ATS iframe.
 */
export function detectAdapter({ url = "", html = "", pageText = "" } = {}) {
  const host = hostOf(url);
  if (host) {
    for (const adapter of ADAPTERS) {
      if (adapter.hosts.some((pattern) => pattern.test(host))) {
        return { adapter, confidence: "host", matched_on: host };
      }
    }
  }
  const haystack = `${html}\n${pageText}`;
  if (haystack.trim()) {
    for (const adapter of ADAPTERS) {
      const hint = adapter.htmlHints.find((pattern) => pattern.test(haystack));
      if (hint) return { adapter, confidence: "embedded", matched_on: String(hint) };
    }
  }
  return { adapter: null, confidence: "none", matched_on: "" };
}

/** Collapse a label to comparable text: lowercase, no punctuation or markers. */
export function normalizeLabel(value) {
  return String(value ?? "")
    .replace(/\*/g, " ")
    .replace(/\(required\)|\(optional\)/gi, " ")
    .replace(/[‘’]/g, "'")
    .replace(/[^a-z0-9'&/+ -]/gi, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/**
 * Decide what a field is and whether the agent may type into it.
 * Returns `{ category, key, safe, reason }`. `safe: false` never means "try
 * harder" — it means hand this field to the human or leave it blank.
 */
export function classifyField(field = {}) {
  const type = String(field.type || "text").toLowerCase();
  if (type === "password") {
    return { category: "credential", key: null, safe: false, reason: "credential must be completed by a human" };
  }

  const haystack = [field.label, field.name, field.id, field.placeholder, field.autocomplete]
    .filter(Boolean)
    .map((part) => normalizeLabel(part))
    .join(" ");

  for (const rule of CATEGORY_RULES) {
    if (!rule.pattern.test(haystack)) continue;
    if (rule.unless && rule.unless.test(haystack)) continue;
    const safe = !NEVER_FILL_CATEGORIES.has(rule.category);
    return {
      category: rule.category,
      key: rule.key,
      safe,
      reason: safe ? "" : `${rule.category} must be completed by a human`,
    };
  }

  // ATS upload controls frequently expose only a generic internal id such as
  // `file-input`. If no label rule matched, the primary file control on an
  // application is the resume upload. Cover-letter controls are still caught
  // by the explicit label rule above.
  if (type === "file") {
    return { category: "document", key: "resume", safe: true, reason: "" };
  }

  // `combobox` covers react-select/Workday listboxes, which is what most
  // modern ATS screening questions render as. Omitting it classified every
  // custom dropdown as an unknown widget and blocked the form.
  if (FREE_TEXT_TYPES.has(type) || CHOICE_TYPES.has(type)) {
    return { category: "screening", key: null, safe: true, reason: "" };
  }
  return { category: "unknown", key: null, safe: false, reason: `unsupported control type: ${type}` };
}

export function isRequired(field = {}) {
  if (field.required === true) return true;
  if (String(field.ariaRequired).toLowerCase() === "true") return true;
  return /\*|\brequired\b/i.test(String(field.label || ""));
}

/**
 * Match an intended answer against a control's real option list.
 *
 * Exact match wins. A partial match must be anchored at a word boundary AND
 * be unique — a loose `hasText: "Man"` filter once matched "Cisgender woman"
 * on a live form and would have submitted the wrong gender.
 */
export function matchOption(options, answer, { exactOnly = false } = {}) {
  const list = (options || []).map((option) => String(option));
  const wanted = String(answer ?? "").trim();
  if (!wanted) return { ok: false, reason: "no answer" };

  const exact = list.filter((option) => option.trim().toLowerCase() === wanted.toLowerCase());
  if (exact.length === 1) return { ok: true, option: exact[0], match: "exact" };
  if (exact.length > 1) return { ok: false, reason: "option_ambiguous", candidates: exact };
  // EEO and work-authorization answers must land on the literal option text.
  // Getting one of these subtly wrong is worse than leaving it for a human.
  if (exactOnly) return { ok: false, reason: "option_not_found_exact", candidates: list.slice(0, 25) };

  const boundary = new RegExp(`\\b${wanted.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i");
  const partial = list.filter((option) => boundary.test(option));
  if (partial.length === 1) return { ok: true, option: partial[0], match: "word-boundary" };
  if (partial.length > 1) return { ok: false, reason: "option_ambiguous", candidates: partial };
  return { ok: false, reason: "option_not_found", candidates: list.slice(0, 25) };
}

/** Look up an answer by field id, name, normalized label, then canonical key. */
function resolveAnswer(field, classification, answers) {
  const lookups = [
    field.id,
    field.name,
    field.selector,
    normalizeLabel(field.label),
    classification.key,
  ];
  for (const lookup of lookups) {
    if (!lookup) continue;
    if (Object.prototype.hasOwnProperty.call(answers, lookup)) {
      return { value: answers[lookup], matched_on: lookup };
    }
    const normalized = normalizeLabel(lookup);
    if (normalized && Object.prototype.hasOwnProperty.call(answers, normalized)) {
      return { value: answers[normalized], matched_on: normalized };
    }
  }
  return null;
}

/**
 * Spot the conditions that mean "stop and hand this to the user" rather than
 * "keep filling". Account walls, logins, CAPTCHA, OTP, and unknown required
 * widgets are never technical retry conditions.
 */
export function detectBlockers({ fields = [], pageText = "", url = "", adapterId = "" } = {}) {
  const blockers = [];
  const text = String(pageText);
  const add = (type, detail) => {
    if (blockers.some((item) => item.type === type)) return;
    blockers.push({ type, detail, blocking: BLOCKING_BLOCKERS.has(type) });
  };

  const classified = fields.map((field) => ({ field, classification: classifyField(field) }));
  const hasPassword = classified.some(({ classification }) => classification.category === "credential");
  const hasOtp = classified.some(({ classification }) => classification.category === "otp");

  if (hasOtp || /\b(enter the (verification|security) code|we (sent|emailed) you a code|check your email for a code)\b/i.test(text)) {
    add("otp", "A one-time code is required. the user enters it; the agent never types or reads codes.");
  }
  if (hasPassword && /\b(create (an )?account|sign up|register|create your profile|set a password)\b/i.test(text)) {
    add("account_wall", "The form requires creating an account before applying.");
  } else if (hasPassword) {
    add("login", "The page is asking for a password. the user signs in.");
  } else if (/\b(create an account to apply|sign up to apply|you must (create|have) an account)\b/i.test(text)) {
    add("account_wall", "The posting states an account is required to apply.");
  } else if (/\b(sign in to (apply|continue)|log ?in to (apply|continue)|already have an account)\b/i.test(text)) {
    add("login", "The page requires an existing login.");
  }
  if (
    classified.some(({ classification }) => classification.category === "captcha") ||
    /\b(recaptcha|hcaptcha|i'?m not a robot|verify you are human)\b/i.test(text)
  ) {
    add("captcha", "A CAPTCHA is present and must be completed by a human.");
  }

  // A field with neither a label nor an addressable selector is widget
  // internals, not a question — Greenhouse's phone control ships a required
  // hidden-ish input like this, and treating it as unknown blocked every form.
  // A real question always carries a label.
  const unknownRequired = classified.filter(
    ({ field, classification }) =>
      classification.category === "unknown" &&
      isRequired(field) &&
      (String(field.label || "").trim() || String(field.selector || "").trim()),
  );
  if (unknownRequired.length) {
    add(
      "unknown_widget",
      `Required control(s) the adapter cannot classify: ${unknownRequired
        .map(({ field }) => field.label || field.selector || field.id || "unlabeled")
        .slice(0, 5)
        .join("; ")}`,
    );
  }

  const adapter = getAdapter(adapterId);
  if (adapter?.accountWallCommon && !blockers.length && !fields.length) {
    add("account_wall", `${adapter.label} postings usually require a candidate account; no form fields were readable.`);
  }
  if (!blockers.length && !fields.length && url) {
    add("unknown_widget", "No form fields were readable on the page.");
  }
  return blockers;
}

/**
 * Turn inspected fields plus an intended answer map into an explicit fill plan.
 *
 * Nothing is filled unless an answer was supplied for it, so a missing profile
 * value shows up as `missing_required` rather than as an invented value. An
 * answer longer than the control's `maxlength` is refused, not truncated —
 * browsers truncate silently and a "successful" fill once cut a real answer
 * mid-sentence at 255 characters.
 */
export function planFill(fields = [], answers = {}, { adapterId = "" } = {}) {
  const adapter = getAdapter(adapterId);
  const plan = { adapter: adapter?.id || "", fills: [], skipped: [], missing_required: [], human_required: [] };

  for (const field of fields) {
    const classification = classifyField(field);
    const required = isRequired(field);
    const base = {
      selector: field.selector || "",
      id: field.id || "",
      name: field.name || "",
      label: field.label || "",
      category: classification.category,
      key: classification.key,
      type: String(field.type || "text").toLowerCase(),
      required,
    };

    // Framework internals can inherit a required marker while exposing no
    // label, id, name, or selector. They are not questions and cannot be
    // addressed; do not report them as missing user data.
    if (!base.selector && !base.id && !base.name && !base.label) {
      plan.skipped.push({ ...base, reason: "unaddressable widget internal" });
      continue;
    }

    if (!classification.safe) {
      const entry = { ...base, reason: classification.reason };
      plan.skipped.push(entry);
      if (HUMAN_HANDOFF_CATEGORIES.has(classification.category) || required) plan.human_required.push(entry);
      continue;
    }

    const answer = resolveAnswer(field, classification, answers);
    if (answer === null || answer.value === undefined || answer.value === null || answer.value === "") {
      const entry = { ...base, reason: "no answer supplied" };
      plan.skipped.push(entry);
      if (required) plan.missing_required.push(entry);
      continue;
    }

    const value = String(answer.value);

    // Ashby exposes each radio option as its own inspected field, with an
    // empty `options` array. When the caller explicitly addresses that exact
    // input by id/selector and supplies a truthy value, click that input
    // directly. Do not use a shared radio `name` here: doing so would plan
    // every option in the group and the last click would silently win.
    if (
      base.type === "radio" &&
      field.options.length === 0 &&
      (
        answer.matched_on === field.id ||
        answer.matched_on === field.selector ||
        answer.matched_on === normalizeLabel(field.label)
      ) &&
      /^(true|yes|1|on|checked)$/i.test(value)
    ) {
      plan.fills.push({
        ...base,
        strategy: "radio-direct",
        value: true,
        intended_length: 0,
        matched_on: answer.matched_on,
      });
      continue;
    }

    if (base.type === "select" || base.type === "radio" || base.type === "react-select" || base.type === "combobox") {
      // Native <select>/<radio> options are readable at inspect time, so
      // validate against them up front. react-select/Workday listboxes never
      // populate field.options in a static DOM read (the option list only
      // exists once the menu is opened) — matching against an always-empty
      // list would skip every combobox regardless of a correct answer. For
      // those, defer to the live click-based resolution in applyExpression,
      // which reads the real open menu and only clicks an exact text match;
      // verifyReadback still catches a bad/missing option after the fact, so
      // this does not weaken the exact-match safety guarantee.
      const liveResolution = field.options.length === 0 && (base.type === "combobox" || base.type === "react-select");
      if (liveResolution) {
        plan.fills.push({
          ...base,
          strategy: adapter?.dropdownStrategy || "native",
          value,
          intended_length: value.length,
          matched_on: answer.matched_on,
          option_match: "live",
        });
        continue;
      }
      const exactOnly = EXACT_OPTION_CATEGORIES.has(classification.category);
      const match = matchOption(field.options, value, { exactOnly });
      if (!match.ok) {
        const entry = { ...base, reason: match.reason, intended: value, candidates: match.candidates };
        plan.skipped.push(entry);
        if (required) plan.missing_required.push(entry);
        continue;
      }
      plan.fills.push({
        ...base,
        strategy: adapter?.dropdownStrategy || "native",
        value: match.option,
        intended_length: match.option.length,
        matched_on: answer.matched_on,
        option_match: match.match,
      });
      continue;
    }

    if (base.type === "file") {
      plan.fills.push({ ...base, strategy: "file", value, intended_length: value.length, matched_on: answer.matched_on });
      continue;
    }

    if (base.type === "checkbox") {
      const checked = value === true || /^(true|yes|1|on|checked)$/i.test(value);
      plan.fills.push({ ...base, strategy: "checkbox", value: checked, intended_length: 0, matched_on: answer.matched_on });
      continue;
    }

    const maxlength = Number.isInteger(field.maxlength) && field.maxlength > 0 ? field.maxlength : null;
    if (maxlength && value.length > maxlength) {
      const entry = {
        ...base,
        reason: "answer_exceeds_maxlength",
        maxlength,
        intended_length: value.length,
        detail: `Rewrite to ${maxlength} characters or fewer; the browser would truncate silently.`,
      };
      plan.skipped.push(entry);
      if (required) plan.missing_required.push(entry);
      continue;
    }

    plan.fills.push({
      ...base,
      strategy: "type",
      value,
      intended_length: value.length,
      maxlength,
      matched_on: answer.matched_on,
    });
  }
  // A radio group is required as a group, not once per option. Once one
  // explicitly targeted choice is planned, the unanswered sibling inputs
  // must not each remain in `missing_required`.
  const answeredRadioGroups = new Set(
    plan.fills
      .filter((fill) => fill.strategy === "radio-direct" && fill.name)
      .map((fill) => fill.name),
  );
  plan.missing_required = plan.missing_required.filter(
    (entry) => !(entry.type === "radio" && entry.name && answeredRadioGroups.has(entry.name)),
  );
  return plan;
}

/**
 * Compare what the page actually holds against what the plan intended.
 *
 * Read-back alone is not proof: a stored length equal to `maxlength` is
 * treated as truncated until shown otherwise, because that is exactly what a
 * silent cut looks like.
 */
export function verifyReadback(plan, observed = {}) {
  const mismatches = [];
  const verified = [];

  for (const fill of plan.fills || []) {
    const key = fill.selector || fill.id;
    const actual = observed[key];
    const record = { selector: key, label: fill.label, category: fill.category };

    if (actual === undefined || actual === null) {
      mismatches.push({ ...record, reason: "not_readable", intended: fill.value });
      continue;
    }

    if (fill.strategy === "checkbox" || fill.strategy === "radio-direct") {
      const checked = actual.checked ?? actual.value;
      if (Boolean(checked) !== Boolean(fill.value)) {
        mismatches.push({
          ...record,
          reason: fill.strategy === "radio-direct" ? "radio_state_mismatch" : "checkbox_state_mismatch",
          intended: fill.value,
          actual: checked,
        });
      } else verified.push(record);
      continue;
    }

    if (fill.strategy === "file") {
      const name = String(actual.fileName ?? actual.value ?? "");
      if (!name || !fill.value.endsWith(name)) {
        mismatches.push({ ...record, reason: "file_not_attached", intended: fill.value, actual: name });
      } else verified.push(record);
      continue;
    }

    // Greenhouse's phone-country combobox intentionally renders only the
    // dial code. Preserve the strict semantic check by requiring both the US
    // flag class and +1 instead of pretending the visible text says the full
    // country name.
    if (
      fill.type === "combobox" &&
      fill.id === "country" &&
      String(fill.value).toLowerCase() === "united states" &&
      actual.countryCode === "us" &&
      String(actual.controlText || "").trim() === "+1"
    ) {
      verified.push(record);
      continue;
    }

    // react-select and Workday listboxes keep the input's value empty after a
    // successful selection; the rendered control text is the real answer.
    // Ordinary inputs live in wrappers whose `controlText` is legitimately
    // empty. Nullish coalescing chose that empty wrapper text before the real
    // input value and falsely reported every React text field as blank.
    // Choose the source by control kind, then fall back only across non-empty
    // strings.
    let rawActual;
    if (fill.strategy === "type") {
      rawActual = actual.value;
    } else if (fill.type === "select") {
      rawActual = actual.selectedText || actual.value;
    } else {
      rawActual = actual.controlText || actual.displayText || actual.selectedText || actual.value;
    }
    const actualValue = String(rawActual ?? "").trim();

    // Phone widgets often store only the national number because the +1 is
    // held in a sibling country-code control. Compare the canonical last ten
    // digits instead of rejecting harmless display formatting.
    if (fill.category === "identity" && fill.key === "phone") {
      const intendedDigits = String(fill.value).replace(/\D/g, "");
      const actualDigits = actualValue.replace(/\D/g, "");
      if (intendedDigits.length >= 10 && actualDigits.length >= 10 &&
          intendedDigits.slice(-10) === actualDigits.slice(-10)) {
        verified.push(record);
        continue;
      }
    }

    if (!actualValue) {
      mismatches.push({ ...record, reason: "empty_after_fill", intended: fill.value });
      continue;
    }
    if (fill.strategy === "type") {
      if (actualValue.length !== fill.intended_length) {
        mismatches.push({
          ...record,
          reason: "length_mismatch",
          intended_length: fill.intended_length,
          actual_length: actualValue.length,
        });
        continue;
      }
      const maxlength = actual.maxlength ?? fill.maxlength ?? null;
      if (maxlength && actualValue.length === maxlength) {
        mismatches.push({
          ...record,
          reason: "at_maxlength_treat_as_truncated",
          intended_length: fill.intended_length,
          maxlength,
        });
        continue;
      }
      if (actualValue !== fill.value) {
        mismatches.push({ ...record, reason: "value_mismatch", intended: fill.value, actual: actualValue });
        continue;
      }
    } else if (actualValue.toLowerCase() !== String(fill.value).toLowerCase()) {
      mismatches.push({ ...record, reason: "selection_mismatch", intended: fill.value, actual: actualValue });
      continue;
    }
    verified.push(record);
  }

  return { verified, mismatches, ok: mismatches.length === 0 };
}

/** True when a control looks like the irreversible final submit for this ATS. */
export function isFinalSubmitControl(adapterId, label) {
  const text = String(label || "").trim();
  if (!text) return false;
  const adapter = getAdapter(adapterId);
  const patterns = adapter?.submitLabels || [/^submit application$/i, /^submit$/i];
  return patterns.some((pattern) => pattern.test(text)) || /^submit\b/i.test(text);
}

/**
 * Browser-side field harvester. Returns a JS expression string for
 * `Runtime.evaluate`; keeping it here means the DOM contract and the
 * classification rules stay in one file.
 */
export function fieldInspectionExpression() {
  return `(() => {
    // SmartRecruiters' OneClick form renders its real controls inside open
    // shadow roots (spl-input, spl-dropzone, and friends). Standard
    // document.querySelectorAll cannot see them, so walk every open root.
    const deepQueryAll = (selector) => {
      const matches = [];
      const visit = (root) => {
        matches.push(...root.querySelectorAll(selector));
        for (const host of root.querySelectorAll('*')) {
          if (host.shadowRoot) visit(host.shadowRoot);
        }
      };
      visit(document);
      return matches;
    };
    const deepQuery = (selector) => deepQueryAll(selector)[0] || null;
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return style.display !== 'none' && style.visibility !== 'hidden' && (rect.width > 0 || rect.height > 0);
    };
    const labelFor = (el) => {
      const root = el.getRootNode?.() || document;
      const byFor = el.id ? root.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
      if (byFor?.innerText?.replace(/\\*/g, '').trim()) return byFor.innerText.trim();
      const wrapping = el.closest('label');
      if (wrapping?.innerText?.replace(/\\*/g, '').trim()) return wrapping.innerText.trim();
      const labelled = el.getAttribute('aria-labelledby');
      if (labelled) {
        const text = labelled.split(/\\s+/).map((id) => root.getElementById?.(id)?.innerText || '').join(' ').trim();
        if (text) return text;
      }
      const fieldEntryLabel = el.closest('[data-field-path]')?.querySelector('label')?.innerText?.trim();
      if (fieldEntryLabel) return fieldEntryLabel;
      const composedParent = (node) => node?.parentElement || node?.getRootNode?.().host || null;
      if (el.getAttribute('role') === 'radio' || el.tagName === 'SPL-RADIO') {
        const option = (el.getAttribute('label') || el.innerText || '').trim();
        let parent = composedParent(el);
        for (let depth = 0; parent && depth < 10; depth += 1, parent = composedParent(parent)) {
          if (parent.tagName === 'SPL-RADIO-GROUP') {
            const question = (parent.innerText || parent.getAttribute('aria-label') || '').trim();
            if (question && option) return question + ': ' + option;
          }
        }
      }
      if (el.tagName === 'SPL-CHECKBOX' && el.innerText?.trim()) return el.innerText.trim();
      // Cross open shadow boundaries to the owning SmartRecruiters component;
      // its aria-label contains the real visible question while the internal
      // control's own label is often just an asterisk.
      let owner = composedParent(el);
      for (let depth = 0; owner && depth < 12; depth += 1, owner = composedParent(owner)) {
        const aria = (owner.getAttribute?.('aria-label') || '').replace(/^Select\\s+/i, '').trim();
        if (aria) return aria;
        const explicit = (owner.getAttribute?.('label') || '').trim();
        if (explicit) return explicit;
        if (/^SPL-(AUTOCOMPLETE|MULTISELECT-AUTOCOMPLETE)$/.test(owner.tagName)) {
          const text = (owner.innerText || '').trim();
          if (text) return text;
        }
      }
      // LinkedIn's custom radios are visually represented by a sibling while
      // the input itself has zero dimensions. Its aria-label is the question
      // and the sibling text is the option, so preserve both as one exact,
      // auditable answer target.
      if (el.type === 'radio' && el.getAttribute('aria-label')) {
        const option = (el.parentElement?.parentElement?.innerText || '').trim();
        if (option) return el.getAttribute('aria-label').trim() + ': ' + option;
      }
      return (el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || '').trim();
    };
    const selectorFor = (el) => {
      if (el.id) return '[id="' + el.id.replaceAll('"', '\\\\"') + '"]';
      if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name.replaceAll('"', '\\\\"') + '"]';
      const fieldPath = el.closest('[data-field-path]')?.getAttribute('data-field-path');
      if (fieldPath) {
        const role = el.getAttribute('role');
        const rolePart = role ? '[role="' + role.replaceAll('"', '\\\\"') + '"]' : '';
        return '[data-field-path="' + fieldPath.replaceAll('"', '\\\\"') + '"] ' + el.tagName.toLowerCase() + rolePart;
      }
      return '';
    };
    const controls = deepQueryAll('input, textarea, select, spl-radio, spl-checkbox, [role="radio"], [role="combobox"], [role="listbox"]');
    const seen = new Set();
    const fields = [];
    for (const el of controls) {
      if (el.type === 'hidden' || (!visible(el) && el.type !== 'file' && el.type !== 'radio')) continue;
      const selector = selectorFor(el);
      const key = selector || (el.name + ':' + el.type);
      if (seen.has(key) || !key) continue;
      seen.add(key);
      let type = el.tagName === 'TEXTAREA' ? 'textarea' : el.tagName === 'SELECT' ? 'select' : (el.type || 'text');
      if (el.tagName === 'SPL-RADIO' || el.getAttribute('role') === 'radio') type = 'radio';
      if (el.tagName === 'SPL-CHECKBOX') type = 'checkbox';
      // A real <select> can still carry role="combobox" for accessibility
      // (seen on isolved's isolvedhire ATS) — don't let that reclassify an
      // already-correct native select as a react-select-style combobox, or
      // its statically-readable <option> list gets ignored and the field
      // gets routed through click-driven menu resolution that doesn't apply
      // to a real <select> (native selects open an OS popup, not a DOM menu).
      if (type !== 'select' && (el.getAttribute('role') === 'combobox' || el.classList.contains('select__input'))) type = 'combobox';
      const options = el.tagName === 'SELECT'
        ? [...el.options].map((option) => option.text.trim()).filter(Boolean)
        : [];
      const ariaLabel = el.getAttribute('aria-label') || '';
      const requiredByVisibleMarker = el.type === 'radio' && ariaLabel &&
        (document.body?.innerText || '').includes(ariaLabel + '*');
      const requiredByFieldEntry = Boolean(
        el.closest('[data-field-path]')?.querySelector('label[class*="required"]'),
      );
      fields.push({
        selector,
        id: el.id || '',
        name: el.name || '',
        type,
        label: labelFor(el),
        placeholder: el.getAttribute('placeholder') || '',
        autocomplete: el.getAttribute('autocomplete') || '',
        required: Boolean(el.required) || el.getAttribute('aria-required') === 'true' || Boolean(requiredByVisibleMarker) || requiredByFieldEntry,
        ariaRequired: el.getAttribute('aria-required') || '',
        maxlength: el.maxLength && el.maxLength > 0 ? el.maxLength : null,
        options,
        value_present: Boolean(el.value),
      });
    }
    const buttons = deepQueryAll('button, input[type="submit"], [role="button"]')
      .map((el) => (el.innerText || el.value || '').trim())
      .filter(Boolean)
      .slice(0, 40);
    const errors = deepQueryAll('[role="alert"], .field-error, .error-message, .input-error, [aria-invalid="true"]')
      .map((el) => (el.innerText || '').trim())
      .filter(Boolean)
      .slice(0, 20);
    return {
      url: location.href,
      title: document.title,
      heading: document.querySelector('h1')?.innerText?.trim() || '',
      fields,
      buttons,
      errors,
      has_captcha_frame: Boolean(deepQuery('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], .g-recaptcha')),
      page_text: (document.body?.innerText || '').slice(0, 8000),
    };
  })()`;
}
