(() => {
  "use strict";

  const APP_ID = "paperless-local-ai-chat-host";
  const BUTTON_ID = "paperless-local-ai-chat-button";
  const SETTINGS_LINK_ID = "paperless-local-ai-settings-link";
  const STORAGE_KEY = "paperless-local-ai-rag-chat-v1";

  const baseHref = document.querySelector("base")?.getAttribute("href") || "/";
  const appBase = new URL(baseHref, window.location.origin);
  const appBasePath = appBase.pathname.endsWith("/") ? appBase.pathname : `${appBase.pathname}/`;
  const apiUrl = (path) => `${appBasePath}_plai/${path.replace(/^\/+/, "")}`;
  const documentUrl = (id) => new URL(`documents/${id}/details`, appBase).toString();

  function cookie(name) {
    const needle = `${encodeURIComponent(name)}=`;
    for (const raw of document.cookie.split(";")) {
      const item = raw.trim();
      if (item.startsWith(needle)) return decodeURIComponent(item.slice(needle.length));
    }
    return "";
  }

  function csrfToken() {
    const prefix = document.querySelector('meta[name="cookie_prefix"]')?.content || "";
    return cookie(`${prefix}csrftoken`);
  }

  async function api(path, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const headers = new Headers(options.headers || {});
    headers.set("Accept", "application/json");
    if (method !== "GET" && method !== "HEAD") {
      headers.set("Content-Type", "application/json");
      const token = csrfToken();
      if (token) headers.set("X-CSRFToken", token);
    }
    const response = await fetch(apiUrl(path), {
      ...options,
      method,
      headers,
      credentials: "same-origin",
      redirect: "error",
    });
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch (_error) {
      payload = { error: text || `HTTP ${response.status}` };
    }
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  }

  function currentDocumentId() {
    let path = window.location.pathname;
    if (appBasePath !== "/" && path.startsWith(appBasePath)) path = path.slice(appBasePath.length - 1);
    const match = path.match(/\/documents\/(\d+)(?:\/|$)/);
    return match ? Number(match[1]) : null;
  }

  function relativePath() {
    let path = window.location.pathname;
    if (appBasePath !== "/" && path.startsWith(appBasePath)) path = path.slice(appBasePath.length);
    return path.replace(/^\/+|\/+$/g, "");
  }

  function loadStored() {
    try {
      const value = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}");
      return value && typeof value === "object" ? value : {};
    } catch (_error) {
      return {};
    }
  }

  function saveStored(state) {
    const payload = {
      messages: state.messages,
      settings: state.settings,
      scope: state.scope,
      conversationDocumentId: state.conversationDocumentId,
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }

  function formatSeconds(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return "";
    return number < 10 ? `${number.toFixed(2)} s` : `${number.toFixed(1)} s`;
  }

  async function bootstrap() {
    return api("bootstrap");
  }

  function addSettingsShortcut(controlCenterUrl) {
    const existing = document.getElementById(SETTINGS_LINK_ID);
    const path = relativePath();
    if (!(path === "settings" || path.startsWith("settings/"))) {
      existing?.remove();
      return;
    }
    const admin = [...document.querySelectorAll("a[href]")].find((link) => {
      const href = link.getAttribute("href") || "";
      return href === "admin/" || href.endsWith("/admin/");
    });
    if (!admin) return;
    if (existing?.isConnected) return;
    const link = document.createElement("a");
    link.id = SETTINGS_LINK_ID;
    link.className = "btn btn-sm btn-outline-primary me-1";
    link.href = controlCenterUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = "Open paperless-local-ai Control Center";
    link.textContent = "paperless-local-ai ↗";
    admin.parentNode?.insertBefore(link, admin);
  }

  function hideNativeChat() {
    const nativeButton = document.getElementById("chatDropdown");
    if (!nativeButton) return null;
    const nativeRoot = nativeButton.closest("pngx-chat") || nativeButton.parentElement;
    if (nativeRoot) {
      nativeRoot.style.setProperty("display", "none", "important");
      nativeRoot.setAttribute("data-paperless-local-ai-native-chat-hidden", "true");
    }
    return nativeRoot;
  }

  function ensureButton(openPanel) {
    let button = document.getElementById(BUTTON_ID);
    if (!button) {
      button = document.createElement("button");
      button.id = BUTTON_ID;
      button.type = "button";
      button.title = "paperless-local-ai chat";
      button.setAttribute("aria-label", "Open paperless-local-ai chat");
      button.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M4 4h16v12H7.5L4 19.5V4Zm2 2v9.3l.7-.7.6-.6H18V6H6Z"/></svg>';
      Object.assign(button.style, {
        border: "0",
        background: "transparent",
        color: "inherit",
        cursor: "pointer",
        fontSize: "1.15rem",
        lineHeight: "1",
        padding: ".45rem .55rem",
        borderRadius: ".375rem",
      });
      button.addEventListener("click", openPanel);
    }

    const nativeRoot = hideNativeChat();
    const toastRoot = document.querySelector("pngx-toasts-dropdown");
    const anchor = nativeRoot || toastRoot;
    if (anchor?.parentNode && button.parentNode !== anchor.parentNode) {
      anchor.parentNode.insertBefore(button, anchor);
      button.style.position = "";
      button.style.right = "";
      button.style.bottom = "";
      button.style.zIndex = "";
    } else if (!button.isConnected) {
      document.body.appendChild(button);
      Object.assign(button.style, {
        position: "fixed",
        right: "1rem",
        bottom: "1rem",
        zIndex: "2147483000",
        background: "var(--bs-body-bg, white)",
        boxShadow: "0 2px 12px rgba(0,0,0,.22)",
      });
    }
    return button;
  }

  function makePanel(boot) {
    const host = document.createElement("div");
    host.id = APP_ID;
    document.body.appendChild(host);
    const root = host.attachShadow({ mode: "open" });
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = apiUrl("assets/chat.css");
    root.appendChild(stylesheet);

    const shell = document.createElement("section");
    shell.className = "shell hidden";
    shell.innerHTML = `
      <header class="header">
        <div>
          <strong>paperless-local-ai</strong>
          <span class="sub">RAG chat</span>
        </div>
        <div class="header-actions">
          <button type="button" data-action="new" title="New chat">＋</button>
          <button type="button" data-action="settings" title="Chat settings">⚙</button>
          <button type="button" data-action="close" title="Close">×</button>
        </div>
      </header>
      <div class="toolbar">
        <label>Search in
          <select data-field="scope">
            <option value="document">Current document</option>
            <option value="all">All documents</option>
          </select>
        </label>
        <label>Model
          <input data-field="model" list="plai-models" autocomplete="off">
          <datalist id="plai-models"></datalist>
        </label>
      </div>
      <div class="settings hidden" data-part="settings">
        <div class="settings-grid">
          <label>Thinking
            <select data-field="think"><option value="auto">Auto</option><option value="off">Off</option><option value="on">On</option></select>
          </label>
          <label>Context
            <input data-field="num_ctx" type="number" min="2048" max="131072" step="1024">
          </label>
          <label>Retrieval Top-K
            <input data-field="top_k" type="number" min="1" max="12" step="1">
          </label>
          <label>Temperature
            <input data-field="temperature" type="number" min="0" max="2" step="0.1">
          </label>
          <label>Max output tokens
            <input data-field="num_predict" type="number" min="64" max="4096" step="64">
          </label>
        </div>
        <div class="index-box">
          <div class="index-head"><strong>Index</strong><span data-part="index-state">Loading…</span></div>
          <div class="progress"><span data-part="index-progress"></span></div>
          <div class="index-actions">
            <button type="button" data-action="sync">Sync</button>
            <button type="button" data-action="rebuild">Rebuild</button>
            <button type="button" data-action="pause">Pause</button>
          </div>
          <small data-part="index-detail"></small>
        </div>
      </div>
      <main class="messages" data-part="messages"></main>
      <div class="phase" data-part="phase"></div>
      <footer class="composer">
        <textarea data-field="question" rows="2" placeholder="Ask about your Paperless documents…"></textarea>
        <div class="composer-actions">
          <button type="button" class="stop hidden" data-action="stop">Stop</button>
          <button type="button" class="send" data-action="send">Send</button>
        </div>
      </footer>
    `;
    root.appendChild(shell);

    const stored = loadStored();
    const defaults = boot.config?.chat_defaults || {};
    const restoredMessages = Array.isArray(stored.messages)
      ? stored.messages.map((message) => message?.pending
        ? { ...message, pending: false, content: message.content || "Previous request was interrupted." }
        : message)
      : [];
    const state = {
      shell,
      root,
      open: false,
      messages: restoredMessages,
      settings: { ...defaults, ...(stored.settings || {}) },
      scope: stored.scope || (currentDocumentId() ? "document" : "all"),
      conversationDocumentId: stored.conversationDocumentId || null,
      jobId: null,
      pollTimer: null,
      indexTimer: null,
      indexState: boot.state || {},
      controlCenterUrl: boot.control_center_url,
    };

    const q = (selector) => root.querySelector(selector);
    const fields = {
      scope: q('[data-field="scope"]'),
      model: q('[data-field="model"]'),
      think: q('[data-field="think"]'),
      num_ctx: q('[data-field="num_ctx"]'),
      top_k: q('[data-field="top_k"]'),
      temperature: q('[data-field="temperature"]'),
      num_predict: q('[data-field="num_predict"]'),
      question: q('[data-field="question"]'),
    };

    function normalizeSettings() {
      return {
        model: String(fields.model.value || defaults.model || "").trim(),
        think: String(fields.think.value || "off"),
        num_ctx: Number(fields.num_ctx.value || 8192),
        top_k: Number(fields.top_k.value || 5),
        temperature: Number(fields.temperature.value || 0.1),
        num_predict: Number(fields.num_predict.value || 512),
      };
    }

    function fillSettings() {
      fields.scope.value = state.scope;
      fields.model.value = state.settings.model || defaults.model || "";
      fields.think.value = state.settings.think || defaults.think || "off";
      fields.num_ctx.value = state.settings.num_ctx || defaults.num_ctx || 8192;
      fields.top_k.value = state.settings.top_k || defaults.top_k || 5;
      fields.temperature.value = state.settings.temperature ?? defaults.temperature ?? 0.1;
      fields.num_predict.value = state.settings.num_predict || defaults.num_predict || 512;
    }

    function sourceNode(source) {
      const link = document.createElement("a");
      link.className = "source";
      link.href = documentUrl(source.document_id);
      link.target = "_self";
      const refs = Array.isArray(source.source_numbers) && source.source_numbers.length
        ? `[${source.source_numbers.join(", ")}] `
        : "";
      link.textContent = `${refs}📄 ${source.title || `Document ${source.document_id}`}`;
      return link;
    }

    function renderMessages() {
      const container = q('[data-part="messages"]');
      container.replaceChildren();
      if (!state.messages.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.innerHTML = "<strong>Ask your archive.</strong><span>Use Current document for a focused question or All documents for archive-wide retrieval.</span>";
        container.appendChild(empty);
        return;
      }
      for (const message of state.messages) {
        const wrapper = document.createElement("article");
        wrapper.className = `message ${message.role}`;
        const label = document.createElement("div");
        label.className = "message-label";
        label.textContent = message.role === "user" ? "You" : "PLAI";
        const body = document.createElement("div");
        body.className = "message-body";
        body.textContent = message.content || (message.pending ? "…" : "");
        wrapper.append(label, body);
        if (Array.isArray(message.sources) && message.sources.length) {
          const sources = document.createElement("div");
          sources.className = "sources";
          for (const source of message.sources) sources.appendChild(sourceNode(source));
          wrapper.appendChild(sources);
        }
        if (message.metrics?.total_seconds) {
          const metrics = document.createElement("small");
          metrics.className = "metrics";
          metrics.textContent = `Total ${formatSeconds(message.metrics.total_seconds)} · embed ${formatSeconds(message.metrics.embedding_seconds)} · retrieval ${formatSeconds(message.metrics.retrieval_seconds)} · LLM ${formatSeconds(message.metrics.generation_seconds)}`;
          wrapper.appendChild(metrics);
        }
        container.appendChild(wrapper);
      }
      container.scrollTop = container.scrollHeight;
    }

    function setPhase(text = "") {
      q('[data-part="phase"]').textContent = text;
    }

    function setRunning(running) {
      q('[data-action="send"]').disabled = running;
      q('[data-action="stop"]').classList.toggle("hidden", !running);
      fields.question.disabled = running;
    }

    function phaseLabel(job) {
      const labels = {
        embedding: "Embedding question…",
        retrieval: "Retrieving relevant chunks…",
        generation: "Generating answer…",
        stopped: "Stopped",
        error: "Error",
      };
      return labels[job.phase] || "";
    }

    function finishJob(job) {
      const assistant = [...state.messages].reverse().find((item) => item.role === "assistant" && item.pending);
      if (assistant) {
        assistant.pending = false;
        assistant.content = job.answer || assistant.content || "";
        assistant.sources = job.sources || [];
        assistant.metrics = job.metrics || {};
        if (job.status === "error") assistant.content = `Error: ${job.error || "Unknown RAG error"}`;
        if (job.status === "stopped" && !assistant.content) assistant.content = "Stopped.";
      }
      state.jobId = null;
      if (state.pollTimer) clearTimeout(state.pollTimer);
      state.pollTimer = null;
      setRunning(false);
      setPhase(job.status === "error" ? job.error || "Error" : "");
      saveStored(state);
      renderMessages();
    }

    async function pollJob() {
      if (!state.jobId) return;
      try {
        const job = await api("chat/status", {
          method: "POST",
          body: JSON.stringify({ job_id: state.jobId }),
        });
        const assistant = [...state.messages].reverse().find((item) => item.role === "assistant" && item.pending);
        if (assistant) {
          assistant.content = job.answer || "";
          assistant.sources = job.sources || [];
          renderMessages();
        }
        setPhase(phaseLabel(job));
        if (["done", "error", "stopped"].includes(job.status)) {
          finishJob(job);
          return;
        }
      } catch (error) {
        setPhase(error.message);
      }
      state.pollTimer = setTimeout(pollJob, 400);
    }

    async function send() {
      const question = fields.question.value.trim();
      if (!question || state.jobId) return;
      state.scope = fields.scope.value;
      state.settings = normalizeSettings();
      const docId = currentDocumentId();
      if (state.scope === "document" && !docId) {
        setPhase("Open a document first, or switch the scope to All documents.");
        return;
      }
      if (state.scope === "document" && state.conversationDocumentId && state.conversationDocumentId !== docId) {
        state.messages = [];
      }
      state.conversationDocumentId = state.scope === "document" ? docId : null;

      const history = state.messages
        .filter((item) => !item.pending && ["user", "assistant"].includes(item.role))
        .map(({ role, content }) => ({ role, content }));
      state.messages.push({ role: "user", content: question });
      state.messages.push({ role: "assistant", content: "", pending: true, sources: [] });
      fields.question.value = "";
      renderMessages();
      setRunning(true);
      setPhase("Starting…");
      saveStored(state);

      try {
        const started = await api("chat/start", {
          method: "POST",
          body: JSON.stringify({
            question,
            history,
            scope: state.scope === "document" ? "document" : "all",
            document_id: state.scope === "document" ? docId : null,
            settings: state.settings,
          }),
        });
        state.jobId = started.job_id;
        pollJob();
      } catch (error) {
        finishJob({ status: "error", phase: "error", error: error.message, answer: "" });
      }
    }

    async function stop() {
      if (!state.jobId) return;
      try {
        await api("chat/stop", {
          method: "POST",
          body: JSON.stringify({ job_id: state.jobId }),
        });
        setPhase("Stopping…");
      } catch (error) {
        setPhase(error.message);
      }
    }

    async function refreshModels() {
      try {
        const payload = await api("models");
        const list = q("#plai-models");
        list.replaceChildren();
        for (const model of payload.models || []) {
          const option = document.createElement("option");
          option.value = model;
          list.appendChild(option);
        }
      } catch (_error) {
        // Free model entry remains usable if /api/tags is unavailable.
      }
    }

    function renderIndex(payload) {
      const idx = payload.state || {};
      state.indexState = idx;
      const stateNode = q('[data-part="index-state"]');
      const detail = q('[data-part="index-detail"]');
      const bar = q('[data-part="index-progress"]');
      const pauseButton = q('[data-action="pause"]');
      let label = idx.index_exists ? `${idx.indexed_documents || 0} docs · ${idx.indexed_chunks || 0} chunks` : "Not built";
      if (idx.running) label = `${idx.operation || "index"}: ${idx.phase || "running"}`;
      if (idx.paused) label = "Paused";
      if (idx.last_error) label = `Error: ${idx.last_error}`;
      stateNode.textContent = label;
      const total = Number(idx.total || 0);
      const current = Number(idx.current || 0);
      const percent = total > 0 ? Math.max(0, Math.min(100, (current / total) * 100)) : 0;
      bar.style.width = `${percent}%`;
      detail.textContent = total > 0 ? `${current} / ${total}${idx.last_sync ? ` · last sync ${idx.last_sync}` : ""}` : (idx.last_sync ? `Last sync ${idx.last_sync}` : "Initial rebuild is explicit.");
      pauseButton.textContent = idx.paused ? "Resume" : "Pause";
    }

    async function refreshIndex() {
      if (state.indexTimer) clearTimeout(state.indexTimer);
      state.indexTimer = null;
      try {
        renderIndex(await api("status"));
      } catch (error) {
        q('[data-part="index-state"]').textContent = error.message;
      }
      if (state.open) state.indexTimer = setTimeout(refreshIndex, 3000);
    }

    async function indexAction(action) {
      try {
        if (action === "rebuild" && !window.confirm("Rebuild the complete PLAI RAG index? The current index stays usable until the rebuild is activated.")) return;
        if (action === "pause") {
          const resume = !!state.indexState.paused;
          const operation = state.indexState.operation;
          await api("index/pause", { method: "POST", body: JSON.stringify({ paused: !resume }) });
          if (resume && operation === "rebuild") await api("index/rebuild", { method: "POST", body: "{}" });
          if (resume && operation === "sync") await api("index/sync", { method: "POST", body: "{}" });
        } else {
          await api(`index/${action}`, { method: "POST", body: "{}" });
        }
        await refreshIndex();
      } catch (error) {
        setPhase(error.message);
      }
    }

    function newChat() {
      if (state.jobId) stop();
      state.messages = [];
      state.conversationDocumentId = null;
      saveStored(state);
      renderMessages();
      setPhase("");
      fields.question.focus();
    }

    function open() {
      state.open = true;
      shell.classList.remove("hidden");
      fillSettings();
      renderMessages();
      refreshModels();
      if (state.indexTimer) clearTimeout(state.indexTimer);
      refreshIndex();
      if (!state.indexState?.index_exists) setPhase("RAG index not built yet. Open settings and run Rebuild.");
      setTimeout(() => fields.question.focus(), 0);
    }

    function close() {
      state.open = false;
      shell.classList.add("hidden");
      if (state.indexTimer) clearTimeout(state.indexTimer);
      state.indexTimer = null;
      state.scope = fields.scope.value;
      state.settings = normalizeSettings();
      saveStored(state);
    }

    q('[data-action="close"]').addEventListener("click", close);
    q('[data-action="new"]').addEventListener("click", newChat);
    q('[data-action="settings"]').addEventListener("click", () => q('[data-part="settings"]').classList.toggle("hidden"));
    q('[data-action="send"]').addEventListener("click", send);
    q('[data-action="stop"]').addEventListener("click", stop);
    q('[data-action="sync"]').addEventListener("click", () => indexAction("sync"));
    q('[data-action="rebuild"]').addEventListener("click", () => indexAction("rebuild"));
    q('[data-action="pause"]').addEventListener("click", () => indexAction("pause"));
    fields.question.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        send();
      }
    });
    for (const field of [fields.scope, fields.model, fields.think, fields.num_ctx, fields.top_k, fields.temperature, fields.num_predict]) {
      field.addEventListener("change", () => {
        state.scope = fields.scope.value;
        state.settings = normalizeSettings();
        saveStored(state);
      });
    }

    fillSettings();
    renderMessages();
    renderIndex({ state: state.indexState });
    return { open, syncNav: () => addSettingsShortcut(state.controlCenterUrl), state };
  }

  async function start() {
    let boot;
    try {
      boot = await bootstrap();
    } catch (_error) {
      // Fail open: if PLAI is unavailable, do not hide or replace Paperless chat.
      return;
    }
    if (!boot?.ok) return;
    const panel = makePanel(boot);
    const sync = () => {
      ensureButton(panel.open);
      panel.syncNav();
    };
    new MutationObserver(sync).observe(document.documentElement, { childList: true, subtree: true });
    window.addEventListener("popstate", sync);
    window.addEventListener("hashchange", sync);
    window.addEventListener("pagehide", () => {
      const jobId = panel.state.jobId;
      if (!jobId) return;
      const token = csrfToken();
      fetch(apiUrl("chat/stop"), {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
          ...(token ? { "X-CSRFToken": token } : {}),
        },
        body: JSON.stringify({ job_id: jobId }),
      }).catch(() => {});
    });
    sync();
  }

  start();
})();
