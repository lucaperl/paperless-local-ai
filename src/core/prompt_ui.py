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
    PROMPT_PRESETS,
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
    PROMPT_PRESETS as CORRESPONDENT_PROMPT_PRESETS,
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
:root{
  color-scheme:dark;
  --bg:#0a0f17;--sidebar:#0c131d;--panel:#121a26;--panel2:#0f1722;--line:#263448;--line2:#31435b;
  --text:#f0f4f8;--muted:#93a2b7;--subtle:#66758a;--green:#55d483;--green-bg:#10271c;
  --blue:#6ba8ff;--blue-bg:#10223c;--orange:#f6bd60;--red:#ff7d7d;--radius:12px;
  --shadow:0 10px 30px rgba(0,0,0,.18)
}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%;background:var(--bg);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
button,input,textarea,select{font:inherit}button{cursor:pointer}code,textarea,input.mono,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.app{min-height:100vh;display:grid;grid-template-columns:250px 1fr}
.sidebar{position:sticky;top:0;height:100vh;background:linear-gradient(180deg,#0d1520,#0a111a);border-right:1px solid var(--line);padding:20px 14px;display:flex;flex-direction:column;gap:20px}
.brand{padding:4px 8px 10px}.brand-title{display:flex;align-items:center;gap:10px;font-size:17px;font-weight:750}
.brand-mark{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#1e3350,#14243a);border:1px solid #36506e;display:grid;place-items:center;color:var(--blue);font-weight:900}
.brand-sub{margin:5px 0 0 42px;color:var(--green);font-size:13px}
.nav-group{display:grid;gap:5px}.nav-label{padding:0 10px 5px;color:var(--subtle);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.nav-btn{border:1px solid transparent;background:transparent;color:#ccd6e3;border-radius:9px;padding:10px 11px;text-align:left;display:flex;align-items:center;gap:10px}
.nav-btn:hover{background:#111b28}.nav-btn.active{background:#173325;border-color:#27513b;color:#ecfff3}.nav-icon{width:18px;text-align:center;color:var(--muted)}.nav-btn.active .nav-icon{color:var(--green)}
.sidebar-footer{margin-top:auto;padding:12px;border:1px solid var(--line);background:#0e1722;border-radius:10px}.status-line{display:flex;align-items:center;gap:8px}.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 10px rgba(85,212,131,.45)}
.mini{font-size:12px;color:var(--muted)}
.main{min-width:0}.topbar{min-height:76px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:16px;padding:16px 28px;background:rgba(11,17,26,.9);position:sticky;top:0;z-index:10;backdrop-filter:blur(10px)}
.page-title{font-size:22px;font-weight:750}.page-subtitle{margin-top:2px;color:var(--muted)}.top-actions{display:flex;align-items:center;gap:10px}.pill{padding:7px 10px;border-radius:999px;border:1px solid var(--line);background:#101a27;color:var(--muted);font-size:12px}.pill.good{color:var(--green);border-color:#28563e;background:var(--green-bg)}
.content{padding:24px 28px 48px;max-width:1560px;margin:auto}.page{display:none}.page.active{display:block}
.hero-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}.card{background:linear-gradient(180deg,#131c29,#101823);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.metric-card{padding:18px}.metric-top{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.metric-icon{width:40px;height:40px;border-radius:11px;display:grid;place-items:center;background:#12253a;border:1px solid #203b5a;color:var(--blue);font-size:18px}.metric-card.good .metric-icon{background:#123022;border-color:#28563e;color:var(--green)}
.metric-title{font-size:15px;font-weight:700;margin-top:3px}.metric-value{font-size:14px;margin-top:10px}.metric-detail{margin-top:4px;color:var(--muted);font-size:12px}.good-text{color:var(--green)}.warn-text{color:var(--orange)}
.section-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:16px}.section{padding:18px}.section h2{font-size:16px;margin:0}.section p{color:var(--muted);margin:5px 0 0}
.kv{display:grid;grid-template-columns:1fr auto;gap:10px;padding:10px 0;border-bottom:1px solid #202c3d}.kv:last-child{border-bottom:0}.kv span:first-child{color:var(--muted)}
.flow{display:grid;gap:0;margin-top:18px}.flow-row{display:grid;grid-template-columns:32px 1fr;gap:12px;position:relative}.flow-row:not(:last-child)::before{content:"";position:absolute;left:15px;top:31px;bottom:-7px;width:2px;background:#29405b}
.flow-dot{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;background:#12253a;border:1px solid #2a4c70;color:var(--blue);font-size:12px;z-index:1}.flow-row.good .flow-dot{background:#123022;border-color:#28563e;color:var(--green)}
.flow-copy{padding:5px 0 18px}.flow-title{font-weight:650}.flow-desc{color:var(--muted);font-size:12px;margin-top:2px}
.page-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:16px}.page-head h1{font-size:22px;margin:0}.page-head p{margin:4px 0 0;color:var(--muted);max-width:950px}
.config-badge{padding:8px 10px;border-radius:9px;background:#111b28;border:1px solid var(--line);color:var(--blue);font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;white-space:nowrap}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}.btn{border:1px solid var(--line2);background:#182434;color:var(--text);padding:9px 13px;border-radius:8px}.btn:hover{background:#1d2b3e}.btn.primary{background:#2460aa;border-color:#3275c6}.btn.good{background:#173925;border-color:#2a6742;color:#eafff0}.toolbar-status{margin-left:auto;color:var(--muted);font-size:12px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0;border-bottom:1px solid var(--line);padding-bottom:9px}.tab{border:1px solid transparent;background:transparent;color:var(--muted);padding:8px 11px;border-radius:8px}.tab:hover{background:#121c29;color:var(--text)}.tab.active{background:#1a2a3e;border-color:#2c425d;color:var(--text)}
.tab-page{display:none}.tab-page.active{display:block}.panel{padding:18px}.panel + .panel{margin-top:14px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.form-grid.three{grid-template-columns:repeat(3,1fr)}.field label{display:block;color:#b7c2d1;margin-bottom:6px;font-size:12px}.field-help{color:var(--muted);font-size:11px;margin-top:5px}
input,textarea,select{width:100%;border:1px solid var(--line);background:#0b121b;color:var(--text);border-radius:8px;padding:9px 10px;outline:none}input:focus,textarea:focus,select:focus{border-color:#4b77a8;box-shadow:0 0 0 3px rgba(75,119,168,.14)}
textarea{min-height:250px;resize:vertical;line-height:1.45}.split{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.preview{background:#091019;border:1px solid var(--line);border-radius:8px;padding:12px;min-height:180px;white-space:pre-wrap;overflow:auto;font-size:12px;color:#ced8e4}
.test-row{display:grid;grid-template-columns:220px auto auto 1fr;gap:10px;align-items:end}.result{margin-top:14px;display:grid;grid-template-columns:1fr 1fr;gap:14px}
.history-item{display:grid;grid-template-columns:90px 1fr 180px auto;gap:10px;align-items:center;padding:11px 0;border-bottom:1px solid var(--line)}.history-item:last-child{border-bottom:0}.badge{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--blue)}
.connection-row{display:grid;grid-template-columns:1fr 1fr;gap:14px}.connection{padding:16px}.connection h3{margin:0 0 10px}.connection-status{margin-top:12px;color:var(--green);display:flex;align-items:center;gap:8px}
.placeholder-grid{display:grid;grid-template-columns:repeat(2,minmax(260px,1fr));gap:8px;margin-top:10px}.placeholder-item{background:#0d1520;border:1px solid var(--line);border-radius:8px;padding:10px}.placeholder-item code{display:block;color:var(--blue);font-size:12px;margin-bottom:4px}.placeholder-item span{color:var(--muted);font-size:11px}
.section-help{border:1px solid var(--line);background:#0e1722;border-radius:9px;margin:0 0 14px;overflow:hidden}.section-help summary{cursor:pointer;list-style:none;padding:10px 12px;color:#c5d1df;font-size:12px;font-weight:650;display:flex;align-items:center;gap:8px}.section-help summary::-webkit-details-marker{display:none}.section-help summary::before{content:"i";display:grid;place-items:center;width:18px;height:18px;border-radius:50%;border:1px solid #3a4d66;color:#9fb3ca;font-size:11px}.section-help[open] summary{border-bottom:1px solid var(--line)}.section-help .help-body{padding:11px 12px;color:var(--muted);font-size:12px;line-height:1.55}
.action-note{display:flex;gap:9px;align-items:flex-start;margin:10px 0 14px;padding:10px 12px;border-radius:9px;border:1px solid #35506d;background:#101b29;color:#cbd8e6;font-size:12px}.action-note strong{color:#fff}
.info-btn{display:inline-grid;place-items:center;width:18px;height:18px;margin-left:6px;padding:0;border-radius:50%;border:1px solid #3a4d66;background:#111b28;color:#9fb3ca;font-size:11px;font-weight:700;vertical-align:middle;cursor:help;position:relative}
.info-btn:hover,.info-btn:focus{color:#fff;border-color:#5d7fa8;outline:none;background:#172538}.info-btn[data-tip]::after{content:attr(data-tip);position:absolute;left:50%;bottom:calc(100% + 10px);transform:translateX(-50%);width:min(360px,75vw);padding:9px 10px;border-radius:8px;background:#07101a;border:1px solid #334861;color:#d9e2ec;font-size:11px;font-weight:400;line-height:1.4;text-align:left;white-space:normal;box-shadow:0 12px 26px rgba(0,0,0,.35);opacity:0;pointer-events:none;transition:.12s;z-index:50}
.info-btn[data-tip]::before{content:"";position:absolute;left:50%;bottom:calc(100% + 4px);transform:translateX(-50%);border:6px solid transparent;border-top-color:#334861;opacity:0;transition:.12s;z-index:51}.info-btn:hover::after,.info-btn:focus::after,.info-btn.open::after,.info-btn:hover::before,.info-btn:focus::before,.info-btn.open::before{opacity:1}
.status-box{padding:9px 11px;border-radius:8px;background:#111b28;border:1px solid var(--line);color:var(--muted);white-space:pre-wrap}.status-box.good{color:var(--green)}
.mock-note{margin-top:18px;color:var(--subtle);font-size:11px;text-align:right}
@media(max-width:1100px){.app{grid-template-columns:210px 1fr}.hero-grid{grid-template-columns:1fr 1fr}.section-grid,.split,.result{grid-template-columns:1fr}.form-grid.three{grid-template-columns:1fr 1fr}}
@media(max-width:760px){.app{display:block}.sidebar{position:static;height:auto}.nav-group{grid-template-columns:repeat(2,minmax(0,1fr))}.nav-label{grid-column:1/-1}.sidebar-footer{display:none}.topbar{position:static;padding:14px 16px}.content{padding:18px 16px 36px}.hero-grid,.form-grid,.form-grid.three,.connection-row{grid-template-columns:1fr}.test-row{grid-template-columns:1fr}.toolbar-status{margin-left:0;width:100%}.placeholder-grid{grid-template-columns:1fr}}

.pipeline-shell{margin-top:14px}
.pipeline-group{position:relative;margin:0 0 16px}
.pipeline-group-label{
  display:inline-flex;align-items:center;gap:8px;padding:7px 11px;border-radius:8px;
  font-weight:700;font-size:12px;margin:0 0 8px;border:1px solid var(--line2)
}
.pipeline-group-label.paperless{background:#122033;color:#9fc7ff;border-color:#2d4b6c}
.pipeline-group-label.local{background:#113127;color:#77e6bd;border-color:#25614c}
.pipeline-main{display:grid;gap:0}
.pipeline-step{display:grid;grid-template-columns:34px 1fr;gap:10px;position:relative}
.pipeline-step:not(:last-child)::before{
  content:"";position:absolute;left:16px;top:34px;bottom:-6px;width:2px;background:#29405b
}
.pipeline-step.paperless:not(:last-child)::before{background:#355b80}
.pipeline-step.local:not(:last-child)::before{background:#2d7b67}
.pipeline-num{
  width:34px;height:34px;border-radius:50%;display:grid;place-items:center;z-index:1;
  border:1px solid #36506e;background:#16263a;color:#a9cbf5;font-size:12px
}
.pipeline-step.local .pipeline-num{background:#12362b;border-color:#2a735f;color:#74e3bc}
.pipeline-copy{padding:4px 0 16px}
.pipeline-title{font-weight:700}
.pipeline-desc{margin-top:3px;color:var(--muted);font-size:12px}
.pipeline-branch-wrap{
  margin:2px 0 16px 44px;display:grid;grid-template-columns:minmax(260px,.9fr) minmax(360px,1.3fr);
  gap:14px;align-items:stretch
}
.pipeline-decision{
  border:1px dashed #7b5aa6;background:#151323;border-radius:10px;padding:12px 14px;
  display:flex;align-items:center;justify-content:center;text-align:center;color:#c5b2e3;font-size:12px
}
.pipeline-fallback{
  border:1px solid #6d4a8d;background:linear-gradient(180deg,#181326,#12101d);
  border-radius:10px;padding:14px
}
.pipeline-fallback-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:9px}
.pipeline-fallback-title{font-weight:750;color:#d9b5ff}
.pipeline-fallback-badge{
  font-size:11px;color:#ffc76b;background:#2a2011;border:1px solid #664a19;border-radius:999px;padding:4px 7px;white-space:nowrap
}
.pipeline-fallback-desc{color:var(--muted);font-size:12px;margin-bottom:10px}
.pipeline-outcome{display:grid;grid-template-columns:1fr auto;gap:12px;padding:8px 9px;border:1px solid #302a41;border-radius:8px;background:#10101a;margin-top:6px;font-size:11px}
.pipeline-outcome strong{color:#e9edf3}
.pipeline-outcome .ok{color:#63d98b}.pipeline-outcome .review{color:#f1bd62}.pipeline-outcome .empty{color:#ef8c8c}
.pipeline-return{
  display:flex;align-items:center;gap:8px;margin:3px 0 10px;color:#8eb8e9;font-size:12px;font-weight:700
}
.pipeline-return::before{content:"↩";font-size:16px}
@media(max-width:980px){.pipeline-branch-wrap{grid-template-columns:1fr;margin-left:44px}}


.pipeline-branch{
  position:relative;
  margin:0 0 18px 44px;
  display:grid;
  grid-template-columns:minmax(0,1fr) minmax(380px,1.15fr);
  gap:18px;
  align-items:start;
}
.pipeline-branch::before{
  content:"";
  position:absolute;
  left:-27px;
  top:-18px;
  width:27px;
  height:2px;
  background:#2d7b67;
}
.pipeline-main-path{
  position:relative;
  min-height:164px;
  padding:14px 14px 14px 20px;
  border:1px dashed #31584d;
  border-radius:10px;
  background:#0f1b18;
}
.pipeline-main-path::before{
  content:"";
  position:absolute;
  left:18px;
  top:-18px;
  bottom:-18px;
  width:2px;
  background:#2d7b67;
}
.pipeline-main-path-label{
  position:relative;
  z-index:1;
  display:inline-flex;
  align-items:center;
  gap:7px;
  padding:5px 8px;
  border-radius:999px;
  background:#133629;
  border:1px solid #2f6c58;
  color:#8be6c5;
  font-size:11px;
  font-weight:700;
}
.pipeline-main-path-copy{
  position:relative;
  z-index:1;
  margin-top:12px;
  color:var(--muted);
  font-size:12px;
  max-width:330px;
}
.pipeline-fallback-path{
  position:relative;
}
.pipeline-fallback-path::before{
  content:"";
  position:absolute;
  left:-18px;
  top:28px;
  width:18px;
  height:2px;
  background:#7f62a8;
}
.pipeline-fallback-path::after{
  content:"";
  position:absolute;
  left:-18px;
  top:-18px;
  width:2px;
  height:47px;
  background:#7f62a8;
}
.pipeline-fallback{
  margin:0;
}
.pipeline-merge{
  position:relative;
  height:24px;
  margin:0 0 0 44px;
}
.pipeline-merge::before{
  content:"";
  position:absolute;
  left:18px;
  top:-18px;
  width:2px;
  height:42px;
  background:#2d7b67;
}
.pipeline-merge::after{
  content:"";
  position:absolute;
  right:calc(38.5% - 10px);
  top:-18px;
  width:calc(61.5% - 52px);
  height:2px;
  background:#7f62a8;
}
.pipeline-return-group{
  margin-top:2px;
  padding-top:2px;
  border-top:1px solid rgba(53,91,128,.22);
}
@media(max-width:980px){
  .pipeline-branch{grid-template-columns:1fr;margin-left:44px}
  .pipeline-main-path{min-height:auto}
  .pipeline-fallback-path::before,.pipeline-fallback-path::after,.pipeline-merge::after{display:none}
}


.branch-choice{
  margin:2px 0 18px 44px;
}
.branch-choice-head{
  display:flex;align-items:center;gap:8px;margin-bottom:10px;color:var(--muted);font-size:11px;
}
.branch-choice-head::before{
  content:"";width:24px;height:2px;background:#2d7b67;border-radius:2px
}
.branch-grid{
  display:grid;
  grid-template-columns:minmax(260px,.9fr) minmax(420px,1.3fr);
  gap:14px;
  align-items:stretch
}
.branch-card{
  border-radius:10px;
  padding:14px;
  min-width:0
}
.branch-card.main{
  border:1px solid #2f6c58;
  background:linear-gradient(180deg,#10251d,#0d1a15);
}
.branch-card.fallback{
  border:1px solid #6d4a8d;
  background:linear-gradient(180deg,#181326,#12101d);
}
.branch-card-head{
  display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px
}
.branch-label{
  display:inline-flex;align-items:center;gap:6px;padding:5px 8px;border-radius:999px;font-size:11px;font-weight:700
}
.branch-label.main{
  color:#8be6c5;background:#133629;border:1px solid #2f6c58
}
.branch-label.fallback{
  color:#d9b5ff;background:#241633;border:1px solid #6d4a8d
}
.branch-badge{
  font-size:11px;color:#ffc76b;background:#2a2011;border:1px solid #664a19;border-radius:999px;padding:4px 7px;white-space:nowrap
}
.branch-copy{color:var(--muted);font-size:12px;line-height:1.5}
.branch-outcomes{display:grid;gap:6px;margin-top:10px}
.branch-outcome{
  display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;
  padding:8px 9px;border:1px solid #302a41;border-radius:8px;background:#10101a;font-size:11px
}
.branch-outcome strong{color:#e9edf3}
.branch-outcome .ok{color:#63d98b}.branch-outcome .review{color:#f1bd62}.branch-outcome .empty{color:#ef8c8c}
.branch-merge{
  display:flex;align-items:center;justify-content:center;gap:8px;
  margin:12px 0 4px;color:#9db0c6;font-size:11px
}
.branch-merge::before,.branch-merge::after{
  content:"";height:1px;background:#33475f;flex:1
}
.branch-merge-pill{
  padding:5px 9px;border-radius:999px;border:1px solid #33475f;background:#101923;color:#b8c6d6;white-space:nowrap
}
@media(max-width:980px){
  .branch-grid{grid-template-columns:1fr}
  .branch-choice{margin-left:44px}
}


.trigger-rule{
  margin:2px 0 10px 44px;
  padding:9px 11px;
  border-radius:9px;
  border:1px solid #33475f;
  background:#0e1722;
  color:#c7d3df;
  font-size:12px;
}
.trigger-rule strong{color:#fff}
.branch-card.bypass{
  border:1px solid #455366;
  background:linear-gradient(180deg,#141b24,#10161e);
}
.branch-label.bypass{
  color:#c1cbd8;background:#1a222d;border:1px solid #455366
}
.branch-grid.three{
  grid-template-columns:minmax(220px,.8fr) minmax(260px,.9fr) minmax(420px,1.35fr);
}
@media(max-width:1200px){
  .branch-grid.three{grid-template-columns:1fr 1fr}
  .branch-card.fallback{grid-column:1/-1}
}
@media(max-width:820px){
  .branch-grid.three{grid-template-columns:1fr}
  .branch-card.fallback{grid-column:auto}
}


.metric-card.bad .metric-icon{background:#351a1e;border-color:#6b2f38;color:var(--red)}
.bad-text{color:var(--red)!important}.pill.bad{color:var(--red);border-color:#6b2f38;background:#271216}.pill.warn{color:var(--orange);border-color:#634b20;background:#241c10}
.status-box.good{color:var(--green);border-color:#28563e}.status-box.bad{color:var(--red);border-color:#6b2f38}
pre.preview{margin:0;min-height:180px;max-height:620px}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-title"><div class="brand-mark">P</div><span>paperless-local-ai</span></div>
      <div class="brand-sub">Control Center</div>
    </div>
    <div class="nav-group">
      <div class="nav-label">Control Center</div>
      <button class="nav-btn active" data-page="overview"><span class="nav-icon">◫</span>Overview</button>
      <button class="nav-btn" data-page="classification"><span class="nav-icon">◎</span>Classification</button>
      <button class="nav-btn" data-page="correspondent"><span class="nav-icon">↪</span>Correspondent</button>
      <button class="nav-btn" data-page="app-settings"><span class="nav-icon">⚙</span>App Settings</button>
    </div>
    <div class="sidebar-footer">
      <div class="status-line"><span class="dot"></span><strong id="sidebarMode">Loading…</strong></div>
      <div id="sidebarAppVersion" class="mini" style="margin-top:8px">AppConfig …</div><div id="sidebarModel" class="mini">Loading…</div>
    </div>
  </aside>

  <main class="main">
    <header class="topbar">
      <div><div class="page-title" id="topTitle">Overview</div><div class="page-subtitle" id="topSubtitle">System overview and current configuration</div></div>
      <div class="top-actions"><span id="topStatus" class="pill">Loading…</span><span id="topModeStatus" class="pill">Loading…</span></div>
    </header>

    <div class="content">
      <section class="page active" id="page-overview">
        <details class="section-help">
          <summary>About the Control Center</summary>
          <div class="help-body">Configure the app, validate connections, preview exact prompts and run real model tests before enabling production metadata writes. Deployment-only values and the Paperless API token remain in <code>.env</code>.</div>
        </details>
        <div class="hero-grid">
          <div id="overviewPaperlessCard" class="card metric-card"><div class="metric-top"><div><div class="metric-title">Paperless-ngx</div><div id="overviewPaperlessStatus" class="metric-value">Checking…</div></div><div class="metric-icon">P</div></div><div id="overviewPaperlessDetail" class="metric-detail">Loading…</div></div>
          <div id="overviewOllamaCard" class="card metric-card"><div class="metric-top"><div><div class="metric-title">Ollama</div><div id="overviewOllamaStatus" class="metric-value">Checking…</div></div><div class="metric-icon">O</div></div><div id="overviewOllamaDetail" class="metric-detail">Loading…</div></div>
          <div id="overviewOcrCard" class="card metric-card"><div class="metric-top"><div><div class="metric-title">OCR</div><div id="overviewOcrStatus" class="metric-value">Loading…</div></div><div class="metric-icon">OCR</div></div><div id="overviewOcrDetail" class="metric-detail">Loading…</div></div>
          <div id="overviewCorrCard" class="card metric-card"><div class="metric-top"><div><div class="metric-title">Correspondent fallback</div><div id="overviewCorrStatus" class="metric-value">Loading…</div></div><div class="metric-icon">↪</div></div><div id="overviewCorrDetail" class="metric-detail">Loading…</div></div>
        </div>
        <div class="section-grid">
          <div class="card section">
            <h2>Pipeline</h2>
            <p><strong>paperless-local-ai extends Paperless import and review:</strong> OCRmyPDF delegates scanned-page recognition to the local PaddleOCR service, then a normal Paperless workflow queues completed documents for local metadata classification.</p>

            <div class="pipeline-shell">
              <div class="pipeline-group">
                <div class="pipeline-group-label paperless">Paperless-ngx</div>
                <div class="pipeline-main">
                  <div class="pipeline-step paperless">
                    <div class="pipeline-num">1</div>
                    <div class="pipeline-copy">
                      <div class="pipeline-title">Paperless import</div>
                      <div class="pipeline-desc">Paperless consumes the original document and runs its normal parser/OCRmyPDF path.</div>
                    </div>
                  </div>
                  <div class="pipeline-step paperless">
                    <div class="pipeline-num">2</div>
                    <div class="pipeline-copy">
                      <div class="pipeline-title">OCRmyPDF → PaddleOCR</div>
                      <div class="pipeline-desc">When OCR is needed, OCRmyPDF calls the authenticated local OCR service and writes a searchable archive text layer plus extracted content.</div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="pipeline-group">
                <div class="pipeline-group-label local">paperless-local-ai</div>
                <div class="pipeline-main">
                  <div class="pipeline-step local">
                    <div class="pipeline-num">3</div>
                    <div class="pipeline-copy">
                      <div class="pipeline-title">Queue metadata classification</div>
                      <div class="pipeline-desc">After the Paperless document is added, a Document Added workflow assigns the LLM queue tag. No OCR queue tag is involved.</div>
                    </div>
                  </div>

                  <div class="pipeline-step local">
                    <div class="pipeline-num">4</div>
                    <div class="pipeline-copy">
                      <div class="pipeline-title">Primary LLM classification</div>
                      <div class="pipeline-desc">One structured request determines title, document type, date, tags and tries to match one of the existing Paperless correspondents.</div>
                    </div>
                  </div>
                </div>

                <div class="trigger-rule">
                  <strong>What happens after classification?</strong>
                  The correspondent fallback is considered only when the primary classification returns <strong>no correspondent</strong>. It runs only if the fallback is enabled under Correspondent → Settings.
                </div>

                <div class="branch-choice">
                  <div class="branch-choice-head">Classification result</div>

                  <div class="branch-grid three">
                    <div class="branch-card main">
                      <div class="branch-card-head">
                        <div class="branch-label main">Existing correspondent returned</div>
                      </div>
                      <div class="branch-copy">
                        The primary classification matched one of the correspondents already present in Paperless.
                        That correspondent continues with the other metadata directly to write-back.
                      </div>
                    </div>

                    <div class="branch-card bypass">
                      <div class="branch-card-head">
                        <div class="branch-label bypass">No correspondent · fallback disabled</div>
                      </div>
                      <div class="branch-copy">
                        No additional LLM call runs. The document continues to write-back with the correspondent left empty.
                      </div>
                    </div>

                    <div class="branch-card fallback">
                      <div class="branch-card-head">
                        <div class="branch-label fallback">No correspondent · fallback enabled</div>
                        <div class="branch-badge">run correspondent fallback</div>
                      </div>
                      <div class="branch-copy">
                        A separate sender-identification LLM call runs with its own prompt and settings. It receives the document text plus the current Paperless correspondent list.
                      </div>

                      <div class="branch-outcomes">
                        <div class="branch-outcome">
                          <strong>Sender matches a correspondent already in Paperless</strong>
                          <span class="ok">apply automatically</span>
                        </div>
                        <div class="branch-outcome">
                          <strong>Sender is identified but does not exist in Paperless yet</strong>
                          <span class="review">Paperless suggestion/review</span>
                        </div>
                        <div class="branch-outcome">
                          <strong>No reliable sender can be identified</strong>
                          <span class="empty">leave empty</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div class="branch-merge">
                    <span class="branch-merge-pill">all paths continue to write-back ↓</span>
                  </div>
                </div>

                <div class="pipeline-main">
                  <div class="pipeline-step local">
                    <div class="pipeline-num">5</div>
                    <div class="pipeline-copy">
                      <div class="pipeline-title">Write back to Paperless</div>
                      <div class="pipeline-desc">Metadata is applied to the same Paperless document; processing tags move it into the normal review state.</div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="pipeline-return-group">
                <div class="pipeline-group">
                  <div class="pipeline-group-label paperless">Paperless-ngx</div>
                  <div class="pipeline-main">
                    <div class="pipeline-step paperless">
                      <div class="pipeline-num">6</div>
                      <div class="pipeline-copy">
                        <div class="pipeline-title">Paperless review</div>
                        <div class="pipeline-desc">The normal Paperless workflow continues. Any proposed new correspondent is shown through Paperless' native suggestion/review flow.</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="card section">
            <h2>Current configuration</h2><p>Only values already available from the current APIs.</p>
            <div style="margin-top:12px">
              <div class="kv"><span>Mode</span><strong id="overviewMode">Loading…</strong></div><div class="kv"><span>Classification</span><span id="overviewClassification">Loading…</span></div><div class="kv"><span>Correspondent fallback</span><span id="overviewCorrConfig">Loading…</span></div><div class="kv"><span>Polling interval</span><span id="overviewPoll">Loading…</span></div><div class="kv"><span>Review cleanup</span><span id="overviewCleanup">Loading…</span></div><div class="kv"><span>Max classification tags</span><span id="overviewMaxTags">Loading…</span></div>
            </div>
          </div>
        </div>
      </section>

      <section class="page" id="page-classification">
        <div class="page-head">
          <div><h1>Document classification</h1><p>Stage 1 runs for every document picked up by automatic LLM processing. The model determines title, document type, an existing Paperless correspondent, classification tags and document date in one structured request. Valid results are written directly to Paperless. If the correspondent remains empty, stage 2 can run afterwards.</p></div>
          <div id="classConfigStatus" class="config-badge">Loading…</div>
        </div>
        <div class="toolbar">
          <button id="validateBtn" class="btn">Validate configuration</button>
          <button id="saveBtn" class="btn primary">Save changes</button>
          <span id="saveStatus" class="toolbar-status">Nothing validated or saved yet.</span>
        </div>
        <details class="section-help">
          <summary>What do Validate and Save do?</summary>
          <div class="help-body"><strong>Validate configuration</strong> checks required fields, placeholders and values without saving. <strong>Save changes</strong> creates a new version that is used from the next production classification job. No restart is required.</div>
        </details>

        <div class="tabs" data-tabs="classification">
          <button class="tab active" data-tab="class-prompt">Prompt</button><button class="tab" data-tab="class-test">Test</button><button class="tab" data-tab="class-output">Output &amp; allowed values</button><button class="tab" data-tab="class-settings">Settings</button><button class="tab" data-tab="class-history">History</button>
        </div>

        <div class="tab-page active" id="class-prompt">
          <details class="section-help"><summary>What is edited here?</summary><div class="help-body">The system prompt contains the general rules for stage 1. The classification prompt contains the task for one document. Placeholders such as <code>{{DOCUMENT_TEXT}}</code> are replaced with data from the selected Paperless document immediately before the model call.</div></details>
          <div class="card panel" style="margin-bottom:14px"><div class="form-grid" style="align-items:end">
            <div class="field"><label>Prompt preset <button type="button" class="info-btn" data-tip="Built-in starting points for the prompt text. Loading a preset changes only the visible draft; it does not save or activate anything automatically.">i</button></label><select id="classPromptPreset"></select></div>
            <div><button id="classLoadPresetBtn" class="btn">Load preset into draft</button><div class="field-help">Replaces the two visible prompt fields only. Review or edit them, then save to activate.</div></div>
          </div></div>
          <div class="split">
            <div class="card panel">
              <div class="field"><label>System prompt <button type="button" class="info-btn" data-tip="Applied to every classification run and defines role, safety rules and general output requirements. Document-specific content belongs in the classification prompt; {{DOCUMENT_TEXT}} must remain there.">i</button></label>
              <textarea id="systemPrompt"></textarea></div>
            </div>
            <div class="card panel">
              <div class="field"><label>Classification prompt <button type="button" class="info-btn" data-tip="Task for one document. It defines how title, document type, existing correspondent, tags and date are determined. The rendered prompt is sent to Ollama as the user message.">i</button></label>
              <textarea id="classificationTemplate"></textarea></div>
            </div>
          </div>
          <div class="card panel" style="margin-top:14px">
            <h3 style="margin-top:0">Available placeholders</h3>
            <p class="mini">At runtime, the Control Center replaces each placeholder with the current value from the test or production document. <code>_JSON</code> variants provide a correctly formatted JSON list; <code>_LINES</code> provides the same values one per line. <code>{{DOCUMENT_TEXT}}</code> is required and must not be removed.</p>
            <div id="placeholders" class="placeholder-grid"></div>
          </div>
        </div>

        <div class="tab-page" id="class-test">
          <div class="action-note"><span>ⓘ</span><div><strong>Safe test before production.</strong> Select an existing Paperless document by ID. <strong>Preview final prompt</strong> loads the document and taxonomy and shows exactly what would be sent to the model without calling it. <strong>Run model test</strong> additionally performs a real Ollama request. Both use the currently visible, even unsaved draft and never modify the Paperless document.</div></div>
          <div class="card panel">
            <div class="test-row">
              <div class="field"><label>Paperless document ID <button type="button" class="info-btn" data-tip="Numeric document ID from Paperless, for example from the document URL or API.">i</button></label><input id="docId" class="mono" type="number" min="1" value="93"></div>
              <button id="previewBtn" class="btn">Preview final prompt</button>
              <button id="testBtn" class="btn primary">Run model test</button>
              <div class="mini">A live model test uses the same shared AI lock as OCR and production LLM jobs. These expensive tasks therefore do not run at the same time; if the AI slot is busy, the test waits.</div>
            </div>
            <div id="testStatus" class="status-box" style="margin-top:12px">Ready for prompt preview or model test.</div>
          </div>
          <div class="result">
            <div class="card panel"><h3 style="margin-top:0">System message sent to the model</h3><p class="mini">Exact rendered system prompt for this test.</p><pre id="systemPreview" class="preview"></pre></div>
            <div class="card panel"><h3 style="margin-top:0">User message sent to the model</h3><p class="mini">Exact rendered classification prompt including substituted placeholders.</p><pre id="userPreview" class="preview"></pre></div>
            <div class="card panel"><h3 style="margin-top:0">Model response and validation</h3><p class="mini">Filled only by <strong>Run model test</strong>. Shows the structured suggestion, validation errors and performance data.</p><pre id="testResult" class="preview"></pre></div>
            <div class="card panel"><h3 style="margin-top:0">Test request details</h3><p class="mini">Technical details about the rendered request, such as configuration version and amount of document text used.</p><pre id="previewMeta" class="preview"></pre></div>
          </div>
        </div>

        <div class="tab-page" id="class-output">
          <details class="section-help"><summary>What is shown here?</summary><div class="help-body">The output schema is the fixed JSON contract the model response must satisfy. Allowed Paperless values show the taxonomy loaded by the most recent preview or model test. Stage 1 can use only current list values for document type, correspondent and tags.</div></details>
          <div class="split">
            <div class="card panel"><h3 style="margin-top:0">Expected JSON output</h3><p class="mini">Defines fields, data types and allowed values for the model response. It is generated automatically from the current configuration.</p><pre id="schemaPreview" class="preview"></pre></div>
            <div class="card panel"><h3 style="margin-top:0">Currently allowed Paperless values</h3><p class="mini">Document types, correspondents and classification tags loaded from Paperless during the latest preview or model test. Technical process tags such as <code>Inbox</code> or <code>LLM</code> are excluded.</p><pre id="taxonomyPreview" class="preview"></pre></div>
          </div>
        </div>

        <div class="tab-page" id="class-settings">
          <details class="section-help"><summary>About these settings</summary><div class="help-body">These settings apply only to Stage 1. Changes affect production only after <strong>Save changes</strong>. They do not modify Ollama itself or the installed model.</div></details>
          <div class="card panel"><div class="form-grid three">
            <div class="field"><label>Ollama model <span class="mini">(model)</span> <button type="button" class="info-btn" data-tip="Exact name of a model already installed in Ollama, for example qwen3.5:4b. The Control Center does not download or install models.">i</button></label><input id="model"></div>
            <div class="field"><label>Context window in tokens <span class="mini">(num_ctx)</span> <button type="button" class="info-btn" data-tip="Maximum context Ollama provides for prompt and response. A larger value allows more text but uses more memory and may be slower.">i</button></label><input id="numCtx" type="number"></div>
            <div class="field"><label>Maximum response length in tokens <span class="mini">(num_predict)</span> <button type="button" class="info-btn" data-tip="Upper limit for the generated JSON response. Too small a value can truncate the response; it does not control the amount of document text read.">i</button></label><input id="numPredict" type="number"></div>
            <div class="field"><label>Output randomness <span class="mini">(temperature)</span> <button type="button" class="info-btn" data-tip="0 provides the most reproducible results and is recommended for metadata. Higher values make responses more variable.">i</button></label><input id="temperature" type="number" min="0" max="2" step="0.05"></div>
            <div class="field"><label>Additional model reasoning <span class="mini">(think)</span> <button type="button" class="info-btn" data-tip="Off is intended for this short structured classification. On enables the model's thinking mode and uses additional time/tokens.">i</button></label><select id="think"><option value="false">Off</option><option value="true">On</option></select></div>
            <div class="field"><label>Keep model loaded after the job <span class="mini">(keep_alive)</span> <button type="button" class="info-btn" data-tip="Passed directly to Ollama. 0 unloads the model after the request; for example 5m keeps it loaded for five minutes. Longer keep-alive uses RAM for longer.">i</button></label><input id="keepAlive"></div>
            <div class="field"><label>Maximum document text in characters <span class="mini">(content_char_limit)</span> <button type="button" class="info-btn" data-tip="Maximum number of characters from Paperless content included in the prompt. Shorter documents are used in full; longer documents are truncated according to the setting below.">i</button></label><input id="contentLimit" type="number"></div>
            <div class="field"><label>Share kept from document start when truncated <span class="mini">(content_head_ratio)</span> <button type="button" class="info-btn" data-tip="Applies only when the document exceeds the character limit. 0.75 means 75% of the retained text comes from the start and 25% from the end.">i</button></label><input id="headRatio" type="number" min="0.5" max="0.95" step="0.05"></div>
            <div class="field"><label>Maximum classification tags <span class="mini">(max_tags)</span> <button type="button" class="info-btn" data-tip="Limits how many classification tags the model response may contain. The value is applied directly to the output schema and validation; process tags do not count.">i</button></label><input id="maxTags" type="number" min="1" max="10"></div>
            <div class="field"><label>Ollama timeout in seconds <span class="mini">(timeout)</span> <button type="button" class="info-btn" data-tip="Maximum time the worker waits for the model request. If exceeded, the request fails and follows normal error handling.">i</button></label><input id="ollamaTimeout" type="number"></div>
          </div></div>
        </div>

        <div class="tab-page" id="class-history">
          <details class="section-help"><summary>What is versioned?</summary><div class="help-body">Every save stores prompt and settings together as a new classification version. Restoring does not overwrite history: the selected older state becomes a new active version.</div></details>
          <div class="card panel">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><h3 style="margin:0">Saved versions</h3><button id="historyRefresh" class="btn">Reload history</button></div>
            <p class="mini"><strong>Restore this version</strong> saves the selected state again as the current configuration. The currently active state remains in history as its own version.</p>
            <div id="historyList"></div>
          </div>
        </div>
      </section>

      <section class="page" id="page-correspondent">
        <div class="page-head">
          <div><h1>Correspondent fallback</h1><p>Stage 2 is optional and runs only when stage 1 found no correspondent and <strong>Enable in production</strong> is on. It identifies only the sender or issuer. An unambiguous existing Paperless correspondent is applied automatically. A genuinely new name is never created automatically; it appears as a native Paperless suggestion for confirmation. If no reliable name is found, nothing changes.</p></div>
          <div id="corrConfigStatus" class="config-badge">Loading…</div>
        </div>
        <div class="toolbar"><button id="corrValidateBtn" class="btn">Validate configuration</button><button id="corrSaveBtn" class="btn primary">Save changes</button><span id="corrSaveStatus" class="toolbar-status">Nothing validated or saved yet.</span></div>
        <details class="section-help"><summary>What do Validate and Save do?</summary><div class="help-body"><strong>Validate configuration</strong> checks required fields, placeholders and values without saving. <strong>Save changes</strong> creates a new version. The <strong>Enable in production</strong> switch under Settings controls whether Stage 2 runs automatically.</div></details>

        <div class="tabs" data-tabs="correspondent"><button class="tab active" data-tab="corr-prompt">Prompt</button><button class="tab" data-tab="corr-test">Test</button><button class="tab" data-tab="corr-settings">Settings</button><button class="tab" data-tab="corr-history">History</button></div>

        <div class="tab-page active" id="corr-prompt">
          <details class="section-help"><summary>What is edited here?</summary><div class="help-body">These prompts belong only to stage 2. They do not affect the title, document type, tags or date from stage 1. Unlike stage 1, this pass may suggest a new correspondent name, but it does not create one.</div></details>
          <div class="card panel" style="margin-bottom:14px"><div class="form-grid" style="align-items:end">
            <div class="field"><label>Prompt preset <button type="button" class="info-btn" data-tip="Built-in starting points for sender-identification prompt text. Loading a preset changes only the visible draft; it does not save or enable production use automatically.">i</button></label><select id="corrPromptPreset"></select></div>
            <div><button id="corrLoadPresetBtn" class="btn">Load preset into draft</button><div class="field-help">Replaces the two visible prompt fields only. Review or edit them, then save to activate.</div></div>
          </div></div>
          <div class="split">
            <div class="card panel"><div class="field"><label>System prompt <button type="button" class="info-btn" data-tip="General role and safety rules for sender identification. The document text belongs in the correspondent prompt.">i</button></label><textarea id="corrSystemPrompt"></textarea></div></div>
            <div class="card panel"><div class="field"><label>Correspondent prompt <button type="button" class="info-btn" data-tip="Task for one document. The model response contains only correspondent: either a suitable existing/new sender name or an empty string when the sender cannot be determined reliably.">i</button></label><textarea id="corrPromptTemplate"></textarea></div></div>
          </div>
          <div class="card panel" style="margin-top:14px">
            <h3 style="margin-top:0">Available placeholders</h3>
            <p class="mini"><code>{{DOCUMENT_TEXT}}</code> is required. <code>{{CORRESPONDENTS_JSON}}</code> and <code>{{CORRESPONDENTS_LINES}}</code> provide existing Paperless correspondents as reference. This list is not a hard restriction in stage 2: if the actual sender does not yet exist, the model may suggest a new name.</p>
            <div id="corrPlaceholders" class="placeholder-grid"></div>
          </div>
        </div>

        <div class="tab-page" id="corr-test">
          <div class="action-note"><span>ⓘ</span><div><strong>What happens during testing?</strong> <strong>Preview final prompt</strong> shows the exact Stage 2 input for a real Paperless document without calling the model. <strong>Run model test</strong> performs a real Ollama request. Neither Paperless metadata nor persistent review suggestions are written. Testing works even when <strong>Enable in production</strong> is off.</div></div>
          <div class="card panel">
            <div class="test-row">
              <div class="field"><label>Paperless document ID <button type="button" class="info-btn" data-tip="Numeric document ID from Paperless, for example from the document URL or API.">i</button></label><input id="corrDocId" type="number" min="1" value="93"></div>
              <button id="corrPreviewBtn" class="btn">Preview final prompt</button>
              <button id="corrTestBtn" class="btn primary">Run model test</button>
              <div class="mini">Preview and model test use the currently visible, even unsaved draft. A live model test uses the shared AI lock so OCR and LLM jobs do not consume the available resources at the same time.</div>
            </div>
            <div id="corrTestStatus" class="status-box" style="margin-top:12px">Ready for prompt preview or model test.</div>
          </div>
          <div class="result">
            <div class="card panel"><h3 style="margin-top:0">System message sent to the model</h3><p class="mini">Exact rendered system prompt for this test.</p><pre id="corrSystemPreview" class="preview"></pre></div>
            <div class="card panel"><h3 style="margin-top:0">User message sent to the model</h3><p class="mini">Exact rendered correspondent prompt including substituted placeholders.</p><pre id="corrUserPreview" class="preview"></pre></div>
            <div class="card panel"><h3 style="margin-top:0">Expected JSON output</h3><p class="mini">Stage 2 may return only the <code>correspondent</code> field.</p><pre id="corrSchemaPreview" class="preview"></pre></div>
            <div class="card panel"><h3 style="margin-top:0">Model response and validation</h3><p class="mini">Filled only by <strong>Run model test</strong>. Shows the candidate, validation errors and performance data.</p><pre id="corrTestResult" class="preview"></pre></div>
            <div class="card panel" style="grid-column:1/-1"><h3 style="margin-top:0">Test request details</h3><p class="mini">Technical details about the rendered request, such as configuration version and amount of document text used.</p><pre id="corrPreviewMeta" class="preview"></pre></div>
          </div>
        </div>

        <div class="tab-page" id="corr-settings">
          <details class="section-help"><summary>About these settings</summary><div class="help-body">These settings apply only to stage 2. Configure whether the fallback runs automatically in production and which model/text parameters it uses. Tests in the Test tab are always available, regardless of the production switch.</div></details>
          <div class="card panel"><h3 style="margin-top:0">Production use</h3>
            <div class="field"><label>Enable in production <span class="mini">(enabled)</span> <button type="button" class="info-btn" data-tip="When On, stage 2 starts automatically only when stage 1 returned no correspondent. An exact existing Paperless name is applied directly; a new name is stored only as a suggestion for confirmation. Empty or uncertain results change nothing. This switch does not affect manual tests.">i</button></label><select id="corrEnabled"><option value="false">Off — manual testing only</option><option value="true">On — run when correspondent is empty</option></select></div>
          </div>
          <div class="card panel"><h3 style="margin-top:0">Model and request parameters</h3><div class="form-grid three">
            <div class="field"><label>Ollama model <span class="mini">(model)</span> <button type="button" class="info-btn" data-tip="Exact name of a model already installed in Ollama. The Control Center does not download or install models.">i</button></label><input id="corrModel"></div>
            <div class="field"><label>Context window in tokens <span class="mini">(num_ctx)</span> <button type="button" class="info-btn" data-tip="Maximum context for the prompt and response of this second model call. Larger values use more memory and may be slower.">i</button></label><input id="corrNumCtx" type="number"></div>
            <div class="field"><label>Maximum response length in tokens <span class="mini">(num_predict)</span> <button type="button" class="info-btn" data-tip="Upper limit for the short JSON response. Because only a name or empty string is expected, this can usually be much smaller than in stage 1.">i</button></label><input id="corrNumPredict" type="number"></div>
            <div class="field"><label>Output randomness <span class="mini">(temperature)</span> <button type="button" class="info-btn" data-tip="0 is recommended for reproducible sender names. Higher values make suggestions more variable and increase unnecessary name variations.">i</button></label><input id="corrTemperature" type="number" min="0" max="2" step="0.05"></div>
            <div class="field"><label>Additional model reasoning <span class="mini">(think)</span> <button type="button" class="info-btn" data-tip="Off is intended for short sender identification. On enables the model's thinking mode and uses additional time/tokens.">i</button></label><select id="corrThink"><option value="false">Off</option><option value="true">On</option></select></div>
            <div class="field"><label>Keep model loaded after the job <span class="mini">(keep_alive)</span> <button type="button" class="info-btn" data-tip="Passed directly to Ollama. 0 unloads the model after the request; for example 5m keeps it loaded for five minutes.">i</button></label><input id="corrKeepAlive"></div>
            <div class="field"><label>Maximum document text in characters <span class="mini">(content_char_limit)</span> <button type="button" class="info-btn" data-tip="Maximum number of characters from Paperless content included in the correspondent prompt. Shorter documents are used in full.">i</button></label><input id="corrContentLimit" type="number"></div>
            <div class="field"><label>Share kept from document start when truncated <span class="mini">(content_head_ratio)</span> <button type="button" class="info-btn" data-tip="Applies only to truncated documents. 0.75 means 75% of the retained text comes from the start and 25% from the end.">i</button></label><input id="corrHeadRatio" type="number" min="0.5" max="0.95" step="0.05"></div>
            <div class="field"><label>Ollama timeout in seconds <span class="mini">(timeout)</span> <button type="button" class="info-btn" data-tip="Maximum time the worker waits for the second model call. If exceeded, the call fails.">i</button></label><input id="corrTimeout" type="number"></div>
          </div></div>
        </div>

        <div class="tab-page" id="corr-history">
          <details class="section-help"><summary>What is versioned?</summary><div class="help-body">Prompt, production switch and stage-2 settings are versioned together, completely separate from stage 1. Restoring saves the selected older state as a new current version; existing history is preserved.</div></details>
          <div class="card panel">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><h3 style="margin:0">Saved versions</h3><button id="corrHistoryRefresh" class="btn">Reload history</button></div>
            <p class="mini"><strong>Restore this version</strong> saves the selected state again as the current correspondent configuration. The currently active state remains in history as its own version.</p>
            <div id="corrHistoryList"></div>
          </div>
        </div>
      </section>

      <section class="page" id="page-app-settings">
        <div class="page-head">
          <div><h1>App Settings</h1><p>General runtime settings are versioned and hot-reloaded by the workers. Only deployment values such as ports, volumes, CPU/RAM limits and the Paperless API token remain in <code>.env</code> because Docker or the secret is needed before the app starts.</p></div>
          <div id="appConfigStatus" class="config-badge">Loading…</div>
        </div>
        <div class="toolbar"><button id="appValidateBtn" class="btn">Validate configuration</button><button id="appSaveBtn" class="btn primary">Save changes</button><span id="appSaveStatus" class="toolbar-status">Nothing validated or saved yet.</span></div>
        <details class="section-help"><summary>Test before production.</summary><div class="help-body">Test Paperless/Ollama connections with the current unsaved draft, preview the exact prompts and run live model tests for both LLM stages without changing the document. Use Dry Run to validate automatic metadata processing before enabling metadata writes. The Paperless API token is never shown in the browser or stored in JSON.</div></details>

        <div class="tabs" data-tabs="app"><button class="tab active" data-tab="app-connections">Connections</button><button class="tab" data-tab="app-workflow">Pipeline &amp; Tags</button><button class="tab" data-tab="app-ocr">OCR</button><button class="tab" data-tab="app-runtime">Runtime</button><button class="tab" data-tab="app-history">History</button></div>

        <div class="tab-page active" id="app-connections">
          <details class="section-help"><summary>About connections</summary><div class="help-body">These URLs are shared by all components. The Paperless API token comes from the deployment environment and is only shown here as configured or missing.</div></details>
          <div class="connection-row">
            <div class="card connection">
              <h3>Paperless-ngx</h3>
              <div class="field"><label>Paperless URL <button type="button" class="info-btn" data-tip="Base URL of the Paperless instance, for example http://paperless:8000 or a reachable LAN address. No trailing slash is required.">i</button></label><input id="appPaperlessUrl" type="text"></div>
              <div class="field" style="margin-top:12px"><label>API token <button type="button" class="info-btn" data-tip="The token is a secret and therefore remains in .env or a Docker secret. It is never returned by this web UI.">i</button></label><div id="appTokenStatus" class="status-box">Loading…</div></div>
            </div>
            <div class="card connection"><h3>Ollama</h3><div class="field"><label>Ollama URL <button type="button" class="info-btn" data-tip="Base URL of an existing Ollama instance. paperless-local-ai does not install or start Ollama.">i</button></label><input id="appOllamaUrl" type="text"></div></div>
          </div>
          <div class="card panel" style="margin-top:14px">
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><button id="appConnectionTestBtn" class="btn good">Test connections with current draft</button><div id="appConnectionStatus" class="status-box" style="flex:1">Not tested yet.</div></div>
            <p class="mini">Tests the currently visible draft without saving it: Paperless including the token, plus Ollama's <code>/api/tags</code>.</p>
          </div>
        </div>

        <div class="tab-page" id="app-workflow">
          <details class="section-help"><summary>Pipeline &amp; tags</summary><div class="help-body">OCR is now part of the Paperless import path through OCRmyPDF and does not use queue tags. These three tags control metadata processing and human review. If you change a name, the corresponding tag must already exist in Paperless.</div></details>
          <div class="card panel"><div class="form-grid three">
            <div class="field"><label>LLM queue tag <button type="button" class="info-btn" data-tip="Assign this tag from a Paperless Document Added workflow after import/OCR completes; the metadata worker then classifies the document.">i</button></label><input id="appLlmQueueTag"></div>
            <div class="field"><label>LLM error tag <button type="button" class="info-btn" data-tip="Set when LLM classification fails.">i</button></label><input id="appLlmErrorTag"></div>
            <div class="field"><label>Review tag <button type="button" class="info-btn" data-tip="Documents remain under this tag for human review. Persistent correspondent suggestions are removed once the document leaves review.">i</button></label><input id="appReviewTag"></div>
            <div class="field"><label>Additional taxonomy-excluded tags <button type="button" class="info-btn" data-tip="Comma-separated additional tags that are never offered to the LLM as classification tags, for example TODO. The three technical tags above are excluded automatically.">i</button></label><input id="appExtraExcludedTags"></div>
          </div></div>
        </div>

        <div class="tab-page" id="app-ocr">
          <details class="section-help"><summary>OCR behavior</summary><div class="help-body">These values control selective PaddleOCR processing. They are reloaded before every poll, so no container restart is required. The original PDF is never modified.</div></details>
          <div class="card panel"><div class="form-grid three">
            <div class="field"><label>OCR language <button type="button" class="info-btn" data-tip="Language of the scanned document for PaddleOCR. Start typing a language name or code. This setting is independent of the Control Center and prompt language.">i</button></label><input id="appOcrLanguage" list="ocrLanguageOptions" autocomplete="off"><datalist id="ocrLanguageOptions">
              <option value="af">Afrikaans</option><option value="az">Azerbaijani</option><option value="bs">Bosnian</option><option value="ca">Catalan</option><option value="ch">Chinese (Simplified)</option><option value="chinese_cht">Chinese (Traditional)</option><option value="cs">Czech</option><option value="cy">Welsh</option><option value="da">Danish</option><option value="de">German</option><option value="en">English</option><option value="es">Spanish</option><option value="et">Estonian</option><option value="eu">Basque</option><option value="fi">Finnish</option><option value="fr">French</option><option value="ga">Irish</option><option value="gl">Galician</option><option value="hr">Croatian</option><option value="hu">Hungarian</option><option value="id">Indonesian</option><option value="is">Icelandic</option><option value="it">Italian</option><option value="japan">Japanese</option><option value="ku">Kurdish</option><option value="la">Latin</option><option value="lb">Luxembourgish</option><option value="lt">Lithuanian</option><option value="lv">Latvian</option><option value="mi">Maori</option><option value="ms">Malay</option><option value="mt">Maltese</option><option value="nl">Dutch</option><option value="no">Norwegian</option><option value="oc">Occitan</option><option value="pl">Polish</option><option value="pt">Portuguese</option><option value="qu">Quechua</option><option value="rm">Romansh</option><option value="ro">Romanian</option><option value="rs_latin">Serbian (Latin)</option><option value="sk">Slovak</option><option value="sl">Slovenian</option><option value="sq">Albanian</option><option value="sv">Swedish</option><option value="sw">Swahili</option><option value="tl">Tagalog</option><option value="tr">Turkish</option><option value="uz">Uzbek</option><option value="vi">Vietnamese</option>
            </datalist></div>
            <div class="field"><label>OCR version <button type="button" class="info-btn" data-tip="PaddleOCR model generation. Tested default: PP-OCRv6.">i</button></label><input id="appOcrVersion"></div>
            <div class="field"><label>Device <button type="button" class="info-btn" data-tip="PaddleOCR device. The tested low-power setup uses cpu.">i</button></label><input id="appOcrDevice"></div>
          </div></div>
        </div>

        <div class="tab-page" id="app-runtime">
          <details class="section-help"><summary>Runtime behavior</summary><div class="help-body">Configure worker intervals and safe operating mode. Docker resource limits remain deployment settings because the container runtime applies them before the app starts.</div></details>
          <div class="card panel"><div class="form-grid three">
            <div class="field"><label>Polling interval in seconds <button type="button" class="info-btn" data-tip="How often the OCR and metadata workers look for queued documents. Minimum: 5 seconds.">i</button></label><input id="appPollInterval" type="number"></div>
            <div class="field"><label>Review cleanup interval in seconds <button type="button" class="info-btn" data-tip="How often stale review records are removed when their document no longer carries the review tag. Default: 3600 = once per hour.">i</button></label><input id="appReviewPruneInterval" type="number"></div>
            <div class="field"><label>Dry Run <button type="button" class="info-btn" data-tip="In Dry Run, classification is executed and logged, but document metadata and persistent review suggestions are not written. Technical queue/error tags may still change.">i</button></label><select id="appDryRun"><option value="false">Off — write metadata to Paperless</option><option value="true">On — run without metadata writes</option></select></div>
          </div></div>
        </div>

        <div class="tab-page" id="app-history">
          <details class="section-help"><summary>Versioned app settings</summary><div class="help-body">Every save keeps the previous state in history. Restoring creates a new current version; existing history is preserved.</div></details>
          <div class="card panel">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px"><h3 style="margin:0">Saved versions</h3><button id="appHistoryRefresh" class="btn">Reload history</button></div>
            <div id="appHistoryList"></div>
          </div>
        </div>
      </section>

    </div>
  </main>
</div>
<script>
let currentConfig=null;
let currentAppConfig=null;
let currentCorrConfig=null;
let classPromptPresets={};
let corrPromptPresets={};
const $=id=>document.getElementById(id);

function renderPromptPresetOptions(selectId,presets){
  const select=$(selectId);const entries=Object.entries(presets||{});
  select.innerHTML='<option value="">Select a preset…</option>'+entries.map(([key,p])=>`<option value="${key}">${p.label||key}</option>`).join('');
}
function loadClassPromptPreset(){
  const preset=classPromptPresets[$('classPromptPreset').value];if(!preset)return;
  $('systemPrompt').value=preset.system_prompt;$('classificationTemplate').value=preset.classification_template;
  setStatus('saveStatus',`${preset.label||'Prompt'} preset loaded into draft · not saved yet.`);
}
function loadCorrPromptPreset(){
  const preset=corrPromptPresets[$('corrPromptPreset').value];if(!preset)return;
  $('corrSystemPrompt').value=preset.system_prompt;$('corrPromptTemplate').value=preset.prompt_template;
  setStatus('corrSaveStatus',`${preset.label||'Prompt'} preset loaded into draft · not saved yet.`);
}

const pageMeta={
  overview:["Overview","System overview and current configuration"],
  classification:["Classification","Primary local LLM metadata assignment"],
  correspondent:["Correspondent fallback","Optional sender-identification stage"],
  "app-settings":["App Settings","Shared connections, workflow, OCR and runtime settings"]
};

async function api(path,opts={}){
  const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});
  const t=await r.text();
  let data;
  try{data=JSON.parse(t)}catch{data={error:t}}
  if(!r.ok)throw new Error(data.error||`${r.status} ${r.statusText}`);
  return data;
}

function setStatus(id,msg,ok=true){
  const el=$(id);if(!el)return;
  el.textContent=msg;
  el.classList.toggle('good-text',ok);
  el.classList.toggle('bad-text',!ok);
  el.classList.toggle('good',ok&&el.classList.contains('status-box'));
  el.classList.toggle('bad',!ok&&el.classList.contains('status-box'));
}

function draft(){return {version:currentConfig?.version||1,updated_at:currentConfig?.updated_at||null,system_prompt:$('systemPrompt').value,classification_template:$('classificationTemplate').value,model:$('model').value.trim(),num_ctx:Number($('numCtx').value),num_predict:Number($('numPredict').value),temperature:Number($('temperature').value),think:$('think').value==='true',keep_alive:/^-?\d+(\.\d+)?$/.test($('keepAlive').value.trim())?Number($('keepAlive').value):$('keepAlive').value,content_char_limit:Number($('contentLimit').value),content_head_ratio:Number($('headRatio').value),max_tags:Number($('maxTags').value),ollama_timeout_seconds:Number($('ollamaTimeout').value)}}
function appDraft(){return {version:currentAppConfig?.version||1,updated_at:currentAppConfig?.updated_at||null,connections:{paperless_url:$('appPaperlessUrl').value.trim(),ollama_url:$('appOllamaUrl').value.trim()},workflow:{llm_queue_tag:$('appLlmQueueTag').value.trim(),llm_error_tag:$('appLlmErrorTag').value.trim(),review_tag:$('appReviewTag').value.trim(),extra_excluded_tags:$('appExtraExcludedTags').value.split(',').map(x=>x.trim()).filter(Boolean)},ocr:{language:$('appOcrLanguage').value.trim(),version:$('appOcrVersion').value.trim(),device:$('appOcrDevice').value.trim()},runtime:{poll_interval_seconds:Number($('appPollInterval').value),review_prune_interval_seconds:Number($('appReviewPruneInterval').value),dry_run:$('appDryRun').value==='true'}}}
function corrDraft(){return {version:currentCorrConfig?.version||1,updated_at:currentCorrConfig?.updated_at||null,enabled:$('corrEnabled').value==='true',system_prompt:$('corrSystemPrompt').value,prompt_template:$('corrPromptTemplate').value,model:$('corrModel').value.trim(),num_ctx:Number($('corrNumCtx').value),num_predict:Number($('corrNumPredict').value),temperature:Number($('corrTemperature').value),think:$('corrThink').value==='true',keep_alive:/^-?\d+(\.\d+)?$/.test($('corrKeepAlive').value.trim())?Number($('corrKeepAlive').value):$('corrKeepAlive').value,content_char_limit:Number($('corrContentLimit').value),content_head_ratio:Number($('corrHeadRatio').value),ollama_timeout_seconds:Number($('corrTimeout').value)}}

function updateOverview(){
  if(currentAppConfig){
    const dry=currentAppConfig.runtime.dry_run;
    const mode=dry?'DRY RUN':'PRODUCTION';
    $('overviewMode').textContent=mode;
    $('overviewMode').className=dry?'warn-text':'good-text';
    $('topModeStatus').textContent=mode;
    $('topModeStatus').className='pill '+(dry?'warn':'good');
    $('sidebarMode').textContent=mode;
    $('sidebarAppVersion').textContent=`AppConfig v${currentAppConfig.version}`;
    $('overviewPaperlessDetail').textContent=currentAppConfig.connections.paperless_url;
    $('overviewOllamaDetail').textContent=currentAppConfig.connections.ollama_url;
    $('overviewOcrStatus').textContent='Ready';
    $('overviewOcrStatus').className='metric-value good-text';
    $('overviewOcrCard').classList.add('good');
    $('overviewOcrDetail').textContent=`${currentAppConfig.ocr.version} · ${currentAppConfig.ocr.language} · ${currentAppConfig.ocr.device.toUpperCase()}`;
    $('overviewPoll').textContent=`${currentAppConfig.runtime.poll_interval_seconds} seconds`;
    $('overviewCleanup').textContent=`${currentAppConfig.runtime.review_prune_interval_seconds} seconds`;
  }
  if(currentConfig){
    $('overviewClassification').textContent=`v${currentConfig.version} · ${currentConfig.model}`;
    $('overviewMaxTags').textContent=String(currentConfig.max_tags);
  }
  if(currentCorrConfig){
    $('overviewCorrStatus').textContent=currentCorrConfig.enabled?'Enabled':'Disabled';
    $('overviewCorrStatus').className='metric-value '+(currentCorrConfig.enabled?'good-text':'muted');
    $('overviewCorrCard').classList.toggle('good',currentCorrConfig.enabled);
    $('overviewCorrDetail').textContent=`v${currentCorrConfig.version} · ${currentCorrConfig.model}`;
    $('overviewCorrConfig').textContent=`v${currentCorrConfig.version} · ${currentCorrConfig.enabled?'enabled':'disabled'}`;
  }
  const model=currentConfig?.model||currentCorrConfig?.model;
  const device=currentAppConfig?.ocr?.device;
  if(model||device)$('sidebarModel').textContent=[model,device?.toUpperCase()].filter(Boolean).join(' · ');
}

function applyConnectionResult(r){
  const items=[['paperless','overviewPaperlessCard','overviewPaperlessStatus','overviewPaperlessDetail'],['ollama','overviewOllamaCard','overviewOllamaStatus','overviewOllamaDetail']];
  for(const [key,cardId,statusId,detailId] of items){
    const result=r[key];const card=$(cardId);const status=$(statusId);
    card.classList.toggle('good',!!result?.ok);card.classList.toggle('bad',!result?.ok);
    status.textContent=result?.ok?'Connected':'Connection error';
    status.className='metric-value '+(result?.ok?'good-text':'bad-text');
    const base=key==='paperless'?currentAppConfig?.connections?.paperless_url:currentAppConfig?.connections?.ollama_url;
    $(detailId).textContent=[base,result?.detail].filter(Boolean).join(' · ');
  }
}
async function checkOverviewConnections(config){
  try{applyConnectionResult(await api('/api/app/connections/test',{method:'POST',body:JSON.stringify({config})}))}
  catch(e){
    for(const id of ['overviewPaperlessStatus','overviewOllamaStatus']){$(id).textContent='Check failed';$(id).className='metric-value bad-text'}
  }
}

function fill(c){
  currentConfig=c;
  $('systemPrompt').value=c.system_prompt;$('classificationTemplate').value=c.classification_template;$('model').value=c.model;$('numCtx').value=c.num_ctx;$('numPredict').value=c.num_predict;$('temperature').value=c.temperature;$('think').value=String(c.think);$('keepAlive').value=c.keep_alive;$('contentLimit').value=c.content_char_limit;$('headRatio').value=c.content_head_ratio;$('maxTags').value=c.max_tags;$('ollamaTimeout').value=c.ollama_timeout_seconds;
  $('classConfigStatus').textContent=`Active configuration · v${c.version} · ${c.model}`;updateOverview();
}
function appFill(c,tokenConfigured){
  currentAppConfig=c;
  $('appPaperlessUrl').value=c.connections.paperless_url;$('appOllamaUrl').value=c.connections.ollama_url;$('appLlmQueueTag').value=c.workflow.llm_queue_tag;$('appLlmErrorTag').value=c.workflow.llm_error_tag;$('appReviewTag').value=c.workflow.review_tag;$('appExtraExcludedTags').value=(c.workflow.extra_excluded_tags||[]).join(', ');$('appOcrLanguage').value=c.ocr.language;$('appOcrVersion').value=c.ocr.version;$('appOcrDevice').value=c.ocr.device;$('appPollInterval').value=c.runtime.poll_interval_seconds;$('appReviewPruneInterval').value=c.runtime.review_prune_interval_seconds;$('appDryRun').value=String(c.runtime.dry_run);
  $('appConfigStatus').textContent=`v${c.version} · ${c.runtime.dry_run?'DRY RUN':'PRODUCTION'}`;$('appConfigStatus').style.color=c.runtime.dry_run?'var(--orange)':'var(--green)';
  $('appTokenStatus').textContent=tokenConfigured?'API token is configured in the deployment environment.':'API token is missing from the deployment environment.';$('appTokenStatus').className='status-box '+(tokenConfigured?'good':'bad');updateOverview();
}
function corrFill(c){
  currentCorrConfig=c;
  $('corrEnabled').value=String(c.enabled);$('corrSystemPrompt').value=c.system_prompt;$('corrPromptTemplate').value=c.prompt_template;$('corrModel').value=c.model;$('corrNumCtx').value=c.num_ctx;$('corrNumPredict').value=c.num_predict;$('corrTemperature').value=c.temperature;$('corrThink').value=String(c.think);$('corrKeepAlive').value=c.keep_alive;$('corrContentLimit').value=c.content_char_limit;$('corrHeadRatio').value=c.content_head_ratio;$('corrTimeout').value=c.ollama_timeout_seconds;
  $('corrConfigStatus').textContent=`${c.enabled?'PRODUCTION ON':'PRODUCTION OFF'} · v${c.version} · ${c.model}`;$('corrConfigStatus').style.color=c.enabled?'var(--green)':'var(--muted)';updateOverview();
}

function renderHistory(items,id,restoreFn){
  const el=$(id);
  el.innerHTML=items.length?items.map(x=>`<div class="history-item"><span class="badge">v${x.version??'?'}</span><span>${x.file}</span><span class="mini">${x.updated_at||''}<br>${(x.config_sha256||'').slice(0,16)}</span><button class="btn" onclick="${restoreFn}('${x.file}')">Restore this version</button></div>`).join(''):'<p class="mini">No older saved version yet.</p>';
}
function renderAppHistory(items){renderHistory(items,'appHistoryList','restoreAppHistory')}
function renderCorrHistory(items){renderHistory(items,'corrHistoryList','restoreCorrHistory')}

async function init(){
  try{const s=await api('/api/state');classPromptPresets=s.presets||{};renderPromptPresetOptions('classPromptPreset',classPromptPresets);fill(s.config);$('placeholders').innerHTML=Object.entries(s.placeholders).map(([k,v])=>`<div class="placeholder-item"><code>{{${k}}}</code><span>${v}</span></div>`).join('');await loadHistory();$('topStatus').textContent='Control Center ready';$('topStatus').className='pill good'}
  catch(e){$('topStatus').textContent=e.message;$('topStatus').className='pill bad'}
}
async function loadApp(){
  try{const r=await api('/api/app/state');appFill(r.config,r.token_configured);renderAppHistory(r.history||[]);checkOverviewConnections(r.config)}
  catch(e){$('appConfigStatus').textContent='Error';$('appConfigStatus').style.color='var(--red)';setStatus('appSaveStatus',e.message,false)}
}
async function loadCorrespondent(){
  try{const s=await api('/api/correspondent/state');corrPromptPresets=s.presets||{};renderPromptPresetOptions('corrPromptPreset',corrPromptPresets);corrFill(s.config);$('corrPlaceholders').innerHTML=Object.entries(s.placeholders).map(([k,v])=>`<div class="placeholder-item"><code>{{${k}}}</code><span>${v}</span></div>`).join('');renderCorrHistory(s.history||[])}
  catch(e){$('corrConfigStatus').textContent='Error';$('corrConfigStatus').style.color='var(--red)';setStatus('corrSaveStatus',e.message,false)}
}

$('classLoadPresetBtn').onclick=loadClassPromptPreset;
$('corrLoadPresetBtn').onclick=loadCorrPromptPreset;

$('validateBtn').onclick=async()=>{try{const r=await api('/api/config/validate',{method:'POST',body:JSON.stringify({config:draft()})});setStatus('saveStatus',`Configuration valid · not saved yet · SHA ${r.config_sha256.slice(0,12)}`)}catch(e){setStatus('saveStatus',e.message,false)}};
$('saveBtn').onclick=async()=>{try{const r=await api('/api/config/save',{method:'POST',body:JSON.stringify({config:draft()})});fill(r.config);setStatus('saveStatus',`Saved and active from the next classification job · v${r.config.version}`);await loadHistory()}catch(e){setStatus('saveStatus',e.message,false)}};
async function doPreview(run){const id=Number($('docId').value);if(!id)return;setStatus('testStatus',run?'Model test running…':'Preparing final prompt…');try{const r=await api(run?'/api/test':'/api/preview',{method:'POST',body:JSON.stringify({document_id:id,config:draft()})});$('systemPreview').textContent=r.rendered.system_prompt;$('userPreview').textContent=r.rendered.user_prompt;$('schemaPreview').textContent=JSON.stringify(r.rendered.schema,null,2);$('taxonomyPreview').textContent=JSON.stringify(r.taxonomy,null,2);$('previewMeta').textContent=JSON.stringify(r.meta,null,2);$('testResult').textContent=run?JSON.stringify({suggestion:r.suggestion,validation_errors:r.validation_errors,performance:r.performance},null,2):'';setStatus('testStatus',run?'Model test complete · Paperless was not modified.':'Final prompt previewed · the model was not called.')}catch(e){setStatus('testStatus',e.message,false)}}
$('previewBtn').onclick=()=>doPreview(false);$('testBtn').onclick=()=>doPreview(true);

$('appValidateBtn').onclick=async()=>{try{const r=await api('/api/app/validate',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appSaveStatus',`Configuration valid · not saved yet · SHA ${r.config_sha256.slice(0,12)}`)}catch(e){setStatus('appSaveStatus',e.message,false)}};
$('appSaveBtn').onclick=async()=>{try{const r=await api('/api/app/save',{method:'POST',body:JSON.stringify({config:appDraft()})});appFill(r.config,r.token_configured);setStatus('appSaveStatus',`Saved · AppConfig v${r.config.version}. Workers reload runtime settings automatically.`);renderAppHistory(r.history||[]);checkOverviewConnections(r.config)}catch(e){setStatus('appSaveStatus',e.message,false)}};
$('appConnectionTestBtn').onclick=async()=>{setStatus('appConnectionStatus','Testing connections…');try{const r=await api('/api/app/connections/test',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appConnectionStatus',`Paperless: ${r.paperless.ok?'OK':'ERROR'}${r.paperless.detail?' · '+r.paperless.detail:''}\nOllama: ${r.ollama.ok?'OK':'ERROR'}${r.ollama.detail?' · '+r.ollama.detail:''}`,r.paperless.ok&&r.ollama.ok);applyConnectionResult(r)}catch(e){setStatus('appConnectionStatus',e.message,false)}};
async function refreshAppHistory(){const r=await api('/api/app/history');renderAppHistory(r.items||[])}
$('appHistoryRefresh').onclick=()=>refreshAppHistory().catch(e=>setStatus('appSaveStatus',e.message,false));
window.restoreAppHistory=async file=>{if(!confirm(`Restore these app settings? The selected state will be saved as a new current version; the current state remains in history.\n\nFile: ${file}`))return;try{const r=await api('/api/app/history/restore',{method:'POST',body:JSON.stringify({file})});appFill(r.config,r.token_configured);renderAppHistory(r.history||[]);setStatus('appSaveStatus',`Restored and saved as a new current version · v${r.config.version}`);checkOverviewConnections(r.config)}catch(e){alert(e.message)}};

$('corrValidateBtn').onclick=async()=>{try{const r=await api('/api/correspondent/validate',{method:'POST',body:JSON.stringify({config:corrDraft()})});setStatus('corrSaveStatus',`Configuration valid · not saved yet · SHA ${r.config_sha256.slice(0,12)}`)}catch(e){setStatus('corrSaveStatus',e.message,false)}};
$('corrSaveBtn').onclick=async()=>{try{const r=await api('/api/correspondent/save',{method:'POST',body:JSON.stringify({config:corrDraft()})});corrFill(r.config);setStatus('corrSaveStatus',`Saved as v${r.config.version} · production fallback ${r.config.enabled?'ON':'OFF'}`);await refreshCorrHistory()}catch(e){setStatus('corrSaveStatus',e.message,false)}};
async function corrPreview(run){const id=Number($('corrDocId').value);if(!id)return;setStatus('corrTestStatus',run?'Model test running…':'Preparing final prompt…');try{const r=await api(run?'/api/correspondent/test':'/api/correspondent/preview',{method:'POST',body:JSON.stringify({document_id:id,config:corrDraft()})});$('corrSystemPreview').textContent=r.rendered.system_prompt;$('corrUserPreview').textContent=r.rendered.user_prompt;$('corrSchemaPreview').textContent=JSON.stringify(r.rendered.schema,null,2);$('corrPreviewMeta').textContent=JSON.stringify(r.meta,null,2);$('corrTestResult').textContent=run?JSON.stringify({suggestion:r.suggestion,validation_errors:r.validation_errors,performance:r.performance},null,2):'';setStatus('corrTestStatus',run?'Model test complete · Paperless was not modified and no correspondent suggestion was saved.':'Final prompt previewed · the model was not called.')}catch(e){setStatus('corrTestStatus',e.message,false)}}
$('corrPreviewBtn').onclick=()=>corrPreview(false);$('corrTestBtn').onclick=()=>corrPreview(true);
async function refreshCorrHistory(){const s=await api('/api/correspondent/state');renderCorrHistory(s.history||[])}
$('corrHistoryRefresh').onclick=()=>refreshCorrHistory().catch(e=>setStatus('corrSaveStatus',e.message,false));
window.restoreCorrHistory=async file=>{if(!confirm(`Restore this correspondent version? The selected state will be saved as a new current version; the current state remains in history.\n\nFile: ${file}`))return;try{const r=await api('/api/correspondent/history/restore',{method:'POST',body:JSON.stringify({file})});corrFill(r.config);setStatus('corrSaveStatus',`Restored and saved as a new current version · v${r.config.version}`);await refreshCorrHistory()}catch(e){alert(e.message)}};

async function loadHistory(){try{const r=await api('/api/history');renderHistory(r.items||[],'historyList','restoreHistory')}catch(e){$('historyList').textContent=e.message}}
window.restoreHistory=async file=>{if(!confirm(`Restore this classification version? The selected state will be saved as a new current version; the current state remains in history.\n\nFile: ${file}`))return;try{const r=await api('/api/history/restore',{method:'POST',body:JSON.stringify({file})});fill(r.config);setStatus('saveStatus',`Restored and saved as a new current version · v${r.config.version}`);await loadHistory()}catch(e){alert(e.message)}};
$('historyRefresh').onclick=loadHistory;

function activatePage(page){
  if(!pageMeta[page])page='overview';
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
  document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===`page-${page}`));
  $('topTitle').textContent=pageMeta[page][0];$('topSubtitle').textContent=pageMeta[page][1];
  try{localStorage.setItem('paperlessControlCenterPage',page)}catch{}
}
function activateTab(group,id){
  const nav=document.querySelector(`.tabs[data-tabs="${group}"]`);const target=$(id);if(!nav||!target)return;
  nav.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===id));
  nav.closest('.page').querySelectorAll('.tab-page').forEach(x=>x.classList.toggle('active',x.id===id));
  try{localStorage.setItem(`paperlessControlCenterTab:${group}`,id)}catch{}
}
document.querySelectorAll('.nav-btn').forEach(b=>b.onclick=()=>activatePage(b.dataset.page));
document.querySelectorAll('.tabs .tab').forEach(b=>b.onclick=()=>activateTab(b.closest('.tabs').dataset.tabs,b.dataset.tab));
for(const [group,fallback] of [['classification','class-prompt'],['correspondent','corr-prompt'],['app','app-connections']]){let tab=fallback;try{tab=localStorage.getItem(`paperlessControlCenterTab:${group}`)||fallback}catch{}activateTab(group,tab)}
let initialPage='overview';try{initialPage=localStorage.getItem('paperlessControlCenterPage')||initialPage}catch{}activatePage(initialPage);

document.querySelectorAll('.info-btn').forEach(btn=>{btn.addEventListener('click',e=>{e.stopPropagation();document.querySelectorAll('.info-btn.open').forEach(x=>{if(x!==btn)x.classList.remove('open')});btn.classList.toggle('open')})});
document.addEventListener('click',()=>document.querySelectorAll('.info-btn.open').forEach(x=>x.classList.remove('open')));

init();loadCorrespondent();loadApp();
</script>
</body>
</html>
'''


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
                "presets": PROMPT_PRESETS,
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
                "presets": CORRESPONDENT_PROMPT_PRESETS,
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
