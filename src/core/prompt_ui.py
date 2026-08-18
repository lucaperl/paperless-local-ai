import json
import os
import traceback

import requests
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from app_config import (
    config_hash as app_config_hash,
    ensure_config as ensure_app_config,
    list_history as list_app_history,
    restore_history as restore_app_history,
    save_config as save_app_config,
    validate_config as validate_app_config,
)

from prompt_runtime import (
    PLACEHOLDERS,
    PaperlessClient,
    ai_resource_lock,
    call_ollama,
    ensure_config,
    list_history,
    load_config,
    make_schema,
    performance_from_raw,
    prompt_hashes,
    render_prompts,
    restore_history,
    save_config,
    validate_config,
    validate_result,
)
from correspondent_runtime import (
    PLACEHOLDERS as CORRESPONDENT_PLACEHOLDERS,
    call_ollama as call_correspondent_ollama,
    ensure_config as ensure_correspondent_config,
    list_history as list_correspondent_history,
    performance_from_raw as correspondent_performance_from_raw,
    prompt_hashes as correspondent_prompt_hashes,
    render_prompts as render_correspondent_prompts,
    restore_history as restore_correspondent_history,
    save_config as save_correspondent_config,
    validate_config as validate_correspondent_config,
    validate_result as validate_correspondent_result,
)

