(() => {
"use strict";

const PROMPT_DEFAULT = __PROMPT_CONFIG_DEFAULT_JSON__;
const PROMPT_PRESETS = __PROMPT_PRESETS_JSON__;
const PLACEHOLDERS = __PLACEHOLDERS_JSON__;
const APP_DEFAULT = __APP_CONFIG_DEFAULT_JSON__;

const STORAGE_KEY = "paperless-local-ai-demo-v2";

const TAGS = [
  {id: 101, name: "Home", parent: null},
  {id: 102, name: "Utilities", parent: 101},
  {id: 103, name: "Finance", parent: null},
  {id: 104, name: "Banking", parent: 103},
  {id: 105, name: "Insurance", parent: 103},
  {id: 106, name: "Work", parent: null},
  {id: 107, name: "Vehicle", parent: null},
  {id: 108, name: "Purchases", parent: null}
];

const DOCUMENT_TYPES = ["Invoice", "Contract", "Letter", "Statement", "Certificate"];
const CORRESPONDENTS = ["Example Energy GmbH", "Demo Bank AG", "Sample Insurance AG"];

const DOCUMENTS = {
  4711: {
    id: 4711,
    current_title: "scan_2026_01_18",
    current_created: "2026-01-18",
    content: `Example Energy GmbH
Customer: Erika Example
Annual electricity statement
Billing period: 2025-01-01 to 2025-12-31
Meter number: DEMO-1842
Electricity consumption: 2,184 kWh
Invoice amount: EUR 684.27
Invoice date: 2026-01-18
This document is a synthetic fixture for the paperless-local-ai public demo.`,
    history_evidence: {similarity: 0.91, support: 4, winner_share: 0.86, tags: ["Utilities"]},
    examples: [
      {id: 4601, title: "Electricity statement 2024", tags: ["Utilities"], excerpt: "Annual electricity statement and meter reading."},
      {id: 4520, title: "Utility advance payment", tags: ["Utilities"], excerpt: "Monthly utility advance payment notice."}
    ],
    result: {
      title: "Electricity annual statement 2025",
      document_type: "Invoice",
      correspondent: "Example Energy GmbH",
      tags: ["Utilities"],
      created: "2026-01-18"
    }
  },
  4712: {
    id: 4712,
    current_title: "document_4712",
    current_created: "2026-02-05",
    content: `Sample Insurance AG
Policy holder: Max Example
Policy number: DEMO-90017
Annual premium invoice for household insurance
Coverage period: 2026-03-01 to 2027-02-28
Premium due: EUR 148.00
Issue date: 2026-02-05
This document is a synthetic fixture for the paperless-local-ai public demo.`,
    history_evidence: {similarity: 0.54, support: 1, winner_share: 0.51, tags: ["Insurance"]},
    examples: [
      {id: 4505, title: "Household insurance renewal", tags: ["Insurance"], excerpt: "Renewal notice for household insurance."},
      {id: 4472, title: "Liability insurance premium", tags: ["Insurance"], excerpt: "Annual insurance premium notice."},
      {id: 4421, title: "Bank account statement", tags: ["Banking"], excerpt: "Monthly account statement with transactions."}
    ],
    result: {
      title: "Household insurance premium 2026",
      document_type: "Invoice",
      correspondent: "Sample Insurance AG",
      tags: ["Insurance"],
      created: "2026-02-05"
    }
  },
  4713: {
    id: 4713,
    current_title: "incoming_document",
    current_created: "2026-03-03",
    content: `Example Services Ltd.
Reference: DEMO-771
General information notice
Thank you for your enquiry. This letter confirms that your request was received.
No invoice, contract, insurance policy, employment matter, vehicle matter or banking transaction is contained in this notice.
Issue date: 2026-03-03
This document is a synthetic fixture for the paperless-local-ai public demo.`,
    history_evidence: null,
    examples: [
      {id: 4388, title: "General service notice", tags: [], excerpt: "Generic acknowledgement without a filing category."}
    ],
    result: {
      title: "Request acknowledgement",
      document_type: "Letter",
      correspondent: "Example Services Ltd.",
      tags: [],
      created: "2026-03-03"
    }
  }
};

const HISTORY_HEALTH = {
  status: "Ready",
  cache_state: "ready",
  stale: false,
  reviewed_documents: 42,
  source: {reviewed_documents: 42},
  tags_represented: 7,
  eligible_tags: 8,
  estimated_reuse_sample_size: 42,
  estimated_reuse_percent: 57,
  potential_inconsistency_count: 1,
  last_updated: "2026-08-28T08:42:00Z",
  per_tag: [
    {name: "Utilities", count: 9, status: "Strong"},
    {name: "Banking", count: 8, status: "Strong"},
    {name: "Insurance", count: 6, status: "Good"},
    {name: "Work", count: 7, status: "Good"},
    {name: "Vehicle", count: 4, status: "Building"},
    {name: "Purchases", count: 5, status: "Good"},
    {name: "Home", count: 3, status: "Building"}
  ],
  potential_inconsistencies: [
    {
      documents: 3,
      tag_sets: [{tags: ["Banking"], count: 2}, {tags: ["Finance"], count: 1}],
      examples: [
        {id: 4320, title: "Monthly account statement", tags: ["Banking"]},
        {id: 4311, title: "Account information", tags: ["Finance"]},
        {id: 4298, title: "Quarterly account statement", tags: ["Banking"]}
      ],
      truncated: false
    }
  ]
};

const clone = value => JSON.parse(JSON.stringify(value));
const nowIso = () => new Date().toISOString();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function initialState() {
  const promptConfig = clone(PROMPT_DEFAULT);
  promptConfig.version = 3;
  promptConfig.updated_at = "2026-08-28T08:30:00Z";
  promptConfig.tag_guidance = {
    "102": "Electricity, gas, water and other household utility bills or statements.",
    "104": "Bank accounts, account statements and banking correspondence.",
    "105": "Insurance policies, premiums, claims and insurer correspondence."
  };

  const appConfig = clone(APP_DEFAULT);
  appConfig.version = 2;
  appConfig.updated_at = "2026-08-28T08:20:00Z";
  appConfig.connections.paperless_url = "http://paperless:8000";
  appConfig.connections.ollama_url = "http://ollama:11434";
  appConfig.ocr.language = "en";
  appConfig.ocr.model_profile = "medium";

  return {
    promptConfig,
    appConfig,
    promptHistory: [
      {
        file: "prompt-config-v0002-demo.json",
        version: 2,
        updated_at: "2026-08-27T18:12:00Z",
        summary: "qwen3.5:4b · Hybrid tagging",
        config: {...clone(promptConfig), version: 2, updated_at: "2026-08-27T18:12:00Z"}
      },
      {
        file: "prompt-config-v0001-demo.json",
        version: 1,
        updated_at: "2026-08-26T09:00:00Z",
        summary: "Initial demo classification settings",
        config: {...clone(PROMPT_DEFAULT), version: 1, updated_at: "2026-08-26T09:00:00Z"}
      }
    ],
    appHistory: [
      {
        file: "app-config-v0001-demo.json",
        version: 1,
        updated_at: "2026-08-27T17:55:00Z",
        summary: "Metadata writes enabled · PP-OCRv6 Medium · 3000 px",
        config: {...clone(appConfig), version: 1, updated_at: "2026-08-27T17:55:00Z"}
      }
    ],
    historyLastUpdated: HISTORY_HEALTH.last_updated
  };
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (_) {}
  return initialState();
}

let state = loadState();

function persist() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (_) {}
}

function reset() {
  try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
  location.reload();
}

function publicHistory(items) {
  return (items || []).map(item => {
    const copy = {...item};
    delete copy.config;
    return copy;
  });
}

function bodyJson(opts) {
  if (!opts || opts.body == null || opts.body === "") return {};
  if (typeof opts.body === "string") {
    try { return JSON.parse(opts.body); } catch (_) { return {}; }
  }
  return opts.body;
}

function placeholdersIn(text) {
  return [...String(text || "").matchAll(/{{\s*([A-Z0-9_]+)\s*}}/g)].map(match => match[1]);
}

function validatePromptConfig(raw) {
  if (!raw || typeof raw !== "object") throw new Error("Configuration must be a JSON object.");
  for (const key of ["system_prompt", "classification_template", "tagging_prompt", "model"]) {
    if (!String(raw[key] || "").trim()) throw new Error(`${key} must not be empty`);
  }

  const system = placeholdersIn(raw.system_prompt);
  const classification = placeholdersIn(raw.classification_template);
  const tagging = placeholdersIn(raw.tagging_prompt);
  const all = [...system, ...classification, ...tagging];
  const allowed = new Set(Object.keys(PLACEHOLDERS));
  const unknown = [...new Set(all.filter(name => !allowed.has(name)))].sort();
  if (unknown.length) throw new Error(`Unknown placeholders: ${unknown.join(", ")}`);
  if (system.includes("DOCUMENT_TEXT")) throw new Error("{{DOCUMENT_TEXT}} must not appear in the system prompt for security reasons");
  if (!classification.includes("DOCUMENT_TEXT")) throw new Error("classification_template must contain {{DOCUMENT_TEXT}}");

  const tagOnly = new Set(["TAGS_JSON", "TAGS_LINES", "MAX_TAGS", "TAG_GUIDANCE", "TAG_EXAMPLES"]);
  const misplaced = [...new Set([...system, ...classification].filter(name => tagOnly.has(name)))].sort();
  if (misplaced.length) throw new Error(`Tagging placeholders belong in tagging_prompt: ${misplaced.join(", ")}`);
  if (!["history_assisted", "llm_only"].includes(raw.tagging_mode)) throw new Error("Unsupported tagging mode");
  if (!Number.isInteger(Number(raw.max_tags)) || Number(raw.max_tags) < 1 || Number(raw.max_tags) > 10) {
    throw new Error("max_tags must be between 1 and 10");
  }
  return clone(raw);
}

function validateCorrespondentMatching(raw) {
  const value = raw || {};
  const minimum_similarity = Number(value.minimum_similarity ?? 0.91);
  const minimum_margin = Number(value.minimum_margin ?? 0.04);
  if (!Number.isFinite(minimum_similarity) || minimum_similarity < 0 || minimum_similarity > 1) {
    throw new Error("correspondent_matching.minimum_similarity must be between 0 and 1");
  }
  if (!Number.isFinite(minimum_margin) || minimum_margin < 0 || minimum_margin > 1) {
    throw new Error("correspondent_matching.minimum_margin must be between 0 and 1");
  }
  return {minimum_similarity, minimum_margin};
}

function validateAppConfig(raw) {
  if (!raw || typeof raw !== "object") throw new Error("App configuration must be a JSON object.");
  for (const key of ["paperless_url", "ollama_url"]) {
    const value = String(raw.connections?.[key] || "");
    if (!/^https?:\/\/[^/]+/i.test(value)) throw new Error(`connections.${key} must be a complete http(s) URL`);
  }
  const workflow = raw.workflow || {};
  const technical = [workflow.llm_queue_tag, workflow.llm_error_tag, workflow.review_tag].map(x => String(x || "").trim());
  if (technical.some(x => !x)) throw new Error("Technical workflow tags must not be empty");
  if (new Set(technical.map(x => x.toLowerCase())).size !== technical.length) {
    throw new Error("Technical workflow tags must have distinct names");
  }
  const candidate = clone(raw);
  candidate.correspondent_matching = validateCorrespondentMatching(raw.correspondent_matching);
  return candidate;
}

function normalizeCorrespondentName(value) {
  const folded = String(value || "").normalize("NFKC").toLowerCase().replace(/ß/g, "ss");
  return (folded.match(/[\p{L}\p{N}_]+/gu) || []).join(" ");
}

function plausibleCorrespondentCandidate(value) {
  const candidate = String(value || "").trim().replace(/\s+/g, " ");
  const normalized = normalizeCorrespondentName(candidate);
  if (!candidate || candidate.length > 255 || normalized.length < 2 || normalized.split(/\s+/).length > 20) return false;
  if (["unknown", "unbekannt", "none", "null", "n a", "nicht erkennbar", "kein absender"].includes(normalized)) return false;
  return /\p{L}/u.test(candidate);
}

function sequenceMatcherRatio(aText, bText) {
  const a = Array.from(aText), b = Array.from(bText), b2j = new Map();
  b.forEach((ch, i) => { if (!b2j.has(ch)) b2j.set(ch, []); b2j.get(ch).push(i); });
  if (b.length >= 200) {
    const ntest = Math.floor(b.length / 100) + 1;
    for (const [ch, indexes] of [...b2j.entries()]) if (indexes.length > ntest) b2j.delete(ch);
  }
  const findLongest = (alo, ahi, blo, bhi) => {
    let bestI = alo, bestJ = blo, bestSize = 0, j2len = new Map();
    for (let i = alo; i < ahi; i += 1) {
      const next = new Map();
      for (const j of b2j.get(a[i]) || []) {
        if (j < blo) continue;
        if (j >= bhi) break;
        const size = (j > 0 ? (j2len.get(j - 1) || 0) : 0) + 1;
        next.set(j, size);
        if (size > bestSize) { bestI = i + 1 - size; bestJ = j + 1 - size; bestSize = size; }
      }
      j2len = next;
    }
    while (bestI > alo && bestJ > blo && a[bestI - 1] === b[bestJ - 1]) { bestI -= 1; bestJ -= 1; bestSize += 1; }
    while (bestI + bestSize < ahi && bestJ + bestSize < bhi && a[bestI + bestSize] === b[bestJ + bestSize]) bestSize += 1;
    return {a: bestI, b: bestJ, size: bestSize};
  };
  const queue = [[0, a.length, 0, b.length]], matches = [];
  while (queue.length) {
    const [alo, ahi, blo, bhi] = queue.pop();
    const m = findLongest(alo, ahi, blo, bhi);
    if (!m.size) continue;
    if (alo < m.a && blo < m.b) queue.push([alo, m.a, blo, m.b]);
    if (m.a + m.size < ahi && m.b + m.size < bhi) queue.push([m.a + m.size, ahi, m.b + m.size, bhi]);
    matches.push(m);
  }
  matches.sort((x, y) => x.a - y.a || x.b - y.b || x.size - y.size);
  let totalMatches = 0, aStart = 0, bStart = 0, size = 0;
  for (const m of matches) {
    if (aStart + size === m.a && bStart + size === m.b) size += m.size;
    else { totalMatches += size; aStart = m.a; bStart = m.b; size = m.size; }
  }
  totalMatches += size;
  return a.length + b.length === 0 ? 1 : (2 * totalMatches) / (a.length + b.length);
}

function simulateDemoCorrespondentMatch(candidateRaw, matchingRaw) {
  const matching = validateCorrespondentMatching(matchingRaw);
  const candidate = String(candidateRaw || "").trim().replace(/\s+/g, " ");
  const normalized = normalizeCorrespondentName(candidate);
  const plausible = plausibleCorrespondentCandidate(candidate);
  const exact = plausible ? CORRESPONDENTS.filter(name => normalizeCorrespondentName(name) === normalized) : [];
  const scored = plausible ? CORRESPONDENTS.map(name => [sequenceMatcherRatio(normalized, normalizeCorrespondentName(name)), name]).sort((x, y) => y[0] - x[0] || y[1].localeCompare(x[1])) : [];
  const best = scored[0]?.[0] ?? null, runner = scored[1]?.[0] ?? null, gateRunner = runner ?? 0;
  let resolution;
  if (!plausible) resolution = {extracted:candidate,status:"empty",resolved:"",suggestion:"",match_score:null,runner_up_score:null};
  else if (exact.length === 1) resolution = {extracted:candidate,status:"existing_exact",resolved:exact[0],suggestion:"",match_score:1,runner_up_score:null};
  else if (scored.length && best >= matching.minimum_similarity && best - gateRunner >= matching.minimum_margin) resolution = {extracted:candidate,status:"existing_fuzzy",resolved:scored[0][1],suggestion:"",match_score:Number(best.toFixed(4)),runner_up_score:Number(gateRunner.toFixed(4))};
  else resolution = {extracted:candidate,status:"new_suggestion",resolved:"",suggestion:candidate,match_score:best==null?null:Number(best.toFixed(4)),runner_up_score:runner==null?null:Number(runner.toFixed(4))};
  return {
    candidate,
    normalized_candidate: normalized,
    normalized_length: normalized.length,
    minimum_similarity: matching.minimum_similarity,
    minimum_margin: matching.minimum_margin,
    thresholds_applied: !["existing_exact","empty"].includes(resolution.status),
    similarity_pass: best == null ? null : best >= matching.minimum_similarity,
    margin_pass: best == null ? null : best - gateRunner >= matching.minimum_margin,
    winner_margin: best == null || runner == null ? null : Number((best-runner).toFixed(4)),
    existing_count: CORRESPONDENTS.length,
    candidates: scored.slice(0,3).map(([score,name]) => ({name,score:Number(score.toFixed(4))})),
    resolution
  };
}

function savePromptConfig(raw) {
  const candidate = validatePromptConfig(raw);
  const previous = clone(state.promptConfig);
  state.promptHistory.unshift({
    file: `prompt-config-v${String(previous.version).padStart(4, "0")}-demo-${Date.now()}.json`,
    version: previous.version,
    updated_at: previous.updated_at,
    summary: `${previous.model} · ${previous.tagging_mode === "history_assisted" ? "Hybrid tagging" : "LLM direct"}`,
    config: previous
  });
  candidate.version = Number(previous.version || 0) + 1;
  candidate.updated_at = nowIso();
  state.promptConfig = candidate;
  persist();
  return clone(candidate);
}

function saveAppConfig(raw) {
  const candidate = validateAppConfig(raw);
  const previous = clone(state.appConfig);
  state.appHistory.unshift({
    file: `app-config-v${String(previous.version).padStart(4, "0")}-demo-${Date.now()}.json`,
    version: previous.version,
    updated_at: previous.updated_at,
    summary: `${previous.runtime?.dry_run ? "Metadata dry run" : "Metadata writes enabled"} · ${previous.ocr?.version || "PP-OCRv6"} ${String(previous.ocr?.model_profile || "medium").replace(/^./, c => c.toUpperCase())} · ${previous.ocr?.max_side_pixels || 3000} px`,
    config: previous
  });
  candidate.version = Number(previous.version || 0) + 1;
  candidate.updated_at = nowIso();
  state.appConfig = candidate;
  persist();
  return clone(candidate);
}

function eligibleTagNames() {
  const parents = new Set(TAGS.filter(tag => tag.parent != null).map(tag => tag.parent));
  return TAGS.filter(tag => !parents.has(tag.id)).map(tag => tag.name);
}

function guidanceText(config) {
  const lines = [];
  const guidance = config.tag_guidance || {};
  for (const tag of TAGS) {
    const value = String(guidance[String(tag.id)] || "").trim();
    if (value) lines.push(`- ${tag.name}: ${value}`);
  }
  return lines.length ? lines.join("\n") : "(none)";
}

function examplesText(doc, route) {
  if (route !== "llm_fallback") return "";
  const examples = doc.examples || [];
  if (!examples.length) return "(none)";
  return examples.map(example =>
    `- ID ${example.id} · ${example.title} · tags: ${(example.tags || []).join(" + ") || "(none)"}\n  ${example.excerpt}`
  ).join("\n");
}

function routeFor(config, doc) {
  if (config.tagging_mode === "llm_only") return "llm_only";
  const evidence = doc.history_evidence;
  if (!evidence) return "llm_fallback";
  const settings = state.appConfig.history || {};
  const passes =
    evidence.similarity >= Number(settings.match_similarity ?? 0.62) &&
    evidence.support >= Number(settings.min_support ?? 2) &&
    evidence.winner_share >= Number(settings.min_winner_share ?? 0.50);
  return passes ? "history_match" : "llm_fallback";
}

function templateValues(config, doc, route) {
  const tags = eligibleTagNames();
  return {
    DOCUMENT_TEXT: doc.content,
    DOCUMENT_ID: String(doc.id),
    CURRENT_TITLE: doc.current_title || "",
    CURRENT_CREATED: doc.current_created || "",
    TAGS_JSON: JSON.stringify(tags, null, 2),
    TAGS_LINES: tags.join("\n"),
    MAX_TAGS: String(config.max_tags),
    TAG_GUIDANCE: guidanceText(config),
    TAG_EXAMPLES: examplesText(doc, route),
    DOCUMENT_TYPES_JSON: JSON.stringify(DOCUMENT_TYPES, null, 2),
    DOCUMENT_TYPES_LINES: DOCUMENT_TYPES.join("\n"),
    CORRESPONDENTS_JSON: JSON.stringify(CORRESPONDENTS, null, 2),
    CORRESPONDENTS_LINES: CORRESPONDENTS.join("\n")
  };
}

function renderTemplate(text, values) {
  return String(text || "").replace(/{{\s*([A-Z0-9_]+)\s*}}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : match
  );
}

function outputSchema(config, route) {
  const properties = {
    title: {type: "string"},
    document_type: {type: "string", enum: ["", ...DOCUMENT_TYPES]},
    correspondent: {type: "string"},
    created: {type: "string", pattern: "^$|^\\d{4}-\\d{2}-\\d{2}$"}
  };
  const required = ["title", "document_type", "correspondent", "created"];
  if (route !== "history_match") {
    properties.tags = {
      type: "array",
      items: {type: "string", enum: eligibleTagNames()},
      maxItems: Number(config.max_tags),
      uniqueItems: true
    };
    required.push("tags");
  }
  return {type: "object", properties, required, additionalProperties: false};
}

function previewPayload(config, doc, includeModelResult) {
  validatePromptConfig(config);
  const route = routeFor(config, doc);
  const values = templateValues(config, doc, route);
  const systemPrompt = renderTemplate(config.system_prompt, values);
  const basePrompt = renderTemplate(config.classification_template, values);
  const taggingPrompt = route === "history_match" ? "" : renderTemplate(config.tagging_prompt, values);
  const userPrompt = taggingPrompt ? `${basePrompt}\n\n${taggingPrompt}` : basePrompt;
  const schema = outputSchema(config, route);

  const evidence = doc.history_evidence;
  const tagging = {
    strategy: config.tagging_mode,
    route,
    history_match: route === "history_match" && evidence ? {
      tags: evidence.tags,
      similarity: evidence.similarity,
      support: evidence.support,
      winner_share: evidence.winner_share
    } : null,
    reviewed_examples: route === "llm_fallback" ? clone(doc.examples || []) : []
  };

  const payload = {
    rendered: {system_prompt: systemPrompt, user_prompt: userPrompt, schema},
    taxonomy: {tags: clone(TAGS), document_types: clone(DOCUMENT_TYPES), correspondents: clone(CORRESPONDENTS)},
    tagging,
    meta: {
      demo: true,
      document_id: doc.id,
      current_title: doc.current_title,
      current_created: doc.current_created,
      document_characters: doc.content.length,
      model: config.model,
      note: "Synthetic browser-only demo fixture; Paperless and Ollama were not contacted."
    }
  };

  if (includeModelResult) {
    const suggestion = clone(doc.result);
    if (route === "history_match" && evidence) suggestion.tags = clone(evidence.tags);
    const corrStatus = !suggestion.correspondent
      ? "empty"
      : CORRESPONDENTS.includes(suggestion.correspondent)
        ? "existing_exact"
        : "new_suggestion";
    payload.suggestion = suggestion;
    payload.validation_errors = [];
    payload.correspondent_resolution = {
      status: corrStatus,
      suggestion: suggestion.correspondent,
      matched_name: corrStatus === "existing_exact" ? suggestion.correspondent : null
    };
    const approxPromptTokens = Math.max(1, Math.round((systemPrompt.length + userPrompt.length) / 4));
    payload.performance = {
      model: config.model,
      inference_seconds: doc.id === 4711 ? 7.4 : doc.id === 4712 ? 8.8 : 6.9,
      prompt_eval_count: approxPromptTokens,
      eval_count: 78,
      eval_tokens_per_second: 10.5,
      simulated: true
    };
  }
  return payload;
}

function taggingState() {
  const history = clone(HISTORY_HEALTH);
  history.last_updated = state.historyLastUpdated || history.last_updated;
  return {tags: clone(TAGS), tag_guidance: clone(state.promptConfig.tag_guidance || {}), history};
}

function ocrRecovery() {
  return {
    state: {status: "idle", attempt: 0, max_attempts: 4, request_id: "", retry_now_requested: false, last_error: ""},
    failures: []
  };
}

async function api(path, opts = {}) {
  const method = String(opts.method || "GET").toUpperCase();
  const body = bodyJson(opts);

  if (path === "/api/state" && method === "GET") {
    return {
      config: clone(state.promptConfig),
      presets: clone(PROMPT_PRESETS),
      placeholders: clone(PLACEHOLDERS),
      config_sha256: "demo",
      prompt_hashes: {config_sha256: "demo"}
    };
  }
  if (path === "/api/history" && method === "GET") return {items: publicHistory(state.promptHistory)};
  if (path === "/api/config/validate" && method === "POST") {
    validatePromptConfig(body.config);
    return {ok: true, config_sha256: "demo-valid"};
  }
  if (path === "/api/config/save" && method === "POST") {
    const config = savePromptConfig(body.config);
    return {ok: true, config, history: publicHistory(state.promptHistory)};
  }
  if (path === "/api/history/restore" && method === "POST") {
    const item = state.promptHistory.find(entry => entry.file === body.file);
    if (!item || !item.config) throw new Error("Demo history version not found");
    const config = savePromptConfig(item.config);
    return {ok: true, config, history: publicHistory(state.promptHistory)};
  }

  if (path === "/api/tagging/state" && method === "GET") return taggingState();
  if (path === "/api/tagging/refresh" && method === "POST") {
    await sleep(300);
    state.historyLastUpdated = nowIso();
    persist();
    return taggingState();
  }

  if ((path === "/api/preview" || path === "/api/test") && method === "POST") {
    const id = Number(body.document_id);
    const doc = DOCUMENTS[id];
    if (!doc) throw new Error("Demo document not found. Try 4711, 4712 or 4713.");
    const config = validatePromptConfig(body.config);
    await sleep(path === "/api/test" ? 650 : 120);
    return previewPayload(config, doc, path === "/api/test");
  }

  if (path === "/api/app/state" && method === "GET") {
    return {
      config: clone(state.appConfig),
      config_sha256: "demo",
      history: publicHistory(state.appHistory),
      token_configured: true,
      paperless_ui_integration_ready: true
    };
  }
  if (path === "/api/app/history" && method === "GET") return {items: publicHistory(state.appHistory)};
  if (path === "/api/app/validate" && method === "POST") {
    validateAppConfig(body.config);
    return {ok: true, config_sha256: "demo-valid"};
  }
  if (path === "/api/app/save" && method === "POST") {
    const config = saveAppConfig(body.config);
    return {ok: true, config, history: publicHistory(state.appHistory), token_configured: true, paperless_ui_integration_ready: true};
  }
  if (path === "/api/app/history/restore" && method === "POST") {
    const item = state.appHistory.find(entry => entry.file === body.file);
    if (!item || !item.config) throw new Error("Demo app-history version not found");
    const config = saveAppConfig(item.config);
    return {ok: true, config, history: publicHistory(state.appHistory), token_configured: true, paperless_ui_integration_ready: true};
  }
  if (path === "/api/app/correspondent-matching/test" && method === "POST") {
    await sleep(120);
    return {simulation: simulateDemoCorrespondentMatch(body.candidate, body.matching)};
  }
  if (path === "/api/app/connections/test" && method === "POST") {
    validateAppConfig(body.config);
    await sleep(350);
    return {
      paperless: {ok: true, detail: "Synthetic Paperless connection"},
      ollama: {ok: true, detail: "Synthetic Ollama connection"}
    };
  }
  if (path === "/api/app/paperless-ui/status" && method === "GET") {
    return {ok: true, reachable: true, package_ready: true, detail: "Synthetic Paperless UI integration verified"};
  }
  if (path === "/api/app/paperless-ui" && method === "POST") {
    const updated = clone(state.appConfig);
    updated.paperless_ui = updated.paperless_ui || {};
    updated.paperless_ui.enabled = Boolean(body.enabled);
    updated.paperless_ui.control_center_url = body.enabled ? "https://example.invalid/control-center" : "";
    const config = saveAppConfig(updated);
    return {ok: true, config, history: publicHistory(state.appHistory), token_configured: true, paperless_ui_integration_ready: true};
  }
  if (path === "/api/app/ocr/health" && method === "GET") {
    return {
      ok: true,
      health: {
        ok: true,
        version: state.appConfig.ocr?.version || "PP-OCRv6",
        model_profile: state.appConfig.ocr?.model_profile || "medium",
        device: state.appConfig.ocr?.device || "cpu",
        simulated: true
      },
      recovery: ocrRecovery()
    };
  }
  if (path === "/api/app/ocr/recovery" && method === "GET") return ocrRecovery();
  if (path === "/api/app/ocr/failures/dismiss" && method === "POST") return {ok: true, removed: false};
  if (path === "/api/app/ocr/retry-now" && method === "POST") return {ok: true, trigger: {request_id: body.request_id || "", simulated: true}};
  if (path === "/api/health" && method === "GET") return {ok: true, demo: true};

  throw new Error(`Demo endpoint is not implemented: ${method} ${path}`);
}

window.PLAI_DEMO = {api, reset};

document.addEventListener("DOMContentLoaded", () => {
  const docId = document.getElementById("docId");
  if (docId && !docId.value) docId.value = "4711";

  document.getElementById("demo-reset")?.addEventListener("click", reset);

  document.querySelectorAll("[data-demo-document]").forEach(button => {
    button.addEventListener("click", () => {
      if (docId) docId.value = button.dataset.demoDocument;
      document.querySelector('[data-page="classification"]')?.click();
      document.querySelector('[data-tab="class-test"]')?.click();
      docId?.focus();
    });
  });
});
})();
