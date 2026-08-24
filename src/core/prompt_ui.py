from __future__ import annotations

import json
import os
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import requests

from app_config import (
    config_hash as app_config_hash,
    ensure_config as ensure_app_config,
    list_history as list_app_history,
    load_config as load_app_config,
    restore_history as restore_app_history,
    save_config as save_app_config,
    validate_config as validate_app_config,
)
from correspondent_resolver import resolve_correspondent
from history_runtime import HistoryIndex, request_history_refresh
from ocr_recovery_state import (
    dismiss_failure as dismiss_ocr_failure,
    recovery_state_for_ui,
    request_retry_now as request_ocr_retry_now,
)
from prompt_runtime import (
    PLACEHOLDERS,
    PROMPT_PRESETS,
    PaperlessClient,
    ai_resource_lock,
    call_ollama,
    ensure_config,
    list_history,
    load_config,
    performance_from_raw,
    prompt_hashes,
    prune_parent_tag_names,
    render_prompts,
    restore_history,
    save_config,
    validate_config,
    validate_result,
)


HOST = os.getenv("PROMPT_UI_HOST", "0.0.0.0")
PORT = int(os.getenv("PROMPT_UI_PORT", "8080"))
PAPERLESS_TOKEN = os.environ.get("PAPERLESS_TOKEN", "")
OCR_SERVICE_INTERNAL_URL = os.getenv(
    "OCR_SERVICE_INTERNAL_URL", "http://ocr-service:8082"
).rstrip("/")
APP_VERSION = os.getenv("APP_VERSION", "dev").strip() or "dev"
DOCS_REF = "main" if APP_VERSION in {"dev", "main"} else f"v{APP_VERSION.removeprefix('v')}"
DOCS_BASE_URL = f"https://github.com/lucaperl/paperless-local-ai/blob/{DOCS_REF}"
TAGGING_DOCS_URL = f"{DOCS_BASE_URL}/docs/tagging.md"
PAPERLESS_SETUP_DOCS_URL = f"{DOCS_BASE_URL}/docs/paperless-setup.md"