HOST = os.getenv("PROMPT_UI_HOST", "0.0.0.0")
PORT = int(os.getenv("PROMPT_UI_PORT", "8080"))
client = PaperlessClient()
PAPERLESS_TOKEN = os.environ.get("PAPERLESS_TOKEN", "")


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>paperless-local-ai Control Center</title>
<style>
:root{color-scheme:dark;--bg:#0f1115;--panel:#171a21;--panel2:#13171e;--line:#2a2f3a;--text:#e8eaf0;--muted:#9ca3af;--accent:#79a7ff;--accent-bg:#1c2940;--ok:#76d49b;--bad:#ff8b8b;--warn:#e8c273}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:16px;background:#101319}h1{font-size:20px;margin:0}h2{font-size:17px;margin:0 0 8px}h3{font-size:15px;margin:0 0 10px}main{padding:20px;max-width:1500px;margin:auto}
.mode-switch{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:20px}.mode-switch button{text-align:left;background:var(--panel2);border:1px solid var(--line);padding:15px 17px;border-radius:10px}.mode-switch button.active{background:var(--accent-bg);border-color:#466697}.mode-title{display:block;font-size:16px;font-weight:650;margin-bottom:3px}.mode-desc{display:block;color:var(--muted);font-size:12px;font-weight:400}
.mode{display:none}.mode.active{display:block}.mode-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px}.mode-head p{margin:4px 0 0;color:var(--muted);max-width:980px}.config-badge{white-space:nowrap;padding:7px 10px;border-radius:7px;background:#202530;border:1px solid var(--line);color:var(--accent);font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
.actionbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:12px}.actionbar .status{margin-left:auto;min-width:260px}
.subtabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px;padding-bottom:10px;border-bottom:1px solid var(--line)}.subtabs button{background:transparent;border:1px solid transparent}.subtabs button:hover{background:#1b2028}.subtabs button.active{background:#273044;border-color:#38465f}.subtab-page{display:none}.subtab-page.active{display:block}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px}.full{grid-column:1/-1}
textarea,input,select{width:100%;background:#0d1015;border:1px solid var(--line);color:var(--text);border-radius:7px;padding:9px;font:13px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}textarea{min-height:280px;resize:vertical}.smallarea{min-height:150px}
button{border:0;border-radius:7px;background:#2c3340;color:var(--text);padding:9px 14px;cursor:pointer}button.primary{background:#315ea8}button.danger{background:#7a3434}button:disabled{opacity:.45;cursor:not-allowed}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.row>*{flex:1}.row button,.row label{flex:0 0 auto}.muted{color:var(--muted)}.help{color:var(--muted);margin:6px 0 0;max-width:1100px}.intro{background:#141923;border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px;padding:11px 13px;margin:0 0 16px}.intro strong{color:var(--text)}.field-help{color:var(--muted);font-size:12px;line-height:1.4;margin-top:5px}
.placeholder-grid{display:grid;grid-template-columns:repeat(2,minmax(280px,1fr));gap:8px;margin-top:10px}.placeholder-item{background:#11151c;border:1px solid var(--line);border-radius:7px;padding:9px}.placeholder-item code{display:block;color:var(--accent);font-size:12px;margin-bottom:4px}.placeholder-item span{color:var(--muted);font-size:12px}
.status{padding:8px 12px;border-radius:7px;background:#202530;white-space:pre-wrap}.status.ok{color:var(--ok)}.status.bad{color:var(--bad)}pre{background:#0d1015;border:1px solid var(--line);border-radius:7px;padding:12px;overflow:auto;max-height:620px;white-space:pre-wrap}.settings{display:grid;grid-template-columns:repeat(3,minmax(180px,1fr));gap:12px}.field label{display:block;color:var(--muted);margin-bottom:5px}.history-item{display:grid;grid-template-columns:80px 1fr 1fr auto;gap:10px;align-items:center;padding:9px;border-bottom:1px solid var(--line)}.badge{font-family:ui-monospace,monospace;color:var(--accent)}
@media(max-width:900px){header{align-items:flex-start;flex-direction:column}.mode-switch{grid-template-columns:1fr}.mode-head{flex-direction:column}.grid{grid-template-columns:1fr}.full{grid-column:auto}.settings{grid-template-columns:1fr}.history-item{grid-template-columns:1fr}.placeholder-grid{grid-template-columns:1fr}.actionbar .status{margin-left:0;width:100%}}
</style>
</head>
<body>
<header>
<div><h1>paperless-local-ai Control Center</h1><div class="muted">Configure the app, validate connections, preview exact prompts and run real model tests before enabling production metadata writes. Deployment-only values and the Paperless API token remain in <code>.env</code>.</div></div>
<div id="topStatus" class="status">Loading…</div>
</header>
<main>
<nav class="mode-switch" aria-label="Application sections">
<button type="button" data-mode="classification" class="active"><span class="mode-title">1 · Classification</span><span class="mode-desc">Runs first and writes title, type, existing correspondent, tags and date to Paperless</span></button>
<button type="button" data-mode="correspondent"><span class="mode-title">2 · Correspondent fallback</span><span class="mode-desc">Runs only when classification finds no correspondent; existing names are applied and new names are sent to review</span></button>
<button type="button" data-mode="app"><span class="mode-title">App settings</span><span class="mode-desc">Manage Paperless/Ollama, workflow tags, OCR and runtime behavior</span></button>
</nav>

<section id="mode-app" class="mode">
<div class="mode-head"><div><h2>App settings</h2><p>General runtime settings are versioned and hot-reloaded by the workers. Only deployment values such as ports, volumes, CPU/RAM limits and the Paperless API token remain in <code>.env</code> because Docker or the secret is needed before the app starts.</p></div><div id="appConfigStatus" class="config-badge">Loading…</div></div>
<div class="actionbar"><button id="appValidateBtn">Validate configuration</button><button id="appSaveBtn" class="primary">Save changes</button><span id="appSaveStatus" class="status">Nothing validated or saved yet.</span></div>
<div class="intro"><strong>Test before production.</strong> Test Paperless/Ollama connections with the current unsaved draft, preview the exact prompts and run live model tests for both LLM stages without changing the document. Use Dry Run to validate automatic metadata processing before enabling metadata writes. The Paperless API token is never shown in the browser or stored in JSON.</div>
<nav class="subtabs" data-mode-tabs="app">
<button type="button" data-subtab="app-connections" class="active">Connections</button><button type="button" data-subtab="app-workflow">Pipeline &amp; Tags</button><button type="button" data-subtab="app-ocr">OCR</button><button type="button" data-subtab="app-runtime">Runtime</button><button type="button" data-subtab="app-history">History</button>
</nav>
<section id="app-connections" class="subtab-page active" data-page-mode="app">
<div class="intro"><strong>Connections</strong> These URLs are shared by all components. The Paperless API token comes from the deployment environment and is only shown here as configured or missing.</div>
<div class="grid"><div class="panel"><h3>Paperless-ngx</h3><div class="field"><label>Paperless URL</label><input id="appPaperlessUrl" type="text"><div class="field-help">Base URL of the Paperless instance, for example <code>http://paperless:8000</code> or a reachable LAN address. No trailing slash is required.</div></div><div class="field" style="margin-top:12px"><label>API token</label><div id="appTokenStatus" class="status">Loading…</div><div class="field-help">The token is a secret and therefore remains in <code>.env</code> or a Docker secret. It is never returned by this web UI.</div></div></div><div class="panel"><h3>Ollama</h3><div class="field"><label>Ollama URL</label><input id="appOllamaUrl" type="text"><div class="field-help">Base URL of an existing Ollama instance. paperless-local-ai does not install or start Ollama.</div></div></div><div class="panel full"><div class="row"><button id="appConnectionTestBtn">Test connections with current draft</button><span id="appConnectionStatus" class="status">Not tested yet.</span></div><p class="help">Tests the currently visible draft without saving it: Paperless including the token, plus Ollama's <code>/api/tags</code>.</p></div></div>
</section>
<section id="app-workflow" class="subtab-page" data-page-mode="app">
<div class="intro"><strong>Pipeline &amp; tags</strong> These five tags control the transition between OCR, LLM processing and human review. If you change a name, the corresponding tag must already exist in Paperless. OCR queue/error tags automatically block the LLM stage, so no duplicate setting is needed.</div>
<div class="settings"><div class="field"><label>OCR queue tag</label><input id="appOcrQueueTag"><div class="field-help">Documents with this tag are processed by the PaddleOCR worker.</div></div><div class="field"><label>OCR error tag</label><input id="appOcrErrorTag"><div class="field-help">Set when OCR processing fails.</div></div><div class="field"><label>LLM queue tag</label><input id="appLlmQueueTag"><div class="field-help">Set after successful OCR; the metadata worker processes documents with this tag.</div></div><div class="field"><label>LLM error tag</label><input id="appLlmErrorTag"><div class="field-help">Set when LLM classification fails.</div></div><div class="field"><label>Review tag</label><input id="appReviewTag"><div class="field-help">Documents remain under this tag for human review. Persistent correspondent suggestions are removed once the document leaves review.</div></div><div class="field"><label>Additional taxonomy-excluded tags</label><input id="appExtraExcludedTags"><div class="field-help">Comma-separated additional tags that are never offered to the LLM as classification tags, for example <code>TODO</code>. The five technical tags above are excluded automatically.</div></div></div>
</section>
<section id="app-ocr" class="subtab-page" data-page-mode="app">
<div class="intro"><strong>OCR</strong> These values control selective PaddleOCR processing. They are reloaded before every poll, so no container restart is required. The original PDF is never modified.</div>
<div class="settings"><div class="field"><label>OCR language</label><input id="appOcrLanguage"><div class="field-help">PaddleOCR language code, for example <code>de</code>. The language determines the recognition models used.</div></div><div class="field"><label>OCR version</label><input id="appOcrVersion"><div class="field-help">PaddleOCR model generation. Tested default: <code>PP-OCRv6</code>.</div></div><div class="field"><label>Device</label><input id="appOcrDevice"><div class="field-help">PaddleOCR device. The tested low-power setup uses <code>cpu</code>.</div></div></div>
</section>
<section id="app-runtime" class="subtab-page" data-page-mode="app">
<div class="intro"><strong>Runtime</strong> Configure worker intervals and safe operating mode. Docker resource limits remain deployment settings because the container runtime applies them before the app starts.</div>
<div class="settings"><div class="field"><label>Polling interval in seconds</label><input id="appPollInterval" type="number"><div class="field-help">How often the OCR and metadata workers look for queued documents. Minimum: 5 seconds.</div></div><div class="field"><label>Review cleanup interval in seconds</label><input id="appReviewPruneInterval" type="number"><div class="field-help">How often stale review records are removed when their document no longer carries the review tag. Default: 3600 = once per hour.</div></div><div class="field"><label>Dry Run</label><select id="appDryRun"><option value="false">Off — write metadata to Paperless</option><option value="true">On — run without metadata writes</option></select><div class="field-help">In Dry Run, classification is executed and logged, but document metadata and persistent review suggestions are not written. Technical queue/error tags may still change.</div></div></div>
</section>
<section id="app-history" class="subtab-page" data-page-mode="app">
<div class="intro"><strong>Versioned app settings</strong> Every save keeps the previous state in history. Restoring creates a new current version; existing history is preserved.</div><div class="panel"><div class="row"><h3>Saved versions</h3><button id="appHistoryRefresh">Reload history</button></div><div id="appHistoryList"></div></div>
</section>
</section>

<section id="mode-classification" class="mode active">
<div class="mode-head"><div><h2>Document classification</h2><p>Stage 1 runs for every document picked up by automatic LLM processing. The model determines title, document type, an existing Paperless correspondent, classification tags and document date in one structured request. Valid results are written directly to Paperless. If the correspondent remains empty, stage 2 can run afterwards.</p></div><div id="classConfigStatus" class="config-badge">Loading…</div></div>
<div class="actionbar"><button id="validateBtn">Validate configuration</button><button id="saveBtn" class="primary">Save changes</button><span id="saveStatus" class="status">Nothing validated or saved yet.</span></div><div class="intro"><strong>Validate or save?</strong> <strong>Validate configuration</strong> checks required fields, placeholders and values without saving. <strong>Save changes</strong> creates a new version that is used from the next production classification job. No restart is required.</div>
<nav class="subtabs" data-mode-tabs="classification">
<button type="button" data-subtab="prompt" class="active">Prompt</button><button type="button" data-subtab="preview">Test</button><button type="button" data-subtab="schema">Output &amp; allowed values</button><button type="button" data-subtab="settings">Settings</button><button type="button" data-subtab="history">History</button>
</nav>

<section id="prompt" class="subtab-page active" data-page-mode="classification">
<div class="intro"><strong>What is edited here?</strong> The system prompt contains the general rules for stage 1. The classification prompt contains the task for one document. Placeholders such as <code>{{DOCUMENT_TEXT}}</code> are replaced with data from the selected Paperless document immediately before the model call.</div>
<div class="grid">
<div class="panel"><h3>System prompt</h3><p class="help">Applied to every classification run and defines role, safety rules and general output requirements. Document-specific content belongs in the classification prompt; <code>{{DOCUMENT_TEXT}}</code> must remain there.</p><textarea id="systemPrompt"></textarea></div>
<div class="panel"><h3>Classification prompt</h3><p class="help">Task for one document. It defines how title, document type, existing correspondent, tags and date are determined. The rendered prompt is sent to Ollama as the user message.</p><textarea id="classificationTemplate"></textarea></div>
<div class="panel full"><h3>Available placeholders</h3><p class="help">At runtime, the Control Center replaces each placeholder with the current value from the test or production document. <code>_JSON</code> variants provide a correctly formatted JSON list; <code>_LINES</code> provides the same values one per line. <code>{{DOCUMENT_TEXT}}</code> is required and must not be removed.</p><div id="placeholders" class="placeholder-grid"></div></div>
</div>
</section>

<section id="preview" class="subtab-page" data-page-mode="classification">
<div class="intro"><strong>Safe test before production.</strong> Select an existing Paperless document by ID. <strong>Preview final prompt</strong> loads the document and taxonomy and shows exactly what would be sent to the model without calling it. <strong>Run model test</strong> additionally performs a real Ollama request. Both use the currently visible, even unsaved draft and never modify the Paperless document.</div>
<div class="grid">
<div class="panel full"><div class="row"><div><label>Paperless document ID</label><input id="docId" type="number" min="1" value="93"><div class="field-help">Numeric document ID from Paperless, for example from the document URL or API.</div></div><button id="previewBtn">Preview final prompt</button><button id="testBtn" class="primary">Run model test</button></div><p class="help">A live model test uses the same shared AI lock as OCR and production LLM jobs. These expensive tasks therefore do not run at the same time; if the AI slot is busy, the test waits.</p><div id="testStatus" class="status">Ready for prompt preview or model test.</div></div>
<div class="panel"><h3>System message sent to the model</h3><p class="help">Exact rendered system prompt for this test.</p><pre id="systemPreview"></pre></div>
<div class="panel"><h3>User message sent to the model</h3><p class="help">Exact rendered classification prompt including substituted placeholders.</p><pre id="userPreview"></pre></div>
<div class="panel"><h3>Model response and validation</h3><p class="help">Filled only by <strong>Run model test</strong>. Shows the structured suggestion, validation errors and performance data.</p><pre id="testResult"></pre></div>
<div class="panel"><h3>Test request details</h3><p class="help">Technical details about the rendered request, such as configuration version and amount of document text used.</p><pre id="previewMeta"></pre></div>
</div>
</section>

<section id="schema" class="subtab-page" data-page-mode="classification">
<div class="intro"><strong>What is shown here?</strong> The output schema is the fixed JSON contract the model response must satisfy. Allowed Paperless values show the taxonomy loaded by the most recent preview or model test. Stage 1 can use only current list values for document type, correspondent and tags.</div>
<div class="grid"><div class="panel"><h3>Expected JSON output</h3><p class="help">Defines fields, data types and allowed values for the model response. It is generated automatically from the current configuration.</p><pre id="schemaPreview"></pre></div><div class="panel"><h3>Currently allowed Paperless values</h3><p class="help">Document types, correspondents and classification tags loaded from Paperless during the latest preview or model test. Technical process tags such as <code>Inbox</code> or <code>LLM</code> are excluded.</p><pre id="taxonomyPreview"></pre></div></div>
</section>

<section id="settings" class="subtab-page" data-page-mode="classification">
<div class="intro"><strong>These settings apply only to Stage 1.</strong> Changes affect production only after <strong>Save changes</strong>. They do not modify Ollama itself or the installed model.</div>
<div class="panel"><div class="settings">
<div class="field"><label>Ollama model <span class="muted">(model)</span></label><input id="model"><div class="field-help">Exact name of a model already installed in Ollama, for example <code>qwen3.5:4b</code>. The Control Center does not download or install models.</div></div>
<div class="field"><label>Context window in tokens <span class="muted">(num_ctx)</span></label><input id="numCtx" type="number"><div class="field-help">Maximum context Ollama provides for prompt and response. A larger value allows more text but uses more memory and may be slower.</div></div>
<div class="field"><label>Maximum response length in tokens <span class="muted">(num_predict)</span></label><input id="numPredict" type="number"><div class="field-help">Upper limit for the generated JSON response. Too small a value can truncate the response; it does not control the amount of document text read.</div></div>
<div class="field"><label>Output randomness <span class="muted">(temperature)</span></label><input id="temperature" type="number" min="0" max="2" step="0.05"><div class="field-help"><code>0</code> provides the most reproducible results and is recommended for metadata. Higher values make responses more variable.</div></div>
<div class="field"><label>Additional model reasoning <span class="muted">(think)</span></label><select id="think"><option value="false">Off</option><option value="true">On</option></select><div class="field-help"><strong>Off</strong> is intended for this short structured classification. <strong>On</strong> enables the model's thinking mode and uses additional time/tokens.</div></div>
<div class="field"><label>Keep model loaded after the job <span class="muted">(keep_alive)</span></label><input id="keepAlive"><div class="field-help">Passed directly to Ollama. <code>0</code> unloads the model after the request; for example <code>5m</code> keeps it loaded for five minutes. Longer keep-alive uses RAM for longer.</div></div>
<div class="field"><label>Maximum document text in characters <span class="muted">(content_char_limit)</span></label><input id="contentLimit" type="number"><div class="field-help">Maximum number of characters from Paperless <code>content</code> included in the prompt. Shorter documents are used in full; longer documents are truncated according to the setting below.</div></div>
<div class="field"><label>Share kept from document start when truncated <span class="muted">(content_head_ratio)</span></label><input id="headRatio" type="number" min="0.5" max="0.95" step="0.05"><div class="field-help">Applies only when the document exceeds the character limit. <code>0.75</code> means 75% of the retained text comes from the start and 25% from the end.</div></div>
<div class="field"><label>Maximum classification tags <span class="muted">(max_tags)</span></label><input id="maxTags" type="number" min="1" max="10"><div class="field-help">Limits how many classification tags the model response may contain. The value is applied directly to the output schema and validation; process tags do not count.</div></div>
<div class="field"><label>Ollama timeout in seconds <span class="muted">(timeout)</span></label><input id="ollamaTimeout" type="number"><div class="field-help">Maximum time the worker waits for the model request. If exceeded, the request fails and follows normal error handling.</div></div>
</div></div>
</section>

<section id="history" class="subtab-page" data-page-mode="classification">
<div class="intro"><strong>What is versioned?</strong> Every save stores prompt and settings together as a new classification version. Restoring does not overwrite history: the selected older state becomes a new active version.</div>
<div class="panel"><div class="row"><h3>Saved versions</h3><button id="historyRefresh">Reload history</button></div><p class="help"><strong>Restore this version</strong> saves the selected state again as the current configuration. The currently active state remains in history as its own version.</p><div id="historyList"></div></div>
</section>
</section>

<section id="mode-correspondent" class="mode">
<div class="mode-head"><div><h2>Correspondent fallback</h2><p>Stage 2 is optional and runs only when stage 1 found no correspondent and <strong>Enable in production</strong> is on. It identifies only the sender or issuer. An unambiguous existing Paperless correspondent is applied automatically. A genuinely new name is never created automatically; it appears as a native Paperless suggestion for confirmation. If no reliable name is found, nothing changes.</p></div><div id="corrConfigStatus" class="config-badge">Loading…</div></div>
<div class="actionbar"><button id="corrValidateBtn">Validate configuration</button><button id="corrSaveBtn" class="primary">Save changes</button><span id="corrSaveStatus" class="status">Nothing validated or saved yet.</span></div><div class="intro"><strong>Validate or save?</strong> <strong>Validate configuration</strong> checks required fields, placeholders and values without saving. <strong>Save changes</strong> creates a new version. The <strong>Enable in production</strong> switch under Settings controls whether Stage 2 runs automatically.</div>
<nav class="subtabs" data-mode-tabs="correspondent">
<button type="button" data-subtab="corr-prompt" class="active">Prompt</button><button type="button" data-subtab="corr-test">Test</button><button type="button" data-subtab="corr-settings">Settings</button><button type="button" data-subtab="corr-history">History</button>
</nav>

<section id="corr-prompt" class="subtab-page active" data-page-mode="correspondent">
<div class="intro"><strong>What is edited here?</strong> These prompts belong only to stage 2. They do not affect the title, document type, tags or date from stage 1. Unlike stage 1, this pass may suggest a new correspondent name, but it does not create one.</div>
<div class="grid">
<div class="panel"><h3>System prompt</h3><p class="help">General role and safety rules for sender identification. The document text belongs in the correspondent prompt.</p><textarea id="corrSystemPrompt"></textarea></div>
<div class="panel"><h3>Correspondent prompt</h3><p class="help">Task for one document. The model response contains only <code>correspondent</code>: either a suitable existing/new sender name or an empty string when the sender cannot be determined reliably.</p><textarea id="corrPromptTemplate"></textarea></div>
<div class="panel full"><h3>Available placeholders</h3><p class="help"><code>{{DOCUMENT_TEXT}}</code> is required. <code>{{CORRESPONDENTS_JSON}}</code> and <code>{{CORRESPONDENTS_LINES}}</code> provide existing Paperless correspondents as reference. This list is not a hard restriction in stage 2: if the actual sender does not yet exist, the model may suggest a new name.</p><div id="corrPlaceholders" class="placeholder-grid"></div></div>
</div>
</section>

<section id="corr-test" class="subtab-page" data-page-mode="correspondent">
<div class="intro"><strong>What happens during testing?</strong> <strong>Preview final prompt</strong> shows the exact Stage 2 input for a real Paperless document without calling the model. <strong>Run model test</strong> performs a real Ollama request. Neither Paperless metadata nor persistent review suggestions are written. Testing works even when <strong>Enable in production</strong> is off.</div>
<div class="grid">
<div class="panel full"><div class="row"><div><label>Paperless document ID</label><input id="corrDocId" type="number" min="1" value="93"><div class="field-help">Numeric document ID from Paperless, for example from the document URL or API.</div></div><button id="corrPreviewBtn">Preview final prompt</button><button id="corrTestBtn" class="primary">Run model test</button></div><p class="help">Preview and model test use the currently visible, even unsaved draft. A live model test uses the shared AI lock so OCR and LLM jobs do not consume the available resources at the same time.</p><div id="corrTestStatus" class="status">Ready for prompt preview or model test.</div></div>
<div class="panel"><h3>System message sent to the model</h3><p class="help">Exact rendered system prompt for this test.</p><pre id="corrSystemPreview"></pre></div>
<div class="panel"><h3>User message sent to the model</h3><p class="help">Exact rendered correspondent prompt including substituted placeholders.</p><pre id="corrUserPreview"></pre></div>
<div class="panel"><h3>Expected JSON output</h3><p class="help">Stage 2 may return only the <code>correspondent</code> field.</p><pre id="corrSchemaPreview"></pre></div>
<div class="panel"><h3>Model response and validation</h3><p class="help">Filled only by <strong>Run model test</strong>. Shows the candidate, validation errors and performance data.</p><pre id="corrTestResult"></pre></div>
<div class="panel full"><h3>Test request details</h3><p class="help">Technical details about the rendered request, such as configuration version and amount of document text used.</p><pre id="corrPreviewMeta"></pre></div>
</div>
</section>

<section id="corr-settings" class="subtab-page" data-page-mode="correspondent">
<div class="intro"><strong>These settings apply only to stage 2.</strong> Configure whether the fallback runs automatically in production and which model/text parameters it uses. Tests in the Test tab are always available, regardless of the production switch.</div>
<div class="grid">
<div class="panel full"><h3>Production use</h3><div class="settings"><div class="field"><label>Enable in production <span class="muted">(enabled)</span></label><select id="corrEnabled"><option value="false">Off — manual testing only</option><option value="true">On — run when correspondent is empty</option></select><div class="field-help">When <strong>On</strong>, stage 2 starts automatically only when stage 1 returned no correspondent. An exact existing Paperless name is applied directly; a new name is stored only as a suggestion for confirmation. Empty or uncertain results change nothing. This switch does not affect manual tests.</div></div></div></div>
<div class="panel full"><h3>Model and request parameters</h3><div class="settings">
<div class="field"><label>Ollama model <span class="muted">(model)</span></label><input id="corrModel"><div class="field-help">Exact name of a model already installed in Ollama. The Control Center does not download or install models.</div></div>
<div class="field"><label>Context window in tokens <span class="muted">(num_ctx)</span></label><input id="corrNumCtx" type="number"><div class="field-help">Maximum context for the prompt and response of this second model call. Larger values use more memory and may be slower.</div></div>
<div class="field"><label>Maximum response length in tokens <span class="muted">(num_predict)</span></label><input id="corrNumPredict" type="number"><div class="field-help">Upper limit for the short JSON response. Because only a name or empty string is expected, this can usually be much smaller than in stage 1.</div></div>
<div class="field"><label>Output randomness <span class="muted">(temperature)</span></label><input id="corrTemperature" type="number" min="0" max="2" step="0.05"><div class="field-help"><code>0</code> is recommended for reproducible sender names. Higher values make suggestions more variable and increase unnecessary name variations.</div></div>
<div class="field"><label>Additional model reasoning <span class="muted">(think)</span></label><select id="corrThink"><option value="false">Off</option><option value="true">On</option></select><div class="field-help"><strong>Off</strong> is intended for short sender identification. <strong>On</strong> enables the model's thinking mode and uses additional time/tokens.</div></div>
<div class="field"><label>Keep model loaded after the job <span class="muted">(keep_alive)</span></label><input id="corrKeepAlive"><div class="field-help">Passed directly to Ollama. <code>0</code> unloads the model after the request; for example <code>5m</code> keeps it loaded for five minutes.</div></div>
<div class="field"><label>Maximum document text in characters <span class="muted">(content_char_limit)</span></label><input id="corrContentLimit" type="number"><div class="field-help">Maximum number of characters from Paperless <code>content</code> included in the correspondent prompt. Shorter documents are used in full.</div></div>
<div class="field"><label>Share kept from document start when truncated <span class="muted">(content_head_ratio)</span></label><input id="corrHeadRatio" type="number" min="0.5" max="0.95" step="0.05"><div class="field-help">Applies only to truncated documents. <code>0.75</code> means 75% of the retained text comes from the start and 25% from the end.</div></div>
<div class="field"><label>Ollama timeout in seconds <span class="muted">(timeout)</span></label><input id="corrTimeout" type="number"><div class="field-help">Maximum time the worker waits for the second model call. If exceeded, the call fails.</div></div>
</div></div>
</div>
</section>

<section id="corr-history" class="subtab-page" data-page-mode="correspondent">
<div class="intro"><strong>What is versioned?</strong> Prompt, production switch and stage-2 settings are versioned together, completely separate from stage 1. Restoring saves the selected older state as a new current version; existing history is preserved.</div>
<div class="panel"><div class="row"><h3>Saved versions</h3><button id="corrHistoryRefresh">Reload history</button></div><p class="help"><strong>Restore this version</strong> saves the selected state again as the current correspondent configuration. The currently active state remains in history as its own version.</p><div id="corrHistoryList"></div></div>
</section>
</section>
</main>
<script>
let currentConfig=null;
const $=id=>document.getElementById(id);
function draft(){return {version:currentConfig?.version||1,updated_at:currentConfig?.updated_at||null,system_prompt:$('systemPrompt').value,classification_template:$('classificationTemplate').value,model:$('model').value.trim(),num_ctx:Number($('numCtx').value),num_predict:Number($('numPredict').value),temperature:Number($('temperature').value),think:$('think').value==='true',keep_alive:/^-?\d+(\.\d+)?$/.test($('keepAlive').value.trim())?Number($('keepAlive').value):$('keepAlive').value,content_char_limit:Number($('contentLimit').value),content_head_ratio:Number($('headRatio').value),max_tags:Number($('maxTags').value),ollama_timeout_seconds:Number($('ollamaTimeout').value)}}
function fill(c){currentConfig=c;$('systemPrompt').value=c.system_prompt;$('classificationTemplate').value=c.classification_template;$('model').value=c.model;$('numCtx').value=c.num_ctx;$('numPredict').value=c.num_predict;$('temperature').value=c.temperature;$('think').value=String(c.think);$('keepAlive').value=c.keep_alive;$('contentLimit').value=c.content_char_limit;$('headRatio').value=c.content_head_ratio;$('maxTags').value=c.max_tags;$('ollamaTimeout').value=c.ollama_timeout_seconds;$('classConfigStatus').textContent=`Active configuration · v${c.version} · ${c.model}`}
async function api(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});const t=await r.text();let data;try{data=JSON.parse(t)}catch{data={error:t}}if(!r.ok)throw new Error(data.error||`${r.status} ${r.statusText}`);return data}
async function init(){try{const s=await api('/api/state');fill(s.config);$('placeholders').innerHTML=Object.entries(s.placeholders).map(([k,v])=>`<div class="placeholder-item"><code>{{${k}}}</code><span>${v}</span></div>`).join('');await loadHistory();$('topStatus').textContent='Control Center ready';$('topStatus').className='status ok'}catch(e){$('topStatus').textContent=e.message;$('topStatus').className='status bad'}}
function setStatus(id,msg,ok=true){$(id).textContent=msg;$(id).className='status '+(ok?'ok':'bad')}
$('validateBtn').onclick=async()=>{try{const r=await api('/api/config/validate',{method:'POST',body:JSON.stringify({config:draft()})});setStatus('saveStatus',`Configuration valid · not saved yet · SHA ${r.config_sha256.slice(0,12)}`)}catch(e){setStatus('saveStatus',e.message,false)}};
$('saveBtn').onclick=async()=>{try{const r=await api('/api/config/save',{method:'POST',body:JSON.stringify({config:draft()})});fill(r.config);setStatus('saveStatus',`Saved and active from the next classification job · v${r.config.version}`);await loadHistory()}catch(e){setStatus('saveStatus',e.message,false)}};
async function doPreview(run){const id=Number($('docId').value);if(!id)return;setStatus('testStatus',run?'Model test running…':'Preparing final prompt…');try{const r=await api(run?'/api/test':'/api/preview',{method:'POST',body:JSON.stringify({document_id:id,config:draft()})});$('systemPreview').textContent=r.rendered.system_prompt;$('userPreview').textContent=r.rendered.user_prompt;$('schemaPreview').textContent=JSON.stringify(r.rendered.schema,null,2);$('taxonomyPreview').textContent=JSON.stringify(r.taxonomy,null,2);$('previewMeta').textContent=JSON.stringify(r.meta,null,2);$('testResult').textContent=run?JSON.stringify({suggestion:r.suggestion,validation_errors:r.validation_errors,performance:r.performance},null,2):'';setStatus('testStatus',run?'Model test complete · Paperless was not modified.':'Final prompt previewed · the model was not called.')}catch(e){setStatus('testStatus',e.message,false)}}
$('previewBtn').onclick=()=>doPreview(false);$('testBtn').onclick=()=>doPreview(true);

let currentAppConfig=null;
function appDraft(){return {version:currentAppConfig?.version||1,updated_at:currentAppConfig?.updated_at||null,connections:{paperless_url:$('appPaperlessUrl').value.trim(),ollama_url:$('appOllamaUrl').value.trim()},workflow:{ocr_queue_tag:$('appOcrQueueTag').value.trim(),ocr_error_tag:$('appOcrErrorTag').value.trim(),llm_queue_tag:$('appLlmQueueTag').value.trim(),llm_error_tag:$('appLlmErrorTag').value.trim(),review_tag:$('appReviewTag').value.trim(),extra_excluded_tags:$('appExtraExcludedTags').value.split(',').map(x=>x.trim()).filter(Boolean)},ocr:{language:$('appOcrLanguage').value.trim(),version:$('appOcrVersion').value.trim(),device:$('appOcrDevice').value.trim()},runtime:{poll_interval_seconds:Number($('appPollInterval').value),review_prune_interval_seconds:Number($('appReviewPruneInterval').value),dry_run:$('appDryRun').value==='true'}}}
function appFill(c,tokenConfigured){currentAppConfig=c;$('appPaperlessUrl').value=c.connections.paperless_url;$('appOllamaUrl').value=c.connections.ollama_url;$('appOcrQueueTag').value=c.workflow.ocr_queue_tag;$('appOcrErrorTag').value=c.workflow.ocr_error_tag;$('appLlmQueueTag').value=c.workflow.llm_queue_tag;$('appLlmErrorTag').value=c.workflow.llm_error_tag;$('appReviewTag').value=c.workflow.review_tag;$('appExtraExcludedTags').value=(c.workflow.extra_excluded_tags||[]).join(', ');$('appOcrLanguage').value=c.ocr.language;$('appOcrVersion').value=c.ocr.version;$('appOcrDevice').value=c.ocr.device;$('appPollInterval').value=c.runtime.poll_interval_seconds;$('appReviewPruneInterval').value=c.runtime.review_prune_interval_seconds;$('appDryRun').value=String(c.runtime.dry_run);$('appConfigStatus').textContent=`v${c.version} · ${c.runtime.dry_run?'DRY RUN':'PRODUCTION'}`;$('appConfigStatus').style.color=c.runtime.dry_run?'var(--warn)':'var(--ok)';$('appTokenStatus').textContent=tokenConfigured?'API token is configured in the deployment environment.':'API token is missing from the deployment environment.';$('appTokenStatus').className='status '+(tokenConfigured?'ok':'bad')}
function renderAppHistory(items){$('appHistoryList').innerHTML=items.length?items.map(x=>`<div class="history-item"><span class="badge">v${x.version??'?'}</span><span>${x.file}</span><span class="muted">${x.updated_at||''}<br>${(x.config_sha256||'').slice(0,16)}</span><button onclick="restoreAppHistory('${x.file}')">Restore this version</button></div>`).join(''):'<p class="muted">No older saved version yet.</p>'}
async function loadApp(){try{const r=await api('/api/app/state');appFill(r.config,r.token_configured);renderAppHistory(r.history||[])}catch(e){$('appConfigStatus').textContent='Error';$('appConfigStatus').style.color='var(--bad)';setStatus('appSaveStatus',e.message,false)}}
$('appValidateBtn').onclick=async()=>{try{const r=await api('/api/app/validate',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appSaveStatus',`Configuration valid · not saved yet · SHA ${r.config_sha256.slice(0,12)}`)}catch(e){setStatus('appSaveStatus',e.message,false)}};
$('appSaveBtn').onclick=async()=>{try{const r=await api('/api/app/save',{method:'POST',body:JSON.stringify({config:appDraft()})});appFill(r.config,r.token_configured);setStatus('appSaveStatus',`Saved · AppConfig v${r.config.version}. Workers reload runtime settings automatically.`);renderAppHistory(r.history||[])}catch(e){setStatus('appSaveStatus',e.message,false)}};
$('appConnectionTestBtn').onclick=async()=>{setStatus('appConnectionStatus','Testing connections…');try{const r=await api('/api/app/connections/test',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appConnectionStatus',`Paperless: ${r.paperless.ok?'OK':'ERROR'}${r.paperless.detail?' · '+r.paperless.detail:''}\nOllama: ${r.ollama.ok?'OK':'ERROR'}${r.ollama.detail?' · '+r.ollama.detail:''}`,r.paperless.ok&&r.ollama.ok)}catch(e){setStatus('appConnectionStatus',e.message,false)}};
async function refreshAppHistory(){const r=await api('/api/app/history');renderAppHistory(r.items||[])}
$('appHistoryRefresh').onclick=()=>refreshAppHistory().catch(e=>setStatus('appSaveStatus',e.message,false));
window.restoreAppHistory=async file=>{if(!confirm(`Restore these app settings? The selected state will be saved as a new current version; the current state remains in history.\n\nFile: ${file}`))return;try{const r=await api('/api/app/history/restore',{method:'POST',body:JSON.stringify({file})});appFill(r.config,r.token_configured);renderAppHistory(r.history||[]);setStatus('appSaveStatus',`Restored and saved as a new current version · v${r.config.version}`)}catch(e){alert(e.message)}};

let currentCorrConfig=null;
function corrDraft(){return {version:currentCorrConfig?.version||1,updated_at:currentCorrConfig?.updated_at||null,enabled:$('corrEnabled').value==='true',system_prompt:$('corrSystemPrompt').value,prompt_template:$('corrPromptTemplate').value,model:$('corrModel').value.trim(),num_ctx:Number($('corrNumCtx').value),num_predict:Number($('corrNumPredict').value),temperature:Number($('corrTemperature').value),think:$('corrThink').value==='true',keep_alive:/^-?\d+(\.\d+)?$/.test($('corrKeepAlive').value.trim())?Number($('corrKeepAlive').value):$('corrKeepAlive').value,content_char_limit:Number($('corrContentLimit').value),content_head_ratio:Number($('corrHeadRatio').value),ollama_timeout_seconds:Number($('corrTimeout').value)}}
function corrFill(c){currentCorrConfig=c;$('corrEnabled').value=String(c.enabled);$('corrSystemPrompt').value=c.system_prompt;$('corrPromptTemplate').value=c.prompt_template;$('corrModel').value=c.model;$('corrNumCtx').value=c.num_ctx;$('corrNumPredict').value=c.num_predict;$('corrTemperature').value=c.temperature;$('corrThink').value=String(c.think);$('corrKeepAlive').value=c.keep_alive;$('corrContentLimit').value=c.content_char_limit;$('corrHeadRatio').value=c.content_head_ratio;$('corrTimeout').value=c.ollama_timeout_seconds;$('corrConfigStatus').textContent=`${c.enabled?'PRODUCTION ON':'PRODUCTION OFF'} · v${c.version} · ${c.model}`;$('corrConfigStatus').style.color=c.enabled?'var(--ok)':'var(--muted)'}
function renderCorrHistory(items){$('corrHistoryList').innerHTML=items.length?items.map(x=>`<div class="history-item"><span class="badge">v${x.version??'?'}</span><span>${x.file}</span><span class="muted">${x.updated_at||''}<br>${(x.config_sha256||'').slice(0,16)}</span><button onclick="restoreCorrHistory('${x.file}')">Restore this version</button></div>`).join(''):'<p class="muted">No older saved version yet.</p>'}
async function loadCorrespondent(){try{const s=await api('/api/correspondent/state');corrFill(s.config);$('corrPlaceholders').innerHTML=Object.entries(s.placeholders).map(([k,v])=>`<div class="placeholder-item"><code>{{${k}}}</code><span>${v}</span></div>`).join('');renderCorrHistory(s.history||[])}catch(e){$('corrConfigStatus').textContent='Error';$('corrConfigStatus').style.color='var(--bad)';setStatus('corrSaveStatus',e.message,false)}}
async function refreshCorrHistory(){const s=await api('/api/correspondent/state');renderCorrHistory(s.history||[])}
$('corrValidateBtn').onclick=async()=>{try{const r=await api('/api/correspondent/validate',{method:'POST',body:JSON.stringify({config:corrDraft()})});setStatus('corrSaveStatus',`Configuration valid · not saved yet · SHA ${r.config_sha256.slice(0,12)}`)}catch(e){setStatus('corrSaveStatus',e.message,false)}};
$('corrSaveBtn').onclick=async()=>{try{const r=await api('/api/correspondent/save',{method:'POST',body:JSON.stringify({config:corrDraft()})});corrFill(r.config);setStatus('corrSaveStatus',`Saved as v${r.config.version} · production fallback ${r.config.enabled?'ON':'OFF'}`);await refreshCorrHistory()}catch(e){setStatus('corrSaveStatus',e.message,false)}};
async function corrPreview(run){const id=Number($('corrDocId').value);if(!id)return;setStatus('corrTestStatus',run?'Model test running…':'Preparing final prompt…');try{const r=await api(run?'/api/correspondent/test':'/api/correspondent/preview',{method:'POST',body:JSON.stringify({document_id:id,config:corrDraft()})});$('corrSystemPreview').textContent=r.rendered.system_prompt;$('corrUserPreview').textContent=r.rendered.user_prompt;$('corrSchemaPreview').textContent=JSON.stringify(r.rendered.schema,null,2);$('corrPreviewMeta').textContent=JSON.stringify(r.meta,null,2);$('corrTestResult').textContent=run?JSON.stringify({suggestion:r.suggestion,validation_errors:r.validation_errors,performance:r.performance},null,2):'';setStatus('corrTestStatus',run?'Model test complete · Paperless was not modified and no correspondent suggestion was saved.':'Final prompt previewed · the model was not called.')}catch(e){setStatus('corrTestStatus',e.message,false)}}
$('corrPreviewBtn').onclick=()=>corrPreview(false);$('corrTestBtn').onclick=()=>corrPreview(true);$('corrHistoryRefresh').onclick=()=>refreshCorrHistory().catch(e=>setStatus('corrSaveStatus',e.message,false));
window.restoreCorrHistory=async file=>{if(!confirm(`Restore this correspondent version? The selected state will be saved as a new current version; the current state remains in history.\n\nFile: ${file}`))return;try{const r=await api('/api/correspondent/history/restore',{method:'POST',body:JSON.stringify({file})});corrFill(r.config);setStatus('corrSaveStatus',`Restored and saved as a new current version · v${r.config.version}`);await refreshCorrHistory()}catch(e){alert(e.message)}};

async function loadHistory(){try{const r=await api('/api/history');$('historyList').innerHTML=r.items.length?r.items.map(x=>`<div class="history-item"><span class="badge">v${x.version??'?'}</span><span>${x.file}</span><span class="muted">${x.updated_at||''}<br>${(x.config_sha256||'').slice(0,16)}</span><button onclick="restoreHistory('${x.file}')">Restore this version</button></div>`).join(''):'<p class="muted">No older saved version yet.</p>'}catch(e){$('historyList').textContent=e.message}}
window.restoreHistory=async file=>{if(!confirm(`Restore this classification version? The selected state will be saved as a new current version; the current state remains in history.\n\nFile: ${file}`))return;try{const r=await api('/api/history/restore',{method:'POST',body:JSON.stringify({file})});fill(r.config);setStatus('saveStatus',`Restored and saved as a new current version · v${r.config.version}`);await loadHistory()}catch(e){alert(e.message)}};$('historyRefresh').onclick=loadHistory;

function activateMode(mode){if(!['classification','correspondent','app'].includes(mode))mode='classification';document.querySelectorAll('.mode-switch button').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));document.querySelectorAll('.mode').forEach(x=>x.classList.toggle('active',x.id===`mode-${mode}`));try{localStorage.setItem('paperlessPromptStudioMode',mode)}catch{}}
function activateSubtab(mode,id){const nav=document.querySelector(`.subtabs[data-mode-tabs="${mode}"]`);const page=$(id);if(!nav||!page||page.dataset.pageMode!==mode)return;nav.querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.subtab===id));document.querySelectorAll(`.subtab-page[data-page-mode="${mode}"]`).forEach(x=>x.classList.toggle('active',x.id===id));try{localStorage.setItem(`paperlessPromptStudioTab:${mode}`,id)}catch{}}
document.querySelectorAll('.mode-switch button').forEach(b=>b.onclick=()=>activateMode(b.dataset.mode));
document.querySelectorAll('.subtabs button').forEach(b=>b.onclick=()=>{const mode=b.closest('.subtabs').dataset.modeTabs;activateSubtab(mode,b.dataset.subtab)});
let initialMode='classification';try{initialMode=localStorage.getItem('paperlessPromptStudioMode')||initialMode}catch{}activateMode(initialMode);
for(const [mode,fallback] of [['classification','prompt'],['correspondent','corr-prompt'],['app','app-connections']]){let tab=fallback;try{tab=localStorage.getItem(`paperlessPromptStudioTab:${mode}`)||fallback}catch{}activateSubtab(mode,tab)}
init();
loadCorrespondent();
loadApp();
</script>
</body>
</html>'''


def response(handler, status, data, content_type="application/json; charset=utf-8"):
    if isinstance(data, (dict, list)):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    elif isinstance(data, str):
        body = data.encode("utf-8")
    else:
        body = bytes(data)
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def body_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 2_000_000:
        raise ValueError("Request too large")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8"))


def draft_config(payload):
    cfg = payload.get("config")
    if cfg is None:
        cfg = load_config()
    return validate_config(cfg)


def preview_for(doc_id, config):
    tax = client.taxonomy()
    doc = client.document(doc_id)
    rendered = render_prompts(doc, tax, config)
    return tax, doc, rendered


class Handler(BaseHTTPRequestHandler):
    server_version = "paperless-local-ai-control-center/0.1"

    def log_message(self, fmt, *args):
        print(f"[HTTP] {self.address_string()} {fmt % args}", flush=True)

    def _dispatch(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if self.command == "GET" and path == "/":
            return response(self, HTTPStatus.OK, HTML, "text/html; charset=utf-8")

        if self.command == "GET" and path == "/api/app/state":
            cfg = ensure_app_config()
            return response(self, HTTPStatus.OK, {
                "config": cfg,
                "config_sha256": app_config_hash(cfg),
                "history": list_app_history(),
                "token_configured": bool(PAPERLESS_TOKEN),
            })

        if self.command == "GET" and path == "/api/app/history":
            return response(self, HTTPStatus.OK, {"items": list_app_history()})

        if self.command == "POST" and path == "/api/app/validate":
            payload = body_json(self)
            cfg = validate_app_config(payload.get("config"))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config_sha256": app_config_hash(cfg),
            })

        if self.command == "POST" and path == "/api/app/save":
            payload = body_json(self)
            cfg = save_app_config(payload.get("config"), source="prompt-ui")
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
                "config_sha256": app_config_hash(cfg),
                "history": list_app_history(),
                "token_configured": bool(PAPERLESS_TOKEN),
            })

        if self.command == "POST" and path == "/api/app/history/restore":
            payload = body_json(self)
            cfg = restore_app_history(payload.get("file", ""))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
                "history": list_app_history(),
                "token_configured": bool(PAPERLESS_TOKEN),
            })

        if self.command == "POST" and path == "/api/app/connections/test":
            payload = body_json(self)
            cfg = validate_app_config(payload.get("config"))
            paperless_url = cfg["connections"]["paperless_url"]
            ollama_url = cfg["connections"]["ollama_url"]

            paperless_result = {"ok": False, "detail": ""}
            if not PAPERLESS_TOKEN:
                paperless_result["detail"] = "PAPERLESS_TOKEN is missing from the deployment environment"
            else:
                try:
                    r = requests.get(
                        paperless_url + "/api/documents/",
                        params={"page_size": 1},
                        headers={
                            "Authorization": f"Token {PAPERLESS_TOKEN}",
                            "Accept": "application/json",
                        },
                        timeout=20,
                    )
                    r.raise_for_status()
                    paperless_result = {"ok": True, "detail": f"HTTP {r.status_code}"}
                except Exception as exc:
                    paperless_result["detail"] = f"{type(exc).__name__}: {exc}"

            ollama_result = {"ok": False, "detail": ""}
            try:
                r = requests.get(ollama_url + "/api/tags", timeout=20)
                r.raise_for_status()
                payload = r.json()
                count = len(payload.get("models", [])) if isinstance(payload, dict) else 0
                ollama_result = {"ok": True, "detail": f"{count} model(s) found"}
            except Exception as exc:
                ollama_result["detail"] = f"{type(exc).__name__}: {exc}"

            return response(self, HTTPStatus.OK, {
                "paperless": paperless_result,
                "ollama": ollama_result,
            })

        if self.command == "GET" and path == "/api/state":
            cfg = ensure_config()
            return response(self, HTTPStatus.OK, {
                "config": cfg,
                "placeholders": PLACEHOLDERS,
                "hashes": prompt_hashes(cfg),
                "connections": ensure_app_config()["connections"],
            })

        if self.command == "GET" and path == "/api/health":
            cfg = load_config()
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config_version": cfg["version"],
                "model": cfg["model"],
            })

        if self.command == "GET" and path == "/api/history":
            return response(self, HTTPStatus.OK, {"items": list_history()})

        if self.command == "POST" and path == "/api/config/validate":
            payload = body_json(self)
            cfg = validate_config(payload.get("config"))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config_sha256": prompt_hashes(cfg)["config_sha256"],
            })

        if self.command == "POST" and path == "/api/config/save":
            payload = body_json(self)
            cfg = save_config(payload.get("config"), source="prompt-ui")
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
                "hashes": prompt_hashes(cfg),
            })

        if self.command == "POST" and path == "/api/history/restore":
            payload = body_json(self)
            cfg = restore_history(payload.get("file", ""))
            return response(self, HTTPStatus.OK, {"ok": True, "config": cfg})

        if self.command == "POST" and path in {"/api/preview", "/api/test"}:
            payload = body_json(self)
            doc_id = int(payload["document_id"])
            cfg = draft_config(payload)
            tax, doc, rendered = preview_for(doc_id, cfg)
            base = {
                "document": {
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "created": doc.get("created"),
                },
                "rendered": {
                    "system_prompt": rendered["system_prompt"],
                    "user_prompt": rendered["user_prompt"],
                    "schema": rendered["schema"],
                },
                "taxonomy": {
                    "tags": tax["content_tags"],
                    "document_types": tax["document_types"],
                    "correspondents": tax["correspondents"],
                },
                "meta": {
                    "config_version": cfg["version"],
                    "draft_config_sha256": prompt_hashes(cfg)["config_sha256"],
                    "model": cfg["model"],
                    "num_ctx": cfg["num_ctx"],
                    "num_predict": cfg["num_predict"],
                    "temperature": cfg["temperature"],
                    "think": cfg["think"],
                    "keep_alive": cfg["keep_alive"],
                    "content_chars_used": rendered["content_chars_used"],
                    "content_truncated": rendered["content_truncated"],
                },
            }
            if path == "/api/preview":
                return response(self, HTTPStatus.OK, base)

            with ai_resource_lock("LLM-PROMPT-UI", doc_id):
                result, raw, wall_duration, _payload = call_ollama(rendered, cfg)
            errors = validate_result(result, tax, cfg)
            base.update({
                "suggestion": result,
                "validation_errors": errors,
                "performance": performance_from_raw(raw, wall_duration),
            })
            return response(self, HTTPStatus.OK, base)


        if self.command == "GET" and path == "/api/correspondent/state":
            cfg = ensure_correspondent_config()
            return response(self, HTTPStatus.OK, {
                "config": cfg,
                "placeholders": CORRESPONDENT_PLACEHOLDERS,
                "hashes": correspondent_prompt_hashes(cfg),
                "history": list_correspondent_history(),
            })

        if self.command == "POST" and path == "/api/correspondent/validate":
            payload = body_json(self)
            cfg = validate_correspondent_config(payload.get("config"))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config_sha256": correspondent_prompt_hashes(cfg)["config_sha256"],
            })

        if self.command == "POST" and path == "/api/correspondent/save":
            payload = body_json(self)
            cfg = save_correspondent_config(
                payload.get("config"),
                source="prompt-ui",
            )
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
                "hashes": correspondent_prompt_hashes(cfg),
            })

        if self.command == "POST" and path == "/api/correspondent/history/restore":
            payload = body_json(self)
            cfg = restore_correspondent_history(payload.get("file", ""))
            return response(self, HTTPStatus.OK, {
                "ok": True,
                "config": cfg,
            })

        if self.command == "POST" and path in {
            "/api/correspondent/preview",
            "/api/correspondent/test",
        }:
            payload = body_json(self)
            doc_id = int(payload["document_id"])
            cfg = validate_correspondent_config(payload.get("config"))
            tax = client.taxonomy()
            doc = client.document(doc_id)
            rendered = render_correspondent_prompts(doc, tax, cfg)

            base = {
                "document": {
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "created": doc.get("created"),
                },
                "rendered": {
                    "system_prompt": rendered["system_prompt"],
                    "user_prompt": rendered["user_prompt"],
                    "schema": rendered["schema"],
                },
                "meta": {
                    "config_version": cfg["version"],
                    "draft_config_sha256": correspondent_prompt_hashes(cfg)["config_sha256"],
                    "enabled_in_draft": cfg["enabled"],
                    "model": cfg["model"],
                    "num_ctx": cfg["num_ctx"],
                    "num_predict": cfg["num_predict"],
                    "temperature": cfg["temperature"],
                    "think": cfg["think"],
                    "keep_alive": cfg["keep_alive"],
                    "content_char_limit": cfg["content_char_limit"],
                    "content_head_ratio": cfg["content_head_ratio"],
                    "content_chars_used": rendered["content_chars_used"],
                    "content_truncated": rendered["content_truncated"],
                    "existing_correspondents": len(tax["correspondents"]),
                },
            }

            if path == "/api/correspondent/preview":
                return response(self, HTTPStatus.OK, base)

            with ai_resource_lock("LLM-CORRESPONDENT-UI", doc_id):
                result, raw, wall_duration, _payload = (
                    call_correspondent_ollama(rendered, cfg)
                )

            errors = validate_correspondent_result(result)
            base.update({
                "suggestion": result,
                "validation_errors": errors,
                "performance": correspondent_performance_from_raw(
                    raw,
                    wall_duration,
                ),
            })
            return response(self, HTTPStatus.OK, base)

        return response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_GET(self):
        try:
            self._dispatch()
        except Exception as e:
            traceback.print_exc()
            response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        try:
            self._dispatch()
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            response(self, HTTPStatus.BAD_REQUEST, {"error": f"{type(e).__name__}: {e}"})
        except Exception as e:
            traceback.print_exc()
            response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    app_cfg = ensure_app_config()
    cfg = ensure_config()
    print(
        f"paperless-local-ai Control Center at http://{HOST}:{PORT} · AppConfig v{app_cfg['version']} · PromptConfig v{cfg['version']}",
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