client = PaperlessClient()
history_index = HistoryIndex()


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>paperless-local-ai Control Center</title>
<style>
:root{color-scheme:dark;--bg:#0a0f17;--side:#0c131d;--panel:#121a26;--panel2:#0f1722;--line:#263448;--line2:#31435b;--text:#f0f4f8;--muted:#93a2b7;--sub:#66758a;--green:#55d483;--blue:#6ba8ff;--orange:#f6bd60;--red:#ff7d7d;--radius:12px;--shadow:0 10px 30px rgba(0,0,0,.18)}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input,textarea,select{font:inherit}button{cursor:pointer}code,pre,textarea,input.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}a{color:#8fbdff}
.app{min-height:100vh;display:grid;grid-template-columns:250px 1fr}.sidebar{position:sticky;top:0;height:100vh;background:linear-gradient(180deg,#0d1520,#0a111a);border-right:1px solid var(--line);padding:20px 14px;display:flex;flex-direction:column;gap:20px}.brand{padding:4px 8px 10px}.brand-title{display:flex;align-items:center;gap:10px;font-size:17px;font-weight:750}.brand-mark{width:32px;height:32px;border-radius:9px;background:#14243a;border:1px solid #36506e;display:grid;place-items:center;color:var(--blue);font-weight:900}.brand-sub{margin:5px 0 0 42px;color:var(--green);font-size:13px}.nav-group{display:grid;gap:5px}.nav-label{padding:0 10px 5px;color:var(--sub);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.nav-btn{border:1px solid transparent;background:transparent;color:#ccd6e3;border-radius:9px;padding:10px 11px;text-align:left;display:flex;align-items:center;gap:10px}.nav-btn:hover{background:#111b28}.nav-btn.active{background:#173325;border-color:#27513b;color:#ecfff3}.sidebar-footer{margin-top:auto;padding:12px;border:1px solid var(--line);background:#0e1722;border-radius:10px}.status-line{display:flex;align-items:center;gap:8px}.dot{width:8px;height:8px;border-radius:50%;background:var(--green)}.mini{font-size:12px;color:var(--muted)}
.main{min-width:0}.topbar{min-height:76px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 28px;background:rgba(11,17,26,.9);position:sticky;top:0;z-index:10;backdrop-filter:blur(10px)}.page-title{font-size:22px;font-weight:750}.page-subtitle{margin-top:2px;color:var(--muted)}.top-actions{display:flex;gap:10px}.pill{padding:7px 10px;border-radius:999px;border:1px solid var(--line);background:#101a27;color:var(--muted);font-size:12px}.pill.good{color:var(--green);border-color:#28563e;background:#10271c}.pill.warn{color:var(--orange);border-color:#6a5127;background:#261d0f}.pill.bad{color:var(--red);border-color:#653638;background:#2b1517}
.content{padding:24px 28px 48px;max-width:1560px;margin:auto}.page{display:none}.page.active{display:block}.page-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:16px}.page-head h1{font-size:22px;margin:0}.page-head p{margin:4px 0 0;color:var(--muted);max-width:980px}.config-badge{padding:8px 10px;border-radius:9px;background:#111b28;border:1px solid var(--line);color:var(--blue);font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;white-space:nowrap}
.card{background:linear-gradient(180deg,#131c29,#101823);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}.panel{padding:18px}.panel+.panel{margin-top:14px}.hero-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}.metric-card{padding:18px}.metric-title{font-size:15px;font-weight:700}.metric-value{font-size:14px;margin-top:10px}.metric-detail{margin-top:4px;color:var(--muted);font-size:12px}.good-text{color:var(--green)!important}.warn-text{color:var(--orange)!important}.bad-text{color:var(--red)!important}.section-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:16px}.section{padding:18px}.section h2,.panel h2,.panel h3{margin-top:0}.section p,.panel>p{color:var(--muted)}.kv{display:grid;grid-template-columns:1fr auto;gap:10px;padding:10px 0;border-bottom:1px solid #202c3d}.kv:last-child{border-bottom:0}.kv span:first-child{color:var(--muted)}
.flow{display:grid;gap:0;margin-top:16px}.flow-row{display:grid;grid-template-columns:32px 1fr;gap:12px;position:relative}.flow-row:not(:last-child)::before{content:"";position:absolute;left:15px;top:31px;bottom:-7px;width:2px;background:#29405b}.flow-dot{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:#12253a;border:1px solid #2a4c70;color:var(--blue);font-size:12px;z-index:1}.flow-row.local .flow-dot{background:#123022;border-color:#28563e;color:var(--green)}.flow-copy{padding:5px 0 18px}.flow-title{font-weight:650}.flow-desc{color:var(--muted);font-size:12px;margin-top:2px}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}.btn{border:1px solid var(--line2);background:#182434;color:var(--text);padding:9px 13px;border-radius:8px}.btn:hover{background:#1d2b3e}.btn.primary{background:#2460aa;border-color:#3275c6}.btn.good{background:#173925;border-color:#2a6742;color:#eafff0}.toolbar-status{margin-left:auto;color:var(--muted);font-size:12px}.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0;border-bottom:1px solid var(--line);padding-bottom:9px}.tab{border:1px solid transparent;background:transparent;color:var(--muted);padding:8px 11px;border-radius:8px}.tab:hover{background:#121c29;color:var(--text)}.tab.active{background:#1a2a3e;border-color:#2c425d;color:var(--text)}.tab-page{display:none}.tab-page.active{display:block}
.section-help{border:1px solid var(--line);background:#0e1722;border-radius:9px;margin:0 0 14px;overflow:hidden}.section-help summary{cursor:pointer;list-style:none;padding:10px 12px;color:#c5d1df;font-size:12px;font-weight:650}.section-help summary::-webkit-details-marker{display:none}.section-help[open] summary{border-bottom:1px solid var(--line)}.help-body{padding:11px 12px;color:var(--muted);font-size:12px;line-height:1.55}.action-note{display:flex;gap:9px;align-items:flex-start;margin:10px 0 14px;padding:10px 12px;border-radius:9px;border:1px solid #35506d;background:#101b29;color:#cbd8e6;font-size:12px}.action-note strong{color:#fff}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.form-grid.three{grid-template-columns:repeat(3,1fr)}.field label{display:block;color:#b7c2d1;margin-bottom:6px;font-size:12px}.field-help{color:var(--muted);font-size:11px;margin-top:5px}input,textarea,select{width:100%;border:1px solid var(--line);background:#0b121b;color:var(--text);border-radius:8px;padding:9px 10px;outline:none}input:focus,textarea:focus,select:focus{border-color:#4b77a8;box-shadow:0 0 0 3px rgba(75,119,168,.14)}textarea{min-height:230px;resize:vertical;line-height:1.45}.split{display:grid;grid-template-columns:1fr 1fr;gap:14px}.test-row{display:grid;grid-template-columns:220px auto auto 1fr;gap:10px;align-items:end}.result{margin-top:14px;display:grid;grid-template-columns:1fr 1fr;gap:14px}.primary-result{grid-column:1/-1}.preview{background:#091019;border:1px solid var(--line);border-radius:8px;padding:12px;min-height:180px;max-height:620px;white-space:pre-wrap;overflow:auto;font-size:12px;color:#ced8e4}.status-box{padding:9px 11px;border-radius:8px;background:#111b28;border:1px solid var(--line);color:var(--muted);white-space:pre-wrap}.status-box.good{color:var(--green);border-color:#28563e}.status-box.bad{color:var(--red);border-color:#6b2f38}.result-summary{padding:12px;border:1px solid var(--line);border-radius:9px;background:#0d1520}.result-state{font-weight:700;margin-bottom:10px}.result-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.result-field{padding:8px 9px;border:1px solid #263448;border-radius:8px;background:#0b121b}.result-field span{display:block;color:var(--muted);font-size:11px;margin-bottom:3px}.history-item{display:grid;grid-template-columns:90px 1fr 180px auto;gap:10px;align-items:center;padding:11px 0;border-bottom:1px solid #202c3d}.connection-row{display:grid;grid-template-columns:1fr 1fr;gap:14px}.connection{padding:16px}.placeholder-grid{display:grid;grid-template-columns:repeat(2,minmax(260px,1fr));gap:8px;margin-top:10px}.placeholder-item{background:#0d1520;border:1px solid var(--line);border-radius:8px;padding:10px}.placeholder-item code{display:block;color:var(--blue);font-size:12px;margin-bottom:4px}.placeholder-item span{color:var(--muted);font-size:11px}
.strategy-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.strategy-card{display:block;border:1px solid var(--line2);background:#0d1520;border-radius:11px;padding:16px;cursor:pointer;position:relative}.strategy-card:has(input:checked){border-color:#4f8bd1;background:#10223a;box-shadow:0 0 0 2px rgba(107,168,255,.08)}.strategy-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.strategy-title{display:flex;align-items:center;gap:9px;font-weight:750}.strategy-title input{width:auto}.strategy-copy{margin-top:9px;color:var(--muted);font-size:12px;line-height:1.55}.strategy-best{margin-top:9px;color:#cbd8e6;font-size:12px}.badge-rec{padding:4px 7px;border-radius:999px;border:1px solid #28563e;color:var(--green);background:#10271c;font-size:10px;font-weight:700;white-space:nowrap}.badge-model{padding:4px 7px;border-radius:999px;border:1px solid #3a4d66;color:#b7c8da;background:#111b28;font-size:10px;font-weight:700;white-space:nowrap}
.health-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.health-metric{padding:12px;background:#0d1520;border:1px solid var(--line);border-radius:9px}.health-metric span{display:block;color:var(--muted);font-size:11px}.health-metric strong{display:block;font-size:18px;margin-top:4px}.tag-table{width:100%;border-collapse:collapse;margin-top:8px}.tag-table th,.tag-table td{text-align:left;padding:8px;border-bottom:1px solid #202c3d;font-size:12px}.tag-table th{color:var(--muted);font-weight:600}.guidance-list{display:grid;gap:8px}.guidance-item{border:1px solid var(--line);border-radius:9px;background:#0d1520;overflow:hidden}.guidance-item summary{cursor:pointer;padding:11px 12px;display:flex;align-items:center;justify-content:space-between;gap:12px}.guidance-item .guidance-body{padding:0 12px 12px}.guidance-item textarea{min-height:100px}.guidance-state{color:var(--muted);font-size:11px}.inconsistency{padding:11px 0;border-bottom:1px solid #202c3d}.inconsistency:last-child{border-bottom:0}.inconsistency-tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}.tag-chip{padding:3px 7px;border-radius:999px;border:1px solid #3a4d66;background:#111b28;color:#c9d4e0;font-size:10px}.doc-list{margin:8px 0 0;padding-left:20px;color:var(--muted);font-size:11px}.separate-note{border-left:3px solid #4c6f99;padding:9px 11px;background:#0d1722;color:#b9c8d8;font-size:12px;margin:10px 0 14px}
.failure-item{padding:11px 0;border-bottom:1px solid #202c3d}.failure-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
@media(max-width:1100px){.app{grid-template-columns:210px 1fr}.hero-grid,.health-grid{grid-template-columns:1fr 1fr}.section-grid,.split,.result,.strategy-grid{grid-template-columns:1fr}.form-grid.three{grid-template-columns:1fr 1fr}}
@media(max-width:760px){.app{display:block}.sidebar{position:static;height:auto}.nav-group{grid-template-columns:repeat(3,minmax(0,1fr))}.nav-label{grid-column:1/-1}.sidebar-footer{display:none}.topbar{position:static;padding:14px 16px}.content{padding:18px 16px 36px}.hero-grid,.health-grid,.form-grid,.form-grid.three,.connection-row{grid-template-columns:1fr}.test-row{grid-template-columns:1fr}.toolbar-status{margin-left:0;width:100%}.placeholder-grid{grid-template-columns:1fr}.result-fields{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
  <div class="brand"><div class="brand-title"><div class="brand-mark">P</div><span>paperless-local-ai</span></div><div class="brand-sub">Control Center</div></div>
  <div class="nav-group"><div class="nav-label">Control Center</div>
    <button class="nav-btn active" data-page="overview">Overview</button>
    <button class="nav-btn" data-page="app-settings">App Settings</button>
    <button class="nav-btn" data-page="classification">Classification</button>
  </div>
  <div class="sidebar-footer"><div class="status-line"><span class="dot"></span><strong id="sidebarMode">Loading…</strong></div><div class="mini" style="margin-top:8px">App __APP_VERSION__</div><div id="sidebarAppVersion" class="mini">App settings …</div><div id="sidebarModel" class="mini">Classification …</div></div>
</aside>
<main class="main">
<header class="topbar"><div><div class="page-title" id="topTitle">Overview</div><div class="page-subtitle" id="topSubtitle">System overview and current configuration</div></div><div class="top-actions"><span id="topStatus" class="pill">Loading…</span><span id="topModeStatus" class="pill">Loading…</span></div></header>
<div class="content">

<section class="page active" id="page-overview">
  <details class="section-help"><summary>About the Control Center</summary><div class="help-body">Configure connections, OCR, classification and tagging here. Prompt previews and model tests are read-only for the selected Paperless document. Deployment secrets and container-level settings remain outside this UI.</div></details>
  <div class="hero-grid">
    <div id="overviewPaperlessCard" class="card metric-card"><div class="metric-title">Paperless-ngx</div><div id="overviewPaperlessStatus" class="metric-value">Checking…</div><div id="overviewPaperlessDetail" class="metric-detail">Loading…</div></div>
    <div id="overviewOllamaCard" class="card metric-card"><div class="metric-title">Ollama</div><div id="overviewOllamaStatus" class="metric-value">Checking…</div><div id="overviewOllamaDetail" class="metric-detail">Loading…</div></div>
    <div id="overviewOcrCard" class="card metric-card"><div class="metric-title">OCR</div><div id="overviewOcrStatus" class="metric-value">Loading…</div><div id="overviewOcrDetail" class="metric-detail">Loading…</div></div>
    <div id="overviewTaggingCard" class="card metric-card"><div class="metric-title">Tagging</div><div id="overviewTaggingStatus" class="metric-value">Loading…</div><div id="overviewTaggingDetail" class="metric-detail">Loading…</div></div>
  </div>
  <div class="section-grid">
    <div class="card section"><h2>Pipeline</h2><p>Paperless remains the document system of record. paperless-local-ai improves scanned-page OCR, then applies local metadata automation.</p>
      <div class="flow">
        <div class="flow-row"><div class="flow-dot">1</div><div class="flow-copy"><div class="flow-title">Paperless import</div><div class="flow-desc">Paperless consumes the original and decides through OCRmyPDF which pages actually need OCR.</div></div></div>
        <div class="flow-row local"><div class="flow-dot">2</div><div class="flow-copy"><div class="flow-title">PaddleOCR for scanned pages</div><div class="flow-desc">Only pages that need OCR are sent to the local OCR service. Native-text pages are not sent to PaddleOCR.</div></div></div>
        <div class="flow-row"><div class="flow-dot">3</div><div class="flow-copy"><div class="flow-title">Metadata queue</div><div class="flow-desc">A Paperless Document Added workflow assigns the configured classification queue tag. The metadata worker picks up the document after import and OCR have finished.</div></div></div>
        <div class="flow-row local"><div class="flow-dot">4</div><div class="flow-copy"><div class="flow-title">Tag routing</div><div class="flow-desc">Hybrid tagging first checks reviewed Paperless documents for a high-confidence tag match. Otherwise the LLM decides tags; LLM direct always lets the model decide.</div></div></div>
        <div class="flow-row local"><div class="flow-dot">5</div><div class="flow-copy"><div class="flow-title">One structured LLM request</div><div class="flow-desc">The model returns title, document type, date and the actual sender/issuer. It also returns tags when the selected tagging route needs an LLM decision.</div></div></div>
        <div class="flow-row local"><div class="flow-dot">6</div><div class="flow-copy"><div class="flow-title">Local sender resolution</div><div class="flow-desc">The extracted sender is matched conservatively to existing Paperless correspondents. If the optional Suggestions integration is configured, a plausible new sender can be exposed in Paperless Document Suggestions; no second LLM call is needed.</div></div></div>
        <div class="flow-row"><div class="flow-dot">7</div><div class="flow-copy"><div class="flow-title">Human review in Paperless</div><div class="flow-desc">Check the generated metadata, then remove the configured review tag. Only documents that have left the review, queue and error tags become trusted Hybrid history.</div></div></div>
      </div>
    </div>
    <div class="card section"><h2>Current configuration</h2><div style="margin-top:12px">
      <div class="kv"><span>Metadata writes</span><strong id="overviewMetadataWrites">Loading…</strong></div>
      <div class="kv"><span>Classification model</span><span id="overviewClassification">Loading…</span></div>
      <div class="kv"><span>Context window</span><span id="overviewContext">Loading…</span></div>
      <div class="kv"><span>Tagging strategy</span><span id="overviewTaggingConfig">Loading…</span></div>
      <div class="kv"><span>PaddleOCR model</span><span id="overviewOcrConfig">Loading…</span></div>
      <div class="kv"><span>Maximum OCR image side</span><span id="overviewOcrImageSize">Loading…</span></div>
    </div></div>
  </div>
</section>

<section class="page" id="page-classification">
  <div class="page-head"><div><h1>Document classification</h1><p>Configure the LLM request for title, document type, date and sender. Tag selection follows the strategy under Tagging; sender names are resolved against Paperless after the model call.</p></div><div id="classConfigStatus" class="config-badge">Loading…</div></div>
  <div class="toolbar"><button id="validateBtn" class="btn">Check configuration</button><button id="saveBtn" class="btn primary">Save changes</button><span id="saveStatus" class="toolbar-status">Saved configuration loaded.</span></div>
  <details class="section-help"><summary>What do Check and Save do?</summary><div class="help-body"><strong>Check configuration</strong> validates the visible draft without saving. <strong>Save changes</strong> creates a new version used by the next automatic classification job. No restart is required.</div></details>
  <div class="tabs" data-tabs="classification">
    <button class="tab active" data-tab="class-test">Test</button><button class="tab" data-tab="class-tagging">Tagging</button><button class="tab" data-tab="class-prompt">Prompt</button><button class="tab" data-tab="class-output">Output &amp; allowed values</button><button class="tab" data-tab="class-settings">Settings</button><button class="tab" data-tab="class-history">History</button>
  </div>

  <div class="tab-page active" id="class-test">
    <div class="action-note"><span>i</span><div><strong>Safe test with a real document.</strong> Preview shows the exact routing decision and prompts without calling Ollama. Run model test additionally performs the real structured request. Neither action changes the selected Paperless document or creates a correspondent suggestion.</div></div>
    <div class="card panel"><div class="test-row"><div class="field"><label>Paperless document ID</label><input id="docId" class="mono" type="number" min="1" placeholder="e.g. 123"><div class="field-help">Numeric ID from the Paperless document URL, e.g. <code>/documents/123/details</code>.</div></div><button id="previewBtn" class="btn">Preview prompts</button><button id="testBtn" class="btn primary">Run model test</button><div class="mini">CPU-only model tests can take tens of seconds to several minutes depending on prompt size. OCR and LLM inference share one resource lock, so a test may also wait for another heavy AI task.</div></div><div id="testStatus" class="status-box" style="margin-top:12px">Ready for prompt preview or model test.</div></div>
    <div class="result">
      <div class="card panel primary-result"><h3>Classification result</h3><p class="mini">Shows the final result after history routing and local correspondent resolution. Raw details remain below.</p><div id="classificationResultHuman" class="result-summary"><span class="mini">Run a model test to see the classification result.</span></div></div>
      <div class="card panel"><h3>Tagging route</h3><p class="mini">Explains whether the tag came from reviewed history or from the LLM.</p><pre id="taggingPreview" class="preview">Run Preview prompts or Run model test to populate this section.</pre></div>
      <div class="card panel"><h3>Request details</h3><pre id="previewMeta" class="preview">Run Preview prompts or Run model test to populate this section.</pre></div>
      <div class="card panel"><h3>System message sent to the model</h3><pre id="systemPreview" class="preview">Run Preview prompts or Run model test to populate this section.</pre></div>
      <div class="card panel"><h3>User message sent to the model</h3><pre id="userPreview" class="preview">Run Preview prompts or Run model test to populate this section.</pre></div>
      <div class="card panel" style="grid-column:1/-1"><details class="section-help" style="margin:0"><summary>Technical model result</summary><div class="help-body"><pre id="testResult" class="preview"></pre></div></details></div>
    </div>
  </div>

  <div class="tab-page" id="class-tagging">
    <details class="section-help"><summary>How tagging works</summary><div class="help-body"><strong>Hybrid tagging</strong> combines reviewed-document similarity with an LLM fallback. <strong>Tag guidance</strong> is separate: it describes your filing rules only when the LLM chooses tags. <a href="__TAGGING_DOCS_URL__" target="_blank" rel="noreferrer">Read the tagging design on GitHub.</a></div></details>

    <div class="card panel"><h3>Tagging strategy</h3><p class="mini">Choose how content tags are decided. Title, document type, date and sender still use the configured LLM.</p>
      <div class="strategy-grid">
        <label class="strategy-card"><div class="strategy-head"><div class="strategy-title"><input type="radio" name="taggingMode" value="history_assisted"><span>Hybrid tagging</span></div><span class="badge-rec">Recommended for small models</span></div><div class="strategy-copy">Compares documents with reviewed examples and reuses a tag only when similarity and neighbor agreement are strong. Otherwise the LLM decides using Tag Guidance and relevant examples.</div><div class="strategy-best"><strong>Best fit:</strong> compact local models, including the 4B reference model. · <a href="__TAGGING_DOCS_URL__#hybrid-tagging" target="_blank" rel="noreferrer">How Hybrid tagging works</a></div></label>
        <label class="strategy-card"><div class="strategy-head"><div class="strategy-title"><input type="radio" name="taggingMode" value="llm_only"><span>LLM direct</span></div><span class="badge-model">For more capable models</span></div><div class="strategy-copy">The configured LLM chooses tags directly for every document. Reviewed examples are not used for routing or prompt examples.</div><div class="strategy-best"><strong>Best fit:</strong> larger or more capable models that map documents to your taxonomy reliably on their own.</div></label>
      </div>
      <div class="separate-note"><strong>Why is Hybrid tagging recommended for small models?</strong> Compact models can understand a document while still applying a personal taxonomy inconsistently. Hybrid tagging reuses reviewed decisions only behind a strict evidence gate and sends uncertain cases to the LLM. <a href="__TAGGING_DOCS_URL__#why-hybrid-tagging-is-the-default" target="_blank" rel="noreferrer">Technical rationale</a>.</div>
    </div>

    <div class="card panel"><div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap"><div><h3 style="margin-bottom:4px">History health</h3><p class="mini" style="margin:0">Built from documents whose configured review tag has been removed after human review. Documents still carrying the classification queue or error tag are excluded. The index checks for changes at most every five minutes when used.</p></div><button id="taggingRefreshBtn" class="btn">Refresh reviewed history</button></div><div id="historyState" class="status-box" style="margin-top:12px">Loading history status…</div>
      <div class="health-grid"><div class="health-metric"><span>Reviewed documents</span><strong id="historyDocs">—</strong></div><div class="health-metric"><span>Tags represented</span><strong id="historyTags">—</strong></div><div class="health-metric"><span>Retrospective history reuse</span><strong id="historyReuse">—</strong></div><div class="health-metric"><span>Potential inconsistencies</span><strong id="historyIssues">—</strong></div></div>
      <div class="mini" style="margin-top:10px"><strong>Retrospective history reuse</strong> is a leave-one-out check of reviewed documents, not a prediction of future accuracy.</div>
      <div class="mini" id="historyUpdated" style="margin-top:6px">Last updated: —</div>
      <details class="section-help" style="margin-top:14px"><summary>History depth by tag</summary><div class="help-body"><p style="margin-top:0"><strong>History depth measures available reviewed examples, not accuracy.</strong> More examples make recurring patterns more likely to be represented, but do not guarantee a confident match.</p><p><strong>No history:</strong> 0 · <strong>Very limited:</strong> 1 · <strong>Limited:</strong> 2–4 · <strong>Good:</strong> 5–9 · <strong>Strong:</strong> 10+</p><div id="historyTagTable">Loading…</div></div></details>
      <details class="section-help"><summary>Potential tag inconsistencies</summary><div class="help-body"><p style="margin-top:0"><strong>This is a review hint, not an error detector.</strong> It shows groups of at least three reviewed documents whose full text is strongly similar but whose current leaf-tag assignments differ. Similar documents can legitimately require different tags, and these findings never change existing tags automatically.</p><details class="section-help"><summary>How is this detected?</summary><div class="help-body">The diagnostic uses the same full-text word + character TF-IDF representation as Hybrid retrieval. It uses complete-linkage clustering with a minimum within-group similarity of 0.50 and shows a group only when multiple leaf-tag assignments are present.</div></details><div id="historyInconsistencies">Loading…</div></div></details>
    </div>

    <div class="card panel"><h3>Tag guidance</h3><p class="mini">Optional descriptions for how <strong>the LLM</strong> should interpret each current Paperless tag. Guidance is supplied on Hybrid fallback and LLM direct routes. A confident Hybrid match does not send Tag Guidance to the model.</p><div class="separate-note">Fields are generated from current Paperless tags and stored by tag ID, so a renamed tag keeps its guidance. Empty fields add nothing to the Tagging prompt.</div><div id="tagGuidanceList" class="guidance-list"><span class="mini">Loading Paperless tags…</span></div></div>
  </div>

  <div class="tab-page" id="class-prompt">
    <details class="section-help"><summary>What is edited here?</summary><div class="help-body">All model instructions are editable. <strong>System</strong> and <strong>Base classification</strong> are always sent. The <strong>Tagging prompt</strong> is appended only when the LLM is responsible for tags. On a confident Hybrid match the Tagging prompt and the <code>tags</code> schema field are omitted entirely. Preview shows the exact final request.</div></details>
    <div class="card panel" style="margin-bottom:14px"><div class="form-grid" style="align-items:end"><div class="field"><label>Prompt preset</label><select id="classPromptPreset"></select></div><div><button id="classLoadPresetBtn" class="btn">Load preset into draft</button><div class="field-help">Replaces all three visible prompt fields in the draft. Save to activate.</div></div></div></div>
    <div class="split"><div class="card panel"><div class="field"><label>System prompt</label><textarea id="systemPrompt"></textarea></div></div><div class="card panel"><div class="field"><label>Base classification prompt</label><textarea id="classificationTemplate"></textarea></div></div></div>
    <div class="card panel" style="margin-top:14px"><div class="field"><label>Tagging prompt</label><textarea id="taggingPrompt"></textarea><div class="field-help">Used only when the LLM chooses tags. Hybrid fallback can inject Tag Guidance and relevant reviewed examples through placeholders. <a href="__TAGGING_DOCS_URL__#editable-prompt-composition" target="_blank" rel="noreferrer">How prompt composition works</a>.</div></div></div>
    <div class="card panel" style="margin-top:14px"><h3>Available placeholders</h3><p class="mini"><code>{{DOCUMENT_TEXT}}</code> is required in the Base classification prompt. Tag-specific placeholders belong in the Tagging prompt so a confident Hybrid route can omit tagging completely.</p><div id="placeholders" class="placeholder-grid"></div></div>
  </div>

  <div class="tab-page" id="class-output">
    <details class="section-help"><summary>What is shown here?</summary><div class="help-body">The structured schema is generated for each request. Document type and LLM-selected tags are constrained to current Paperless values. Correspondent is free text because the application resolves the extracted sender afterwards. A confident Hybrid route omits the Tagging prompt and the <code>tags</code> schema property entirely because the reviewed tag is already known.</div></details>
    <div class="split"><div class="card panel"><h3>Output schema</h3><pre id="schemaPreview" class="preview">Run Preview prompts or Run model test to populate this section.</pre></div><div class="card panel"><h3>Current Paperless taxonomy</h3><pre id="taxonomyPreview" class="preview">Run Preview prompts or Run model test to populate this section.</pre></div></div>
  </div>

  <div class="tab-page" id="class-settings">
    <details class="section-help"><summary>About these settings</summary><div class="help-body">These settings control the one classification LLM request. The tagging strategy and per-tag guidance are configured separately under Tagging.</div></details>
    <div class="card panel"><h3>Model and document input</h3><div class="form-grid three"><div class="field"><label>Ollama model</label><input id="model"><div class="field-help">Exact name of a model already installed in Ollama, e.g. qwen3.5:4b.</div></div><div class="field"><label>Context window</label><input id="numCtx" type="number"><div class="field-help">Maximum context available to Ollama. Larger values use more RAM and allow larger prompts; actual runtime mainly follows the prompt tokens used.</div></div><div class="field"><label>Document text limit (characters)</label><input id="contentLimit" type="number"><div class="field-help">Maximum Paperless document text sent to the LLM. Longer text is truncated using the beginning/end ratio below.</div></div><div class="field"><label>Maximum LLM tags</label><input id="maxTags" type="number" min="1" max="10"><div class="field-help">Used only when the LLM is responsible for the tag decision.</div></div></div></div>
    <details class="section-help" style="margin-top:14px"><summary>Advanced model settings</summary><div class="help-body"><div class="form-grid three"><div class="field"><label>Maximum output tokens</label><input id="numPredict" type="number"><div class="field-help">Maximum size of the generated structured response. This does not limit input or document text.</div></div><div class="field"><label>Temperature</label><input id="temperature" type="number" min="0" max="2" step="0.05"><div class="field-help">Controls output randomness. The CPU reference configuration uses 0.</div></div><div class="field"><label>Thinking</label><select id="think"><option value="false">Off</option><option value="true">On</option></select><div class="field-help">Enables model thinking when supported and can substantially increase latency.</div></div><div class="field"><label>Keep alive</label><input id="keepAlive"><div class="field-help">Ollama request keep-alive hint. The metadata worker explicitly unloads the model after a completed classification job.</div></div><div class="field"><label>Document text kept from beginning</label><input id="headRatio" type="number" min="0.5" max="0.95" step="0.05"><div class="field-help">Used only when document text exceeds the limit. 0.75 keeps 75% from the beginning and 25% from the end.</div></div><div class="field"><label>Request timeout (seconds)</label><input id="ollamaTimeout" type="number"><div class="field-help">Maximum time to wait for the Ollama classification request.</div></div></div></div></details>
  </div>

  <div class="tab-page" id="class-history"><details class="section-help"><summary>What is versioned?</summary><div class="help-body">Prompts, model settings, tagging strategy and per-tag guidance are saved together. Restoring an older version creates a new current version; existing history remains intact.</div></details><div class="card panel"><div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><h3 style="margin:0">Saved versions</h3><button id="historyRefresh" class="btn">Reload saved versions</button></div><div id="historyList"></div></div></div>
</section>

<section class="page" id="page-app-settings">
  <div class="page-head"><div><h1>App Settings</h1><p>Configure Paperless and Ollama connections, workflow tags, OCR and runtime behavior. These settings are versioned and hot-reloaded; ports, volumes, resource limits and secrets remain deployment settings.</p></div><div id="appConfigStatus" class="config-badge">Loading…</div></div>
  <div class="toolbar"><button id="appValidateBtn" class="btn">Check configuration</button><button id="appSaveBtn" class="btn primary">Save changes</button><span id="appSaveStatus" class="toolbar-status">Saved configuration loaded.</span></div>
  <div class="tabs" data-tabs="app"><button class="tab active" data-tab="app-connections">Connections</button><button class="tab" data-tab="app-workflow">Pipeline &amp; Tags</button><button class="tab" data-tab="app-ocr">OCR</button><button class="tab" data-tab="app-runtime">Runtime</button><button class="tab" data-tab="app-history">History</button></div>

  <div class="tab-page active" id="app-connections"><details class="section-help"><summary>About connections</summary><div class="help-body">URLs must be reachable from the app containers. The Paperless token is a deployment secret and is never shown or stored in versioned UI configuration.</div></details><div class="connection-row"><div class="card connection"><h3>Paperless-ngx</h3><div class="field"><label>Paperless URL</label><input id="appPaperlessUrl"></div><div class="field" style="margin-top:12px"><label>API token</label><div id="appTokenStatus" class="status-box">Loading…</div></div></div><div class="card connection"><h3>Ollama</h3><div class="field"><label>Ollama URL</label><input id="appOllamaUrl"></div></div></div><div class="card panel" style="margin-top:14px"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button id="appConnectionTestBtn" class="btn good">Test connections with current draft</button><div id="appConnectionStatus" class="status-box" style="flex:1">Not tested yet.</div></div></div></div>

  <div class="tab-page" id="app-workflow"><details class="section-help"><summary>Pipeline &amp; tags</summary><div class="help-body">These names must match existing Paperless tags exactly. The classification queue starts metadata processing; the error tag marks failures; the review tag marks documents awaiting human review and is the Hybrid trust boundary. The review tag can have any name. The recommended Paperless setup marks the chosen review tag as an <strong>Inbox tag</strong> so Paperless adds it on import. <a href="__PAPERLESS_SETUP_DOCS_URL__#2-metadata-and-review-tags" target="_blank" rel="noreferrer">Paperless setup</a>.</div></details><div class="card panel"><div class="form-grid three"><div class="field"><label>Classification queue tag</label><input id="appLlmQueueTag"><div class="field-help">Must match an existing Paperless tag exactly.</div></div><div class="field"><label>Classification error tag</label><input id="appLlmErrorTag"><div class="field-help">Must match an existing Paperless tag exactly.</div></div><div class="field"><label>Review tag</label><input id="appReviewTag"><div class="field-help">Keep this tag on the document until human review is complete. Removing it makes the document eligible for trusted Hybrid history once queue/error tags are also gone.</div></div><div class="field"><label>Additional tags excluded from classification</label><input id="appExtraExcludedTags"><div class="field-help">Comma-separated. These tags are not offered as content-tag candidates and are preserved during metadata write-back, e.g. TODO.</div></div></div></div></div>

  <div class="tab-page" id="app-ocr"><details class="section-help"><summary>OCR behavior</summary><div class="help-body">These settings affect scanned-page OCR only. The original and archive PDFs are never resized by this setting. Maximum OCR image side is the main OCR memory control; automatic retries recover from temporary OCR process/service failures.</div></details><div class="card panel"><div class="form-grid three"><div class="field"><label>OCR language</label><input id="appOcrLanguage" list="ocrLanguageOptions"><datalist id="ocrLanguageOptions"><option value="de">German</option><option value="en">English</option><option value="it">Italian</option><option value="fr">French</option><option value="es">Spanish</option><option value="nl">Dutch</option><option value="pl">Polish</option><option value="pt">Portuguese</option><option value="japan">Japanese</option></datalist></div><input id="appOcrVersion" type="hidden"><div class="field"><label>PaddleOCR model</label><select id="appOcrModelProfile"><option value="medium">PP-OCRv6 Medium — Highest quality · Recommended</option><option value="small">PP-OCRv6 Small — Lower inference cost</option><option value="tiny">PP-OCRv6 Tiny — Lowest inference cost · Lower accuracy</option></select></div><div class="field"><label>Maximum OCR image side</label><input id="appOcrMaxSidePixels" type="number" min="2000" max="4000" step="100"><div class="field-help">Longest side of the temporary OCR raster. Default 3000 px. Lower this first if OCR is memory-limited; the original/archive document is unchanged.</div></div><div class="field"><label>Inference device</label><input id="appOcrDevice"><div class="field-help">CPU is the tested reference configuration; other devices are currently unverified.</div></div><div class="field" style="grid-column:1/-1"><label>Automatic OCR retries</label><input id="appOcrRetryDelays" class="mono" placeholder="15, 60, 300, 600"><div class="field-help">Delay before each retry in seconds. Empty disables automatic retries.</div></div></div></div>
    <div class="card panel" style="margin-top:14px"><div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap"><div><h3 style="margin-bottom:4px">OCR recovery</h3><p class="mini" style="margin:0">Temporary failures are retried automatically according to the configured schedule.</p></div><div><span id="ocrRecoveryPill" class="pill">Loading…</span> <button id="ocrRetryNowBtn" class="btn" style="display:none">Retry now</button></div></div><div id="ocrRecoverySummary" class="status-box" style="margin-top:12px">Loading…</div><details id="ocrRecoveryTechnical" class="section-help" style="display:none;margin-top:10px"><summary>Technical details</summary><div id="ocrRecoveryTechnicalText" class="help-body"></div></details><details class="section-help" style="margin-top:12px"><summary>Recent OCR failures (<span id="ocrFailureCount">0</span>)</summary><div class="help-body"><div id="ocrFailureList">No OCR failures recorded.</div></div></details></div>
  </div>

  <div class="tab-page" id="app-runtime"><details class="section-help"><summary>Runtime behavior</summary><div class="help-body"><strong>Dry run</strong> is an optional test mode. Classification still runs, but document metadata and persistent new-correspondent review records are not written. Technical workflow/error tags may still change. OCR remains part of Paperless import and is unaffected.</div></details><div class="card panel"><h3>Metadata writes</h3><div class="field"><label>Dry run (no metadata writes)</label><select id="appDryRun"><option value="false">Off — write metadata to Paperless</option><option value="true">On — do not write metadata</option></select><div class="field-help">Default is Off. Enable Dry Run temporarily when you want to inspect classification behavior without writing document metadata.</div></div></div><details class="section-help" style="margin-top:14px"><summary>Advanced worker settings</summary><div class="help-body"><div class="form-grid"><div class="field"><label>Metadata queue polling interval</label><input id="appPollInterval" type="number"><div class="field-help">Seconds between checks for documents carrying the classification queue tag.</div></div><div class="field"><label>Suggestion record cleanup interval</label><input id="appReviewPruneInterval" type="number"><div class="field-help">Seconds between cleanup checks for stored new-correspondent review records after documents leave the configured review tag.</div></div></div></div></details></div>

  <div class="tab-page" id="app-history"><details class="section-help"><summary>Versioned app settings</summary><div class="help-body">Every save keeps the previous state in history. Restoring creates a new current version.</div></details><div class="card panel"><div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><h3 style="margin:0">Saved versions</h3><button id="appHistoryRefresh" class="btn">Reload saved versions</button></div><div id="appHistoryList"></div></div></div>
</section>

</div></main></div>
<script>
let currentConfig=null,currentAppConfig=null,currentTaxonomy=[],currentHistoryStatus=null;let classPromptPresets={};
const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
async function api(path,opts={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});const t=await r.text();let data;try{data=JSON.parse(t)}catch{data={error:t}}if(!r.ok)throw new Error(data.error||`${r.status} ${r.statusText}`);return data}
function setStatus(id,msg,ok=true){const el=$(id);if(!el)return;el.textContent=msg;el.classList.toggle('good-text',ok);el.classList.toggle('bad-text',!ok);el.classList.toggle('good',ok&&el.classList.contains('status-box'));el.classList.toggle('bad',!ok&&el.classList.contains('status-box'))}
function markUnsaved(id='saveStatus'){const el=$(id);if(el){el.textContent='Unsaved changes.';el.className='toolbar-status warn-text'}}
function selectedTaggingMode(){return document.querySelector('input[name="taggingMode"]:checked')?.value||currentConfig?.tagging_mode||'history_assisted'}
function tagGuidanceDraft(){const inputs=[...document.querySelectorAll('.tag-guidance-input')];if(!inputs.length)return {...(currentConfig?.tag_guidance||{})};const out={};inputs.forEach(el=>{const v=el.value.trim();if(v)out[el.dataset.tagId]=v});return out}
function draft(){return {version:currentConfig?.version||1,updated_at:currentConfig?.updated_at||null,system_prompt:$('systemPrompt').value,classification_template:$('classificationTemplate').value,tagging_prompt:$('taggingPrompt').value,model:$('model').value.trim(),num_ctx:Number($('numCtx').value),num_predict:Number($('numPredict').value),temperature:Number($('temperature').value),think:$('think').value==='true',keep_alive:/^-?\d+(\.\d+)?$/.test($('keepAlive').value.trim())?Number($('keepAlive').value):$('keepAlive').value,content_char_limit:Number($('contentLimit').value),content_head_ratio:Number($('headRatio').value),max_tags:Number($('maxTags').value),ollama_timeout_seconds:Number($('ollamaTimeout').value),tagging_mode:selectedTaggingMode(),tag_guidance:tagGuidanceDraft()}}
function parseRetryDelays(value){const raw=value.trim();if(!raw)return[];const parts=raw.split(',').map(x=>x.trim());if(parts.some(x=>!/^\d+$/.test(x)))throw new Error('Automatic OCR retries must be whole-number seconds separated by commas.');return parts.map(Number)}
function appDraft(){return {version:currentAppConfig?.version||1,updated_at:currentAppConfig?.updated_at||null,connections:{paperless_url:$('appPaperlessUrl').value.trim(),ollama_url:$('appOllamaUrl').value.trim()},workflow:{llm_queue_tag:$('appLlmQueueTag').value.trim(),llm_error_tag:$('appLlmErrorTag').value.trim(),review_tag:$('appReviewTag').value.trim(),extra_excluded_tags:$('appExtraExcludedTags').value.split(',').map(x=>x.trim()).filter(Boolean)},ocr:{language:$('appOcrLanguage').value.trim(),version:$('appOcrVersion').value.trim(),model_profile:$('appOcrModelProfile').value,max_side_pixels:Number($('appOcrMaxSidePixels').value),retry_delays_seconds:parseRetryDelays($('appOcrRetryDelays').value),device:$('appOcrDevice').value.trim()},runtime:{poll_interval_seconds:Number($('appPollInterval').value),review_prune_interval_seconds:Number($('appReviewPruneInterval').value),dry_run:$('appDryRun').value==='true'}}}
function fill(c){currentConfig=c;$('systemPrompt').value=c.system_prompt;$('classificationTemplate').value=c.classification_template;$('taggingPrompt').value=c.tagging_prompt;$('model').value=c.model;$('numCtx').value=c.num_ctx;$('numPredict').value=c.num_predict;$('temperature').value=c.temperature;$('think').value=String(c.think);$('keepAlive').value=c.keep_alive;$('contentLimit').value=c.content_char_limit;$('headRatio').value=c.content_head_ratio;$('maxTags').value=c.max_tags;$('ollamaTimeout').value=c.ollama_timeout_seconds;document.querySelectorAll('input[name="taggingMode"]').forEach(x=>x.checked=x.value===(c.tagging_mode||'history_assisted'));$('classConfigStatus').textContent=`Classification settings v${c.version} · ${c.model}`;renderTagGuidance();updateOverview()}
function appFill(c,tokenConfigured){currentAppConfig=c;$('appPaperlessUrl').value=c.connections.paperless_url;$('appOllamaUrl').value=c.connections.ollama_url;$('appLlmQueueTag').value=c.workflow.llm_queue_tag;$('appLlmErrorTag').value=c.workflow.llm_error_tag;$('appReviewTag').value=c.workflow.review_tag;$('appExtraExcludedTags').value=(c.workflow.extra_excluded_tags||[]).join(', ');$('appOcrLanguage').value=c.ocr.language;$('appOcrVersion').value=c.ocr.version;$('appOcrModelProfile').value=c.ocr.model_profile||'medium';$('appOcrMaxSidePixels').value=c.ocr.max_side_pixels||3000;$('appOcrRetryDelays').value=(c.ocr.retry_delays_seconds||[]).join(', ');$('appOcrDevice').value=c.ocr.device;$('appPollInterval').value=c.runtime.poll_interval_seconds;$('appReviewPruneInterval').value=c.runtime.review_prune_interval_seconds;$('appDryRun').value=String(c.runtime.dry_run);$('appConfigStatus').textContent=`App settings v${c.version} · ${c.runtime.dry_run?'metadata dry run':'metadata writes enabled'}`;$('appTokenStatus').textContent=tokenConfigured?'API token is configured in the deployment environment.':'API token is missing from the deployment environment.';$('appTokenStatus').className='status-box '+(tokenConfigured?'good':'bad');updateOverview()}
function updateOverview(){if(currentAppConfig){const dry=currentAppConfig.runtime.dry_run;$('overviewMetadataWrites').textContent=dry?'Dry run':'Enabled';$('overviewMetadataWrites').className=dry?'warn-text':'good-text';$('topModeStatus').textContent=dry?'Metadata dry run':'Metadata writes enabled';$('topModeStatus').className='pill '+(dry?'warn':'good');$('sidebarMode').textContent=dry?'Metadata dry run':'Metadata writes enabled';$('sidebarAppVersion').textContent=`App settings v${currentAppConfig.version}`;$('overviewPaperlessDetail').textContent=currentAppConfig.connections.paperless_url;$('overviewOllamaDetail').textContent=currentAppConfig.connections.ollama_url;const p=currentAppConfig.ocr.model_profile||'medium';$('overviewOcrConfig').textContent=`${currentAppConfig.ocr.version} ${p[0].toUpperCase()+p.slice(1)}`;$('overviewOcrImageSize').textContent=`${currentAppConfig.ocr.max_side_pixels||3000} px`;$('overviewOcrDetail').textContent=`${currentAppConfig.ocr.version} ${p} · ${currentAppConfig.ocr.language} · ${currentAppConfig.ocr.device.toUpperCase()}`}
if(currentConfig){$('overviewClassification').textContent=currentConfig.model;$('overviewContext').textContent=`${currentConfig.num_ctx} tokens`;const hybrid=currentConfig.tagging_mode==='history_assisted';const label=hybrid?'Hybrid tagging':'LLM direct';$('overviewTaggingConfig').textContent=label;$('overviewTaggingStatus').textContent=label;$('overviewTaggingStatus').className='metric-value '+(hybrid?'good-text':'');$('overviewTaggingDetail').textContent=hybrid?(currentHistoryStatus?`${currentHistoryStatus.reviewed_documents} reviewed docs · ${currentHistoryStatus.estimated_reuse_percent}% retrospective reuse`:'Reviewed-example gate + LLM fallback'):'LLM decides every tag';$('sidebarModel').textContent=`Classification · ${currentConfig.model}`}}
function renderPromptPresetOptions(){const s=$('classPromptPreset');s.innerHTML='<option value="">Select a preset…</option>'+Object.entries(classPromptPresets||{}).map(([k,p])=>`<option value="${esc(k)}">${esc(p.label||k)}</option>`).join('')}
function loadClassPromptPreset(){const p=classPromptPresets[$('classPromptPreset').value];if(!p)return;$('systemPrompt').value=p.system_prompt;$('classificationTemplate').value=p.classification_template;$('taggingPrompt').value=p.tagging_prompt;markUnsaved()}
function renderTagGuidance(){const el=$('tagGuidanceList');if(!el)return;if(!currentTaxonomy.length){el.innerHTML='<span class="mini">No current Paperless tags loaded yet.</span>';return}const guidance=currentConfig?.tag_guidance||{};const names=Object.fromEntries(currentTaxonomy.map(t=>[t.id,t.name]));el.innerHTML=currentTaxonomy.map(t=>{const value=guidance[String(t.id)]||'';const parent=t.parent?` <span class="mini">· child of ${esc(names[t.parent]||'another tag')}</span>`:'';return `<details class="guidance-item"><summary><span><strong>${esc(t.name)}</strong>${parent}</span><span class="guidance-state">${value?'Guidance set':'Optional'}</span></summary><div class="guidance-body"><textarea class="tag-guidance-input" data-tag-id="${t.id}" placeholder="Describe when the LLM should use this tag and how it differs from similar tags…">${esc(value)}</textarea></div></details>`}).join('');el.querySelectorAll('.tag-guidance-input').forEach(x=>x.addEventListener('input',()=>markUnsaved()))}
function renderHistoryHealth(h){currentHistoryStatus=h;const state=$('historyState');const strategy=selectedTaggingMode();if(h.status==='Error'){state.textContent=`History could not be refreshed: ${h.last_error||'unknown error'}`;state.className='status-box bad'}else{state.textContent=(strategy==='llm_only'?'History is not used by the current LLM direct strategy. ':'')+(h.status==='Ready'?'History index is ready. Strong evidence can be reused by Hybrid tagging.':'There is not enough reviewed history yet. Hybrid tagging will use the LLM fallback.');state.className='status-box '+(h.status==='Ready'?'good':'')}
$('historyDocs').textContent=h.reviewed_documents??0;$('historyTags').textContent=`${h.tags_represented??0} / ${h.eligible_tags??0}`;const sample=h.estimated_reuse_sample_size||0;$('historyReuse').textContent=sample?`${h.estimated_reuse_percent}%`:'—';$('historyIssues').textContent=h.potential_inconsistency_count??0;$('historyUpdated').textContent=`Last updated: ${h.last_updated?new Date(h.last_updated).toLocaleString():'not built'}${sample&&sample!==(h.reviewed_documents||0)?` · reuse estimate sampled from ${sample} documents`:''}`;
const rows=h.per_tag||[];$('historyTagTable').innerHTML=rows.length?`<table class=\"tag-table\"><thead><tr><th>Tag</th><th>Reviewed docs</th><th>History depth</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${r.count}</td><td>${esc(r.status)}</td></tr>`).join('')}</tbody></table>`:'<span class=\"mini\">No reviewed tags yet.</span>';
const issues=h.potential_inconsistencies||[];$('historyInconsistencies').innerHTML=issues.length?issues.map((g,i)=>`<div class=\"inconsistency\"><strong>Review hint · ${g.documents} similar reviewed documents · ${(g.tag_sets||[]).length} tag sets</strong><div class=\"inconsistency-tags\">${(g.tag_sets||[]).map(s=>`<span class=\"tag-chip\">${esc((s.tags||[]).join(' + ')||'No content tag')} · ${s.count}</span>`).join('')}</div><ul class=\"doc-list\">${(g.examples||[]).slice(0,10).map(d=>`<li>ID ${d.id} · ${esc(d.title)} — ${esc((d.tags||[]).join(' + ')||'No content tag')}</li>`).join('')}</ul>${g.truncated?'<div class=\"mini\">More documents are part of this group.</div>':''}</div>`).join(''):'<span class=\"mini\">No potential inconsistencies detected by the current history diagnostic.</span>';updateOverview()}
async function loadTagging(force=false){try{const r=await api(force?'/api/tagging/refresh':'/api/tagging/state',{method:force?'POST':'GET',body:force?'{}':undefined});currentTaxonomy=r.tags||[];renderTagGuidance();renderHistoryHealth(r.history||{});return r}catch(e){$('historyState').textContent=e.message;$('historyState').className='status-box bad';throw e}}
function renderClassificationResult(r){const el=$('classificationResultHuman');const s=r?.suggestion||{};const errors=r?.validation_errors||[];const tags=Array.isArray(s.tags)?s.tags.join(', '):'—';const routeRaw=r?.tagging?.route||'—';const corrRaw=r?.correspondent_resolution?.status||'—';const routeLabels={history_match:'From reviewed history',llm_fallback:'LLM fallback',llm_only:'LLM direct'};const corrLabels={existing_exact:'Matched existing correspondent',existing_fuzzy:'Matched existing correspondent · fuzzy match',new_suggestion:'New sender candidate · not auto-created',empty:'No reliable sender found',skipped_main_invalid:'Not resolved because classification was invalid'};const route=routeLabels[routeRaw]||routeRaw;const corr=corrLabels[corrRaw]||corrRaw;el.innerHTML=`<div class="result-state ${errors.length?'bad-text':'good-text'}">${errors.length?'Validation failed':'Valid result'}</div><div class="result-fields"><div class="result-field"><span>Title</span><strong>${esc(s.title||'—')}</strong></div><div class="result-field"><span>Document type</span><strong>${esc(s.document_type||'—')}</strong></div><div class="result-field"><span>Sender / correspondent</span><strong>${esc(s.correspondent||r?.correspondent_resolution?.suggestion||'—')}</strong><div class="mini">${esc(corr)}</div></div><div class="result-field"><span>Tags</span><strong>${esc(tags||'—')}</strong><div class="mini">${esc(route)}</div></div><div class="result-field"><span>Date</span><strong>${esc(s.created||'—')}</strong></div></div>${errors.length?`<div class="mini bad-text" style="margin-top:9px">${esc(errors.join(' · '))}</div>`:''}`}
function formatHistoryDate(v){if(!v)return'';const d=new Date(v);return Number.isNaN(d.getTime())?v:d.toLocaleString()}
function renderHistory(items,id,restoreFn){$(id).innerHTML=items.length?items.map(x=>`<div class="history-item"><span class="config-badge">v${x.version??'?'}</span><span>${esc(x.summary||'Saved configuration')}</span><span class="mini">${esc(formatHistoryDate(x.updated_at||''))}</span><button class="btn" onclick="${restoreFn}('${esc(x.file)}')">Restore</button></div>`).join(''):'<p class="mini">No older saved version yet.</p>'}
function renderAppHistory(items){renderHistory(items,'appHistoryList','restoreAppHistory')}
function ocrGuidance(v){const t=String(v||'').toLowerCase();if(/out of memory|cannot allocate|bad_alloc/.test(t))return 'This looks memory-related. Try lowering Maximum OCR image side.';if(/language mismatch/.test(t))return 'Check that Paperless and paperless-local-ai use the same OCR language.';return ''}
function renderOcrRecovery(payload){const state=payload?.state||{status:'idle'},failures=payload?.failures||[],display=state.status==='idle'&&failures.length?'failed':state.status,labels={idle:'Ready',running:'OCR running',waiting:'Waiting to retry',failed:'Needs attention'},pill=$('ocrRecoveryPill'),retry=$('ocrRetryNowBtn');pill.textContent=labels[display]||display;pill.className='pill '+(display==='idle'?'good':display==='waiting'?'warn':display==='failed'?'bad':'');retry.style.display=state.status==='waiting'?'inline-block':'none';retry.dataset.requestId=state.request_id||'';retry.disabled=!!state.retry_now_requested;const hint=ocrGuidance(state.last_error);$('ocrRecoverySummary').textContent=state.status==='waiting'?`OCR was interrupted. Attempt ${state.attempt||1} of ${state.max_attempts||1} failed; the same page will retry automatically.`:state.status==='running'?`OCR is running. Attempt ${state.attempt||1} of ${state.max_attempts||1}.`:state.status==='failed'?`OCR could not recover automatically.${hint?' '+hint:''}`:failures.length?`OCR is ready, but ${failures.length} earlier failure${failures.length===1?' needs':'s need'} attention below.`:'OCR is ready. No action is needed.';$('ocrRecoveryTechnical').style.display=state.last_error?'block':'none';$('ocrRecoveryTechnicalText').textContent=state.last_error||'';$('ocrFailureCount').textContent=String(failures.length);$('ocrFailureList').innerHTML=failures.length?failures.map(f=>`<div class="failure-item"><div class="failure-head"><div><strong>${esc(f.source||'OCR page')}</strong><div class="mini">${esc(f.failed_at||'')} · ${f.attempts||1} attempts</div></div><button class="btn" onclick="dismissOcrFailure('${esc(f.id)}')">Dismiss</button></div><div class="mini" style="margin-top:6px">${esc(ocrGuidance(f.error)||'Automatic recovery could not complete this OCR job.')}</div></div>`).join(''):'<span class="mini">No OCR failures recorded.</span>'}
async function refreshOcrRecovery(){try{const h=await api('/api/app/ocr/health');renderOcrRecovery(h.recovery||{});const status=$('overviewOcrStatus');if(h.ok){status.textContent='Ready';status.className='metric-value good-text'}else{status.textContent='Unavailable';status.className='metric-value bad-text'}}catch(e){$('overviewOcrStatus').textContent='Unavailable';$('overviewOcrStatus').className='metric-value bad-text'}}
window.dismissOcrFailure=async id=>{if(!confirm('Dismiss this Control Center notice? This does not retry, modify or delete the document.'))return;await api('/api/app/ocr/failures/dismiss',{method:'POST',body:JSON.stringify({failure_id:id})});await refreshOcrRecovery()};
function applyConnectionResult(r){for(const [key,statusId,detailId] of [['paperless','overviewPaperlessStatus','overviewPaperlessDetail'],['ollama','overviewOllamaStatus','overviewOllamaDetail']]){const result=r[key],status=$(statusId);status.textContent=result?.ok?'Connected':'Connection error';status.className='metric-value '+(result?.ok?'good-text':'bad-text');const base=key==='paperless'?currentAppConfig?.connections?.paperless_url:currentAppConfig?.connections?.ollama_url;$(detailId).textContent=base||result?.detail||''}}
async function checkConnections(c){try{applyConnectionResult(await api('/api/app/connections/test',{method:'POST',body:JSON.stringify({config:c})}))}catch{}}
async function init(){try{const s=await api('/api/state');classPromptPresets=s.presets||{};renderPromptPresetOptions();fill(s.config);$('placeholders').innerHTML=Object.entries(s.placeholders).map(([k,v])=>`<div class="placeholder-item"><code>{{${esc(k)}}}</code><span>${esc(v)}</span></div>`).join('');await loadHistory();await loadTagging();$('topStatus').textContent='Control Center ready';$('topStatus').className='pill good'}catch(e){$('topStatus').textContent=e.message;$('topStatus').className='pill bad'}}
async function loadApp(){try{const r=await api('/api/app/state');appFill(r.config,r.token_configured);renderAppHistory(r.history||[]);checkConnections(r.config)}catch(e){setStatus('appSaveStatus',e.message,false)}}
$('classLoadPresetBtn').onclick=loadClassPromptPreset;for(const id of ['systemPrompt','classificationTemplate','taggingPrompt','model','numCtx','numPredict','temperature','think','keepAlive','contentLimit','headRatio','maxTags','ollamaTimeout']){$(id)?.addEventListener('input',()=>markUnsaved());$(id)?.addEventListener('change',()=>markUnsaved())}document.querySelectorAll('input[name="taggingMode"]').forEach(x=>x.addEventListener('change',()=>{markUnsaved();if(currentHistoryStatus)renderHistoryHealth(currentHistoryStatus)}));
for(const id of ['appPaperlessUrl','appOllamaUrl','appLlmQueueTag','appLlmErrorTag','appReviewTag','appExtraExcludedTags','appOcrLanguage','appOcrModelProfile','appOcrMaxSidePixels','appOcrRetryDelays','appOcrDevice','appPollInterval','appReviewPruneInterval','appDryRun']){$(id)?.addEventListener('input',()=>markUnsaved('appSaveStatus'));$(id)?.addEventListener('change',()=>markUnsaved('appSaveStatus'))}
$('validateBtn').onclick=async()=>{try{await api('/api/config/validate',{method:'POST',body:JSON.stringify({config:draft()})});setStatus('saveStatus','Configuration valid · not saved yet.')}catch(e){setStatus('saveStatus',e.message,false)}};$('saveBtn').onclick=async()=>{try{const r=await api('/api/config/save',{method:'POST',body:JSON.stringify({config:draft()})});fill(r.config);setStatus('saveStatus',`Saved · Classification settings v${r.config.version} are active from the next classification job.`);await loadHistory();await loadTagging()}catch(e){setStatus('saveStatus',e.message,false)}};
async function doPreview(run){const id=Number($('docId').value);if(!id){setStatus('testStatus','Enter a Paperless document ID.',false);return}setStatus('testStatus',run?'Model test running…':'Preparing routing and prompts…');try{const r=await api(run?'/api/test':'/api/preview',{method:'POST',body:JSON.stringify({document_id:id,config:draft()})});$('systemPreview').textContent=r.rendered.system_prompt;$('userPreview').textContent=r.rendered.user_prompt;$('schemaPreview').textContent=JSON.stringify(r.rendered.schema,null,2);$('taxonomyPreview').textContent=JSON.stringify(r.taxonomy,null,2);$('taggingPreview').textContent=JSON.stringify(r.tagging,null,2);$('previewMeta').textContent=JSON.stringify(r.meta,null,2);$('testResult').textContent=run?JSON.stringify({suggestion:r.suggestion,validation_errors:r.validation_errors,correspondent_resolution:r.correspondent_resolution,performance:r.performance},null,2):'';if(run)renderClassificationResult(r);setStatus('testStatus',run?'Model test complete · Paperless was not modified.':'Preview complete · the model was not called.')}catch(e){setStatus('testStatus',e.message,false)}}$('previewBtn').onclick=()=>doPreview(false);$('testBtn').onclick=()=>doPreview(true);$('taggingRefreshBtn').onclick=async()=>{setStatus('historyState','Refreshing reviewed history…');try{await loadTagging(true)}catch{}};
$('appValidateBtn').onclick=async()=>{try{await api('/api/app/validate',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appSaveStatus','Configuration valid · not saved yet.')}catch(e){setStatus('appSaveStatus',e.message,false)}};$('appSaveBtn').onclick=async()=>{try{const r=await api('/api/app/save',{method:'POST',body:JSON.stringify({config:appDraft()})});appFill(r.config,r.token_configured);setStatus('appSaveStatus',`Saved · App settings v${r.config.version} are active.`);renderAppHistory(r.history||[]);checkConnections(r.config);await loadTagging(true)}catch(e){setStatus('appSaveStatus',e.message,false)}};$('appConnectionTestBtn').onclick=async()=>{setStatus('appConnectionStatus','Testing connections…');try{const r=await api('/api/app/connections/test',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appConnectionStatus',`Paperless: ${r.paperless.ok?'OK':'ERROR'}${r.paperless.detail?' · '+r.paperless.detail:''}\nOllama: ${r.ollama.ok?'OK':'ERROR'}${r.ollama.detail?' · '+r.ollama.detail:''}`,r.paperless.ok&&r.ollama.ok);applyConnectionResult(r)}catch(e){setStatus('appConnectionStatus',e.message,false)}};$('ocrRetryNowBtn').onclick=async()=>{const id=$('ocrRetryNowBtn').dataset.requestId;if(!id)return;await api('/api/app/ocr/retry-now',{method:'POST',body:JSON.stringify({request_id:id})});await refreshOcrRecovery()};
async function loadHistory(){try{const r=await api('/api/history');renderHistory(r.items||[],'historyList','restoreHistory')}catch(e){$('historyList').textContent=e.message}}window.restoreHistory=async file=>{if(!confirm('Restore this classification version as a new current version?'))return;const r=await api('/api/history/restore',{method:'POST',body:JSON.stringify({file})});fill(r.config);await loadHistory();await loadTagging();setStatus('saveStatus',`Restored and saved as v${r.config.version}`)};$('historyRefresh').onclick=loadHistory;
async function refreshAppHistory(){const r=await api('/api/app/history');renderAppHistory(r.items||[])}window.restoreAppHistory=async file=>{if(!confirm('Restore these app settings as a new current version?'))return;const r=await api('/api/app/history/restore',{method:'POST',body:JSON.stringify({file})});appFill(r.config,r.token_configured);renderAppHistory(r.history||[]);await loadTagging(true)};$('appHistoryRefresh').onclick=()=>refreshAppHistory().catch(e=>setStatus('appSaveStatus',e.message,false));
const pageMeta={overview:['Overview','System overview and current configuration'],classification:['Classification','Local metadata and tag automation'],'app-settings':['App Settings','Connections, workflow, OCR and runtime']};function activatePage(page){if(!pageMeta[page])page='overview';document.querySelectorAll('.nav-btn').forEach(b=>b.classList.toggle('active',b.dataset.page===page));document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===`page-${page}`));$('topTitle').textContent=pageMeta[page][0];$('topSubtitle').textContent=pageMeta[page][1];try{localStorage.setItem('paperlessControlCenterPage',page)}catch{}}function activateTab(group,id){const nav=document.querySelector(`.tabs[data-tabs="${group}"]`),target=$(id);if(!nav||!target)return;nav.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===id));nav.closest('.page').querySelectorAll('.tab-page').forEach(x=>x.classList.toggle('active',x.id===id));try{localStorage.setItem(`paperlessControlCenterTab:${group}`,id)}catch{}}document.querySelectorAll('.nav-btn').forEach(b=>b.onclick=()=>activatePage(b.dataset.page));document.querySelectorAll('.tabs .tab').forEach(b=>b.onclick=()=>activateTab(b.closest('.tabs').dataset.tabs,b.dataset.tab));for(const [group,fallback] of [['classification','class-test'],['app','app-connections']]){let tab=fallback;try{tab=localStorage.getItem(`paperlessControlCenterTab:${group}`)||fallback}catch{}activateTab(group,tab)}let initialPage='overview';try{initialPage=localStorage.getItem('paperlessControlCenterPage')||initialPage}catch{}activatePage(initialPage);
init();loadApp();refreshOcrRecovery();setInterval(refreshOcrRecovery,5000);
</script>
</body></html>'''.replace("__TAGGING_DOCS_URL__", TAGGING_DOCS_URL).replace("__PAPERLESS_SETUP_DOCS_URL__", PAPERLESS_SETUP_DOCS_URL).replace("__APP_VERSION__", APP_VERSION)


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


def tagging_state(*, force=False):
    cfg = load_config()
    app_cfg = load_app_config()
    tax = client.taxonomy()
    workflow = app_cfg["workflow"]
    history = history_index.refresh(
        client,
        tax,
        [workflow["review_tag"], workflow["llm_queue_tag"], workflow["llm_error_tag"]],
        force=force,
    )
    return {
        "tagging_mode": cfg["tagging_mode"],
        "tags": tax["tags"],
        "tag_guidance": cfg.get("tag_guidance", {}),
        "history": history,
    }


def preview_for(doc_id, config):
    tax = client.taxonomy()
    doc = client.document(doc_id)
    app_cfg = load_app_config()
    workflow = app_cfg["workflow"]
    tagging = history_index.tagging_context(
        client,
        tax,
        config,
        [workflow["review_tag"], workflow["llm_queue_tag"], workflow["llm_error_tag"]],
        doc,
    )
    rendered = render_prompts(doc, tax, config, tagging=tagging)
    return tax, doc, tagging, rendered


def finalize_model_result(result, tax, config, tagging, rendered):
    errors = validate_result(
        result,
        tax,
        config,
        tags_enabled=rendered["tags_enabled"],
    )
    correspondent_resolution = {
        "extracted": "",
        "status": "skipped_main_invalid",
        "resolved": "",
        "suggestion": "",
        "match_score": None,
        "runner_up_score": None,
    }
    if not errors:
        correspondent_resolution = resolve_correspondent(
            result.get("correspondent", ""),
            tax["correspondents"],
        )
        result["correspondent"] = correspondent_resolution["resolved"]
        if tagging.get("route") == "history_match":
            result["tags"] = [tagging["tag"]]
        else:
            result["tags"] = prune_parent_tag_names(result.get("tags", []), tax)
    return errors, correspondent_resolution


class Handler(BaseHTTPRequestHandler):
    server_version = "paperless-local-ai-control-center/0.3"

    def log_message(self, fmt, *args):
        print(f"[HTTP] {self.address_string()} {fmt % args}", flush=True)

    def _dispatch(self):
        path = urlparse(self.path).path
        if self.command == "GET" and path == "/":
            return response(self, HTTPStatus.OK, HTML, "text/html; charset=utf-8")

        if self.command == "GET" and path == "/api/app/state":
            cfg = ensure_app_config()
            return response(
                self,
                HTTPStatus.OK,
                {
                    "config": cfg,
                    "config_sha256": app_config_hash(cfg),
                    "history": list_app_history(),
                    "token_configured": bool(PAPERLESS_TOKEN),
                },
            )
        if self.command == "GET" and path == "/api/app/history":
            return response(self, HTTPStatus.OK, {"items": list_app_history()})
        if self.command == "GET" and path == "/api/app/ocr/recovery":
            return response(self, HTTPStatus.OK, recovery_state_for_ui())
        if self.command == "GET" and path == "/api/app/ocr/health":
            result = {"ok": False, "health": None, "recovery": recovery_state_for_ui()}
            try:
                r = requests.get(OCR_SERVICE_INTERNAL_URL + "/health", timeout=5)
                r.raise_for_status()
                health = r.json()
                result["ok"] = bool(health.get("ok", True)) if isinstance(health, dict) else True
                result["health"] = health
            except Exception as exc:
                result["error"] = f"{type(exc).__name__}: {exc}"
            return response(self, HTTPStatus.OK, result)
        if self.command == "POST" and path == "/api/app/ocr/retry-now":
            payload = body_json(self)
            trigger = request_ocr_retry_now(payload.get("request_id", ""))
            return response(self, HTTPStatus.OK, {"ok": True, "trigger": trigger})
        if self.command == "POST" and path == "/api/app/ocr/failures/dismiss":
            payload = body_json(self)
            removed = dismiss_ocr_failure(payload.get("failure_id", ""))
            return response(self, HTTPStatus.OK, {"ok": True, "removed": removed})
        if self.command == "POST" and path == "/api/app/validate":
            payload = body_json(self)
            cfg = validate_app_config(payload.get("config"))
            return response(self, HTTPStatus.OK, {"ok": True, "config_sha256": app_config_hash(cfg)})
        if self.command == "POST" and path == "/api/app/save":
            payload = body_json(self)
            cfg = save_app_config(payload.get("config"), source="prompt-ui")
            request_history_refresh()
            return response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "config": cfg,
                    "config_sha256": app_config_hash(cfg),
                    "history": list_app_history(),
                    "token_configured": bool(PAPERLESS_TOKEN),
                },
            )
        if self.command == "POST" and path == "/api/app/history/restore":
            payload = body_json(self)
            cfg = restore_app_history(payload.get("file", ""))
            request_history_refresh()
            return response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "config": cfg,
                    "history": list_app_history(),
                    "token_configured": bool(PAPERLESS_TOKEN),
                },
            )
        if self.command == "POST" and path == "/api/app/connections/test":
            payload = body_json(self)
            cfg = validate_app_config(payload.get("config"))
            paperless_result = {"ok": False, "detail": ""}
            if not PAPERLESS_TOKEN:
                paperless_result["detail"] = "PAPERLESS_TOKEN is missing"
            else:
                try:
                    r = requests.get(
                        cfg["connections"]["paperless_url"] + "/api/documents/",
                        params={"page_size": 1},
                        headers={"Authorization": f"Token {PAPERLESS_TOKEN}", "Accept": "application/json"},
                        timeout=20,
                    )
                    r.raise_for_status()
                    paperless_result = {"ok": True, "detail": f"HTTP {r.status_code}"}
                except Exception as exc:
                    paperless_result["detail"] = f"{type(exc).__name__}: {exc}"
            ollama_result = {"ok": False, "detail": ""}
            try:
                r = requests.get(cfg["connections"]["ollama_url"] + "/api/tags", timeout=20)
                r.raise_for_status()
                data = r.json()
                ollama_result = {"ok": True, "detail": f"{len(data.get('models', []))} model(s) found"}
            except Exception as exc:
                ollama_result["detail"] = f"{type(exc).__name__}: {exc}"
            return response(self, HTTPStatus.OK, {"paperless": paperless_result, "ollama": ollama_result})

        if self.command == "GET" and path == "/api/state":
            cfg = ensure_config()
            return response(
                self,
                HTTPStatus.OK,
                {
                    "config": cfg,
                    "placeholders": PLACEHOLDERS,
                    "presets": PROMPT_PRESETS,
                    "hashes": prompt_hashes(cfg),
                    "connections": ensure_app_config()["connections"],
                },
            )
        if self.command == "GET" and path == "/api/health":
            cfg = load_config()
            return response(
                self,
                HTTPStatus.OK,
                {"ok": True, "config_version": cfg["version"], "model": cfg["model"], "tagging_mode": cfg["tagging_mode"]},
            )
        if self.command == "GET" and path == "/api/history":
            return response(self, HTTPStatus.OK, {"items": list_history()})
        if self.command == "GET" and path == "/api/tagging/state":
            return response(self, HTTPStatus.OK, tagging_state(force=False))
        if self.command == "POST" and path == "/api/tagging/refresh":
            request_history_refresh()
            return response(self, HTTPStatus.OK, tagging_state(force=True))
        if self.command == "POST" and path == "/api/config/validate":
            payload = body_json(self)
            cfg = validate_config(payload.get("config"))
            return response(self, HTTPStatus.OK, {"ok": True, "config_sha256": prompt_hashes(cfg)["config_sha256"]})
        if self.command == "POST" and path == "/api/config/save":
            payload = body_json(self)
            cfg = save_config(payload.get("config"), source="prompt-ui")
            return response(self, HTTPStatus.OK, {"ok": True, "config": cfg, "hashes": prompt_hashes(cfg)})
        if self.command == "POST" and path == "/api/history/restore":
            payload = body_json(self)
            cfg = restore_history(payload.get("file", ""))
            return response(self, HTTPStatus.OK, {"ok": True, "config": cfg})
        if self.command == "POST" and path in {"/api/preview", "/api/test"}:
            payload = body_json(self)
            doc_id = int(payload["document_id"])
            cfg = draft_config(payload)
            tax, doc, tagging, rendered = preview_for(doc_id, cfg)
            base = {
                "document": {"id": doc.get("id"), "title": doc.get("title"), "created": doc.get("created")},
                "rendered": {
                    "system_prompt": rendered["system_prompt"],
                    "user_prompt": rendered["user_prompt"],
                    "schema": rendered["schema"],
                },
                "taxonomy": {
                    "tags": tax["tags"],
                    "document_types": tax["document_types"],
                    "existing_correspondents": tax["correspondents"],
                },
                "tagging": tagging,
                "meta": {
                    "config_version": cfg["version"],
                    "draft_config_sha256": prompt_hashes(cfg)["config_sha256"],
                    "model": cfg["model"],
                    "tagging_mode": cfg["tagging_mode"],
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
            errors, correspondent_resolution = finalize_model_result(result, tax, cfg, tagging, rendered)
            base.update(
                {
                    "suggestion": result,
                    "validation_errors": errors,
                    "correspondent_resolution": correspondent_resolution,
                    "performance": performance_from_raw(raw, wall_duration),
                }
            )
            return response(self, HTTPStatus.OK, base)

        return response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_GET(self):
        try:
            self._dispatch()
        except Exception as exc:
            traceback.print_exc()
            response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self):
        try:
            self._dispatch()
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            response(self, HTTPStatus.BAD_REQUEST, {"error": f"{type(exc).__name__}: {exc}"})
        except Exception as exc:
            traceback.print_exc()
            response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"})


if __name__ == "__main__":
    app_cfg = ensure_app_config()
    cfg = ensure_config()
    print(
        f"paperless-local-ai Control Center at http://{HOST}:{PORT} · Settings v{app_cfg['version']} · Classification v{cfg['version']} · Tagging {cfg['tagging_mode']}",
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
