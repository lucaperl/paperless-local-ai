(() => {
  "use strict";

  const APP_ID = "paperless-local-ai-chat-host";
  const BUTTON_ID = "paperless-local-ai-chat-button";
  const BUTTON_STYLE_ID = "paperless-local-ai-chat-button-style";
  const SETTINGS_LINK_ID = "paperless-local-ai-settings-link";
  const ACTIVE_CHAT_KEY = "paperless-local-ai-active-chat-v2";

  const baseHref = document.querySelector("base")?.getAttribute("href") || "/";
  const appBase = new URL(baseHref, window.location.origin);
  const appBasePath = appBase.pathname.endsWith("/") ? appBase.pathname : `${appBase.pathname}/`;
  const apiUrl = (path) => `${appBasePath}_plai/${path.replace(/^\/+/, "")}`;
  const paperlessApiUrl = (path) => `${appBasePath}api/${path.replace(/^\/+/, "")}`;
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
    const response = await fetch(apiUrl(path), { ...options, method, headers, credentials: "same-origin", redirect: "error" });
    const text = await response.text();
    let payload = {};
    try { payload = text ? JSON.parse(text) : {}; } catch (_error) { payload = { error: text || `HTTP ${response.status}` }; }
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  }

  async function paperlessApi(path) {
    const response = await fetch(paperlessApiUrl(path), { credentials: "same-origin", headers: { Accept: "application/json; version=10" } });
    if (!response.ok) throw new Error(`Paperless API ${response.status}`);
    return response.json();
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

  function formatSeconds(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return "";
    return number < 10 ? `${number.toFixed(2)} s` : `${number.toFixed(1)} s`;
  }

  function formatDurationSeconds(seconds) {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const rest = seconds % 60;
    if (hours) return `${hours}h ${minutes}m`;
    if (minutes) return `${minutes}m ${rest}s`;
    return `${rest}s`;
  }

  function ensureNavbarButtonStyle() {
    if (document.getElementById(BUTTON_STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = BUTTON_STYLE_ID;
    style.textContent = `
      #${BUTTON_ID} { border:0!important; background:transparent!important; box-shadow:none!important; }
      #${BUTTON_ID}:hover, #${BUTTON_ID}:active, #${BUTTON_ID}:focus { background:transparent!important; box-shadow:none!important; outline:none!important; }
      #${BUTTON_ID}:focus-visible { outline:2px solid currentColor!important; outline-offset:2px!important; border-radius:.375rem!important; }
    `;
    document.head.appendChild(style);
  }

  function addSettingsShortcut(controlCenterUrl) {
    const existing = document.getElementById(SETTINGS_LINK_ID);
    const path = relativePath();
    if (!(path === "settings" || path.startsWith("settings/"))) { existing?.remove(); return; }
    const admin = [...document.querySelectorAll("a[href]")].find((link) => {
      const href = link.getAttribute("href") || "";
      return href === "admin/" || href.endsWith("/admin/");
    });
    if (!admin || existing?.isConnected) return;
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

  function ensureButton(togglePanel, isOpen) {
    ensureNavbarButtonStyle();
    let button = document.getElementById(BUTTON_ID);
    if (!button) {
      button = document.createElement("button");
      button.id = BUTTON_ID;
      button.type = "button";
      button.title = "paperless-local-ai chat";
      button.setAttribute("aria-label", "Toggle paperless-local-ai chat");
      button.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M4 4h16v12H7.5L4 19.5V4Zm2 2v9.3l.7-.7.6-.6H18V6H6Z"/></svg>';
      Object.assign(button.style, { color: "inherit", cursor: "pointer", fontSize: "1.15rem", lineHeight: "1", padding: ".45rem .55rem", borderRadius: ".375rem" });
      button.addEventListener("click", togglePanel);
    }
    button.setAttribute("aria-expanded", isOpen() ? "true" : "false");

    const nativeRoot = hideNativeChat();
    const toastRoot = document.querySelector("pngx-toasts-dropdown");
    const anchor = nativeRoot || toastRoot;
    if (anchor?.parentNode && button.parentNode !== anchor.parentNode) {
      anchor.parentNode.insertBefore(button, anchor);
      button.style.position = ""; button.style.right = ""; button.style.bottom = ""; button.style.zIndex = "";
    } else if (!button.isConnected) {
      document.body.appendChild(button);
      Object.assign(button.style, { position: "fixed", right: "1rem", bottom: "1rem", zIndex: "2147483000", background: "var(--bs-body-bg, white)", boxShadow: "0 2px 12px rgba(0,0,0,.22)" });
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
        <div><strong>paperless-local-ai</strong><span class="sub">RAG chat</span></div>
        <div class="header-actions">
          <button type="button" data-action="history" title="Chat history">☰</button>
          <button type="button" data-action="new" title="New chat">＋</button>
          <button type="button" data-action="settings" title="Chat settings">⚙</button>
          <button type="button" data-action="close" title="Close">×</button>
        </div>
      </header>
      <div class="body-row">
        <aside class="history hidden" data-part="history">
          <div class="history-head"><strong>Chats</strong><button type="button" data-action="new-side">＋</button></div>
          <div class="history-list" data-part="history-list"></div>
        </aside>
        <section class="chat-area">
          <div class="toolbar">
            <label>Search in
              <select data-field="scope">
                <option value="all">All documents</option>
                <option value="document">Current document</option>
                <option value="tag">Tag…</option>
                <option value="correspondent">Correspondent…</option>
                <option value="document_type">Document type…</option>
              </select>
            </label>
            <div class="scope-value hidden" data-part="scope-value">
              <div class="field-label" data-part="scope-label">Choose</div>
              <div class="scope-combobox" data-part="scope-combobox">
                <input data-field="scope_query" type="text" autocomplete="off" role="combobox"
                  aria-autocomplete="list" aria-expanded="false" aria-controls="plai-scope-options">
                <div class="scope-options hidden" data-part="scope-options" id="plai-scope-options" role="listbox"></div>
              </div>
            </div>
            <label>Model
              <input data-field="model" list="plai-models" autocomplete="off">
              <datalist id="plai-models"></datalist>
            </label>
          </div>
          <div class="settings hidden" data-part="settings">
            <div class="settings-grid">
              <label>Thinking<select data-field="think"><option value="auto">Auto</option><option value="off">Off</option><option value="on">On</option></select></label>
              <label>Context<input data-field="num_ctx" type="number" min="2048" max="131072" step="1024"></label>
              <label>Retrieval Top-K<input data-field="top_k" type="number" min="1" max="12" step="1"></label>
              <label>Temperature<input data-field="temperature" type="number" min="0" max="2" step="0.1"></label>
              <label>Max output tokens<input data-field="num_predict" type="number" min="64" max="4096" step="64"></label>
            </div>
            <div class="index-box">
              <div class="index-head"><strong>Index</strong><span data-part="index-state">Loading…</span></div>
              <div class="progress"><span data-part="index-progress"></span></div>
              <small data-part="index-detail"></small>
              <div class="index-config">
                <label>Embedding model
                  <input data-field="embedding_model" list="plai-models" autocomplete="off">
                </label>
                <div class="index-config-grid">
                  <label>Chunk target
                    <input data-field="chunk_target_chars" type="number" min="1000" max="20000" step="100">
                  </label>
                  <label>Chunk overlap
                    <input data-field="chunk_overlap_chars" type="number" min="0" max="19999" step="100">
                  </label>
                  <label>Embedding batch size
                    <input data-field="embedding_batch_size" type="number" min="1" max="64" step="1">
                  </label>
                  <label>Embedding slice size
                    <input data-field="embedding_slice_chunks" type="number" min="1" max="256" step="1">
                  </label>
                  <label>Sync interval (seconds)
                    <input data-field="sync_interval_seconds" type="number" min="60" max="86400" step="60">
                  </label>
                </div>
                <small data-part="index-config-detail"></small>
                <button type="button" data-action="save-index-config">Save index settings</button>
              </div>
              <p class="index-help">Rebuild recreates the PLAI search index for all Paperless documents. It never modifies the documents themselves. An existing active index remains usable until the rebuilt index is activated.</p>
              <div class="index-actions">
                <button type="button" data-action="sync">Sync</button>
                <button type="button" data-action="rebuild">Rebuild</button>
                <button type="button" data-action="pause">Pause</button>
              </div>
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
        </section>
      </div>
    `;
    root.appendChild(shell);

    const stopKeyboardPropagation = (event) => event.stopPropagation();
    root.addEventListener("keydown", stopKeyboardPropagation);
    root.addEventListener("keypress", stopKeyboardPropagation);
    root.addEventListener("keyup", stopKeyboardPropagation);

    const defaults = boot.config?.chat_defaults || {};
    const state = {
      shell, root, open: false, historyOpen: false,
      messages: [], settings: { ...defaults },
      scope: currentDocumentId() ? "document" : "all", scopeId: null, scopeLabel: null,
      conversationId: localStorage.getItem(ACTIVE_CHAT_KEY) || null,
      jobId: null, pollTimer: null, indexTimer: null,
      indexState: boot.state || {}, indexConfig: boot.config || {},
      conversations: [], controlCenterUrl: boot.control_center_url,
      scopeOptionsByType: {}, scopeOptions: [], scopeOptionType: null,
      scopeActiveIndex: -1, scopeLoadToken: 0, observedDocumentId: currentDocumentId(),
    };

    const q = (selector) => root.querySelector(selector);
    const fields = {
      scope: q('[data-field="scope"]'), scope_query: q('[data-field="scope_query"]'), model: q('[data-field="model"]'),
      think: q('[data-field="think"]'), num_ctx: q('[data-field="num_ctx"]'), top_k: q('[data-field="top_k"]'),
      temperature: q('[data-field="temperature"]'), num_predict: q('[data-field="num_predict"]'),
      embedding_model: q('[data-field="embedding_model"]'),
      chunk_target_chars: q('[data-field="chunk_target_chars"]'), chunk_overlap_chars: q('[data-field="chunk_overlap_chars"]'),
      embedding_batch_size: q('[data-field="embedding_batch_size"]'), embedding_slice_chunks: q('[data-field="embedding_slice_chunks"]'),
      sync_interval_seconds: q('[data-field="sync_interval_seconds"]'), question: q('[data-field="question"]'),
    };

    function normalizeSettings() {
      return {
        model: String(fields.model.value || defaults.model || "").trim(), think: String(fields.think.value || "off"),
        num_ctx: Number(fields.num_ctx.value || 8192), top_k: Number(fields.top_k.value || 5),
        temperature: Number(fields.temperature.value || 0.1), num_predict: Number(fields.num_predict.value || 512),
      };
    }

    function fillSettings() {
      fields.model.value = state.settings.model || defaults.model || "";
      fields.think.value = state.settings.think || defaults.think || "off";
      fields.num_ctx.value = state.settings.num_ctx || defaults.num_ctx || 8192;
      fields.top_k.value = state.settings.top_k || defaults.top_k || 5;
      fields.temperature.value = state.settings.temperature ?? defaults.temperature ?? 0.1;
      fields.num_predict.value = state.settings.num_predict || defaults.num_predict || 512;
      fillIndexConfigFields();
      fields.scope.value = state.scope;
      updateScopeUi(false);
    }

    function fillIndexConfigFields() {
      fields.embedding_model.value = state.indexConfig.embedding_model || "";
      fields.chunk_target_chars.value = state.indexConfig.chunk_target_chars ?? 4000;
      fields.chunk_overlap_chars.value = state.indexConfig.chunk_overlap_chars ?? 800;
      fields.embedding_batch_size.value = state.indexConfig.embedding_batch_size ?? 16;
      fields.embedding_slice_chunks.value = state.indexConfig.embedding_slice_chunks ?? 64;
      fields.sync_interval_seconds.value = state.indexConfig.sync_interval_seconds ?? 900;
    }

    function sourceNode(source) {
      const link = document.createElement("a");
      link.className = "source"; link.href = documentUrl(source.document_id); link.target = "_self";
      const refs = Array.isArray(source.source_numbers) && source.source_numbers.length ? `[${source.source_numbers.join(", ")}] ` : "";
      link.textContent = `${refs}📄 ${source.title || `Document ${source.document_id}`}`;
      return link;
    }

    function renderMessages() {
      const container = q('[data-part="messages"]'); container.replaceChildren();
      if (!state.messages.length) {
        const empty = document.createElement("div"); empty.className = "empty";
        empty.innerHTML = "<strong>Ask your archive.</strong><span>Choose all documents, the current document, a tag, correspondent or document type.</span>";
        container.appendChild(empty); return;
      }
      for (const message of state.messages) {
        const wrapper = document.createElement("article"); wrapper.className = `message ${message.role}`;
        const label = document.createElement("div"); label.className = "message-label"; label.textContent = message.role === "user" ? "You" : "PLAI";
        const body = document.createElement("div"); body.className = "message-body"; body.textContent = message.content || (message.pending ? "…" : "");
        wrapper.append(label, body);
        if (Array.isArray(message.sources) && message.sources.length) {
          const sources = document.createElement("div"); sources.className = "sources";
          for (const source of message.sources) sources.appendChild(sourceNode(source)); wrapper.appendChild(sources);
        }
        if (message.metrics?.total_seconds) {
          const metrics = document.createElement("small"); metrics.className = "metrics";
          metrics.textContent = `Total ${formatSeconds(message.metrics.total_seconds)} · embed ${formatSeconds(message.metrics.embedding_seconds)} · retrieval ${formatSeconds(message.metrics.retrieval_seconds)} · LLM ${formatSeconds(message.metrics.generation_seconds)}`;
          wrapper.appendChild(metrics);
        }
        container.appendChild(wrapper);
      }
      container.scrollTop = container.scrollHeight;
    }

    function setPhase(text = "") { q('[data-part="phase"]').textContent = text; }
    function setRunning(running) {
      q('[data-action="send"]').disabled = running || !state.indexState?.index_exists;
      q('[data-action="stop"]').classList.toggle("hidden", !running);
      fields.question.disabled = running;
    }

    function waitingLabel(job) {
      const activity = job.waiting_for || {};
      const label = activity.label || "another AI task";
      const started = Number(activity.started_at_ms || 0);
      const elapsed = started ? ` · ${formatDurationSeconds((Date.now() - started) / 1000)}` : "";
      if (activity.operation === "rag_chat") return `Waiting for AI… Another chat is currently generating${elapsed}`;
      return `Waiting for AI… ${label} is currently using the AI slot${elapsed}`;
    }

    function phaseLabel(job) {
      if (job.phase === "waiting") return waitingLabel(job);
      const labels = { embedding: "Embedding question…", retrieval: "Retrieving relevant chunks…", generation: "Generating answer…", stopped: "Stopped", error: "Error" };
      return labels[job.phase] || "";
    }

    async function refreshConversations() {
      const payload = await api("conversations", { method: "POST", body: "{}" });
      state.conversations = payload.conversations || [];
      renderHistory();
    }

    function renderHistory() {
      const list = q('[data-part="history-list"]'); list.replaceChildren();
      for (const item of state.conversations) {
        const row = document.createElement("div"); row.className = `history-item${item.id === state.conversationId ? " active" : ""}`;
        const open = document.createElement("button"); open.type = "button"; open.className = "history-open";
        open.textContent = `${item.active_job_id ? "● " : ""}${item.title || "New chat"}`; open.title = item.title || "New chat";
        open.addEventListener("click", () => loadConversation(item.id));
        const menu = document.createElement("button"); menu.type = "button"; menu.className = "history-menu"; menu.textContent = "⋯";
        menu.addEventListener("click", async () => {
          const action = window.prompt("Type rename or delete", "rename");
          if (action === "rename") {
            const title = window.prompt("Chat title", item.title || ""); if (!title) return;
            await api("conversations/rename", { method: "POST", body: JSON.stringify({ conversation_id: item.id, title }) });
            await refreshConversations();
          } else if (action === "delete") {
            if (!window.confirm(`Delete “${item.title || "this chat"}”?`)) return;
            try { await api("conversations/delete", { method: "POST", body: JSON.stringify({ conversation_id: item.id }) }); }
            catch (error) { setPhase(error.message); return; }
            if (state.conversationId === item.id) newChat();
            await refreshConversations();
          }
        });
        row.append(open, menu); list.appendChild(row);
      }
    }

    async function loadConversation(id) {
      if (!id) return;
      if (state.pollTimer) clearTimeout(state.pollTimer);
      state.pollTimer = null;
      const conversation = await api("conversations/get", { method: "POST", body: JSON.stringify({ conversation_id: id }) });
      state.conversationId = conversation.id; localStorage.setItem(ACTIVE_CHAT_KEY, conversation.id);
      state.messages = Array.isArray(conversation.messages) ? conversation.messages : [];
      state.settings = { ...defaults, ...(conversation.settings || {}) };
      const scope = conversation.scope || {};
      state.scope = scope.type || "all"; state.scopeId = scope.id ?? null; state.scopeLabel = scope.label ?? null;
      state.jobId = conversation.active_job_id || null;
      fillSettings(); renderMessages(); renderHistory();
      if (state.jobId) { setRunning(true); pollJob(); } else { setRunning(false); setPhase(""); }
    }

    async function ensureConversation() {
      if (state.conversationId) return state.conversationId;
      const scope = currentScopePayload();
      const conversation = await api("conversations/create", { method: "POST", body: JSON.stringify({ scope, settings: normalizeSettings() }) });
      state.conversationId = conversation.id; localStorage.setItem(ACTIVE_CHAT_KEY, conversation.id);
      await refreshConversations();
      return conversation.id;
    }

    async function pollJob() {
      if (!state.jobId) return;
      try {
        const job = await api("chat/status", { method: "POST", body: JSON.stringify({ job_id: state.jobId }) });
        const assistant = [...state.messages].reverse().find((item) => item.role === "assistant" && item.pending);
        if (assistant) { assistant.content = job.answer || ""; assistant.sources = job.sources || []; renderMessages(); }
        setPhase(phaseLabel(job));
        if (["done", "error", "stopped"].includes(job.status)) {
          state.jobId = null; setRunning(false); await loadConversation(state.conversationId); await refreshConversations(); return;
        }
      } catch (error) { setPhase(error.message); }
      state.pollTimer = setTimeout(pollJob, 500);
    }

    function currentScopePayload() {
      const type = fields.scope.value;
      const docId = currentDocumentId();
      return {
        type,
        id: ["tag", "correspondent", "document_type"].includes(type) ? state.scopeId : null,
        label: ["tag", "correspondent", "document_type"].includes(type) ? state.scopeLabel : null,
        document_id: type === "document" ? docId : null,
      };
    }

    async function send() {
      const question = fields.question.value.trim(); if (!question || state.jobId) return;
      if (!state.indexState?.index_exists) { setPhase("Build the RAG index first."); return; }
      const scope = currentScopePayload();
      if (scope.type === "document" && !scope.document_id) { setPhase("Open a document first, or choose another search scope."); return; }
      if (["tag", "correspondent", "document_type"].includes(scope.type) && !scope.id) { setPhase("Choose a value for the selected search scope."); return; }
      const conversationId = await ensureConversation();
      state.settings = normalizeSettings(); state.scope = scope.type; state.scopeId = scope.id; state.scopeLabel = scope.label;
      state.messages.push({ role: "user", content: question });
      state.messages.push({ role: "assistant", content: "", pending: true, sources: [] });
      fields.question.value = ""; renderMessages(); setRunning(true); setPhase("Submitting…");
      try {
        const started = await api("chat/start", { method: "POST", body: JSON.stringify({
          conversation_id: conversationId, question, scope: scope.type, scope_id: scope.id,
          scope_label: scope.label, document_id: scope.document_id, settings: state.settings,
        }) });
        state.jobId = started.job_id; await refreshConversations(); pollJob();
      } catch (error) {
        state.messages = state.messages.slice(0, -2); renderMessages(); setRunning(false); setPhase(error.message);
        await loadConversation(conversationId).catch(() => {});
      }
    }

    async function stop() {
      if (!state.jobId) return;
      try { await api("chat/stop", { method: "POST", body: JSON.stringify({ job_id: state.jobId }) }); setPhase("Stopping…"); }
      catch (error) { setPhase(error.message); }
    }

    async function refreshModels() {
      try {
        const payload = await api("models"); const list = q("#plai-models"); list.replaceChildren();
        for (const model of payload.models || []) { const option = document.createElement("option"); option.value = model; list.appendChild(option); }
      } catch (_error) {}
    }

    const scopedTypes = new Set(["tag", "correspondent", "document_type"]);
    const scopeLabels = { tag: "Tag", correspondent: "Correspondent", document_type: "Document type" };

    function closeScopeOptions() {
      q('[data-part="scope-options"]').classList.add("hidden");
      fields.scope_query.setAttribute("aria-expanded", "false");
      fields.scope_query.removeAttribute("aria-activedescendant");
      state.scopeActiveIndex = -1;
    }

    function scopeSearchValue(item) {
      return `${item.name || ""} ${item.id}`.toLocaleLowerCase();
    }

    function visibleScopeOptions(showAll = false) {
      const query = fields.scope_query.value.trim().toLocaleLowerCase();
      const source = state.scopeOptions || [];
      if (showAll || !query || (state.scopeLabel && fields.scope_query.value === state.scopeLabel)) {
        return source.slice(0, 60);
      }
      return source.filter((item) => scopeSearchValue(item).includes(query)).slice(0, 60);
    }

    function selectScopeOption(item) {
      state.scopeId = Number(item.id) || null;
      state.scopeLabel = item.name || `ID ${item.id}`;
      fields.scope_query.value = state.scopeLabel;
      closeScopeOptions();
    }

    function renderScopeOptions(showAll = false) {
      const list = q('[data-part="scope-options"]');
      if (!scopedTypes.has(fields.scope.value) || fields.scope_query.disabled) {
        closeScopeOptions();
        return;
      }
      const items = visibleScopeOptions(showAll);
      if (state.scopeActiveIndex >= items.length) state.scopeActiveIndex = items.length ? items.length - 1 : -1;
      list.replaceChildren();

      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "scope-option empty-option";
        empty.textContent = "No matches";
        list.appendChild(empty);
      } else {
        items.forEach((item, index) => {
          const option = document.createElement("button");
          option.type = "button";
          option.className = `scope-option${index === state.scopeActiveIndex ? " active" : ""}`;
          option.id = `plai-scope-option-${index}`;
          option.setAttribute("role", "option");
          option.setAttribute("aria-selected", item.id === state.scopeId ? "true" : "false");
          option.textContent = item.name || `ID ${item.id}`;
          option.addEventListener("mousedown", (event) => {
            event.preventDefault();
            selectScopeOption(item);
          });
          list.appendChild(option);
        });
      }

      list.classList.remove("hidden");
      fields.scope_query.setAttribute("aria-expanded", "true");
      if (state.scopeActiveIndex >= 0) {
        fields.scope_query.setAttribute("aria-activedescendant", `plai-scope-option-${state.scopeActiveIndex}`);
      } else {
        fields.scope_query.removeAttribute("aria-activedescendant");
      }
    }

    async function fetchAllScopeOptions(type) {
      if (state.scopeOptionsByType[type]) return state.scopeOptionsByType[type];
      const endpoint = { tag: "tags/", correspondent: "correspondents/", document_type: "document_types/" }[type];
      const items = [];
      for (let page = 1; page <= 100; page += 1) {
        const payload = await paperlessApi(`${endpoint}?page_size=250&ordering=name&page=${page}`);
        const batch = Array.isArray(payload) ? payload : (payload.results || []);
        for (const item of batch) {
          if (item && item.id != null) items.push({ id: Number(item.id), name: String(item.name || `ID ${item.id}`) });
        }
        if (Array.isArray(payload) || !payload.next) break;
        if (page === 100) throw new Error("Paperless scope list exceeded 100 pages");
      }
      state.scopeOptionsByType[type] = items;
      return items;
    }

    async function loadScopeOptions(type) {
      const wrap = q('[data-part="scope-value"]');
      if (!scopedTypes.has(type)) {
        wrap.classList.add("hidden");
        state.scopeOptions = [];
        state.scopeOptionType = null;
        closeScopeOptions();
        return;
      }

      wrap.classList.remove("hidden");
      q('[data-part="scope-label"]').textContent = scopeLabels[type];
      fields.scope_query.value = state.scope === type && state.scopeLabel ? state.scopeLabel : "";
      fields.scope_query.disabled = true;
      fields.scope_query.placeholder = `Loading ${scopeLabels[type].toLocaleLowerCase()}s…`;
      closeScopeOptions();

      const token = ++state.scopeLoadToken;
      try {
        const items = await fetchAllScopeOptions(type);
        if (token !== state.scopeLoadToken || fields.scope.value !== type) return;
        state.scopeOptions = items;
        state.scopeOptionType = type;
        fields.scope_query.disabled = false;
        fields.scope_query.placeholder = `Search ${scopeLabels[type].toLocaleLowerCase()}…`;
        fields.scope_query.value = state.scope === type && state.scopeLabel ? state.scopeLabel : "";
      } catch (error) {
        if (token !== state.scopeLoadToken) return;
        fields.scope_query.disabled = false;
        fields.scope_query.placeholder = `Search ${scopeLabels[type].toLocaleLowerCase()}…`;
        setPhase(`Could not load Paperless filters: ${error.message}`);
      }
    }

    async function updateScopeUi(load = true) {
      const docId = currentDocumentId();
      const docOption = [...fields.scope.options].find((option) => option.value === "document");
      if (docOption) docOption.disabled = !docId;
      if (fields.scope.value === "document" && !docId) {
        fields.scope.value = "all";
        state.scope = "all";
        state.scopeId = null;
        state.scopeLabel = null;
      }
      if (load) await loadScopeOptions(fields.scope.value); else loadScopeOptions(fields.scope.value);
    }

    function syncDocumentContext() {
      const docId = currentDocumentId();
      if (docId === state.observedDocumentId) return;
      state.observedDocumentId = docId;
      updateScopeUi(false);
    }

    function renderIndex(payload) {
      const idx = payload.state || {}; state.indexState = idx; state.indexConfig = payload.config || state.indexConfig;
      const stateNode = q('[data-part="index-state"]'); const detail = q('[data-part="index-detail"]'); const bar = q('[data-part="index-progress"]'); const pauseButton = q('[data-action="pause"]');
      let label = idx.index_exists ? `${idx.indexed_documents || 0} docs · ${idx.indexed_chunks || 0} chunks` : "Not built";
      if (idx.running) label = `${idx.operation || "index"}: ${idx.phase || "running"}`;
      if (idx.paused) label = "Paused";
      if (idx.rebuild_required && idx.index_exists) label += " · rebuild required";
      if (idx.last_error) label = `Error: ${idx.last_error}`;
      stateNode.textContent = label;
      const total = Number(idx.total || 0); const current = Number(idx.current || 0); const percent = total > 0 ? Math.max(0, Math.min(100, (current / total) * 100)) : 0; bar.style.width = `${percent}%`;
      let extra = "";
      if (idx.running && idx.started_at && total > 0 && current > 0) {
        const elapsed = Math.max(1, (Date.now() - Date.parse(idx.started_at)) / 1000); const eta = elapsed * Math.max(0, total - current) / current;
        extra = ` · elapsed ${formatDurationSeconds(elapsed)} · ETA ~${formatDurationSeconds(eta)}`;
      }
      detail.textContent = total > 0 ? `${current} / ${total} documents · ${idx.indexed_chunks || 0} chunks${extra}` : (idx.last_sync ? `Last sync ${idx.last_sync}` : "Initial rebuild is explicit.");
      const active = idx.active_signature || null;
      q('[data-part="index-config-detail"]').textContent = active
        ? `Active: ${active.embedding_model} · chunk ${active.chunk_target_chars}/${active.chunk_overlap_chars}. Configured: ${state.indexConfig.embedding_model} · chunk ${state.indexConfig.chunk_target_chars}/${state.indexConfig.chunk_overlap_chars}, batch ${state.indexConfig.embedding_batch_size}, slice ${state.indexConfig.embedding_slice_chunks}, sync ${state.indexConfig.sync_interval_seconds}s.`
        : `Next rebuild: ${state.indexConfig.embedding_model} · chunk ${state.indexConfig.chunk_target_chars}/${state.indexConfig.chunk_overlap_chars}, batch ${state.indexConfig.embedding_batch_size}, slice ${state.indexConfig.embedding_slice_chunks}, sync ${state.indexConfig.sync_interval_seconds}s.`;
      pauseButton.textContent = idx.paused ? "Resume" : "Pause"; setRunning(!!state.jobId);
    }

    async function refreshIndex() {
      if (state.indexTimer) clearTimeout(state.indexTimer); state.indexTimer = null;
      try { renderIndex(await api("status")); } catch (error) { q('[data-part="index-state"]').textContent = error.message; }
      if (state.open) state.indexTimer = setTimeout(refreshIndex, 3000);
    }

    async function saveIndexConfig() {
      const config = {
        embedding_model: fields.embedding_model.value.trim(),
        chunk_target_chars: Number(fields.chunk_target_chars.value),
        chunk_overlap_chars: Number(fields.chunk_overlap_chars.value),
        embedding_batch_size: Number(fields.embedding_batch_size.value),
        embedding_slice_chunks: Number(fields.embedding_slice_chunks.value),
        sync_interval_seconds: Number(fields.sync_interval_seconds.value),
      };
      if (!config.embedding_model) { setPhase("Embedding model is required."); return; }
      const integerFields = [
        "chunk_target_chars", "chunk_overlap_chars", "embedding_batch_size",
        "embedding_slice_chunks", "sync_interval_seconds",
      ];
      if (integerFields.some((key) => !Number.isInteger(config[key]))) {
        setPhase("Index numeric settings must be whole numbers.");
        return;
      }
      try {
        const payload = await api("config", { method: "POST", body: JSON.stringify(config) });
        renderIndex(payload);
        fillIndexConfigFields();
        if (!state.indexState.index_exists) {
          setPhase("Index settings saved.");
        } else if (state.indexState.rebuild_required) {
          setPhase("Index settings saved. The active index remains usable; model/chunk changes require Rebuild.");
        } else {
          setPhase("Index settings saved. Batch, slice and sync changes apply without rebuilding.");
        }
      } catch (error) { setPhase(error.message); }
    }

    async function indexAction(action) {
      try {
        if (action === "rebuild" && !window.confirm("Rebuild the complete PLAI RAG index? Paperless documents are not modified, and an existing active index stays usable until activation.")) return;
        if (action === "pause") {
          const resume = !!state.indexState.paused; const operation = state.indexState.operation;
          await api("index/pause", { method: "POST", body: JSON.stringify({ paused: !resume }) });
          if (resume && operation === "rebuild") await api("index/rebuild", { method: "POST", body: "{}" });
          if (resume && operation === "sync") await api("index/sync", { method: "POST", body: "{}" });
        } else { await api(`index/${action}`, { method: "POST", body: "{}" }); }
        await refreshIndex();
      } catch (error) { setPhase(error.message); }
    }

    function newChat() {
      state.conversationId = null; state.messages = []; state.jobId = null; localStorage.removeItem(ACTIVE_CHAT_KEY);
      state.settings = { ...defaults }; state.scope = currentDocumentId() ? "document" : "all"; state.scopeId = null; state.scopeLabel = null;
      fillSettings(); renderMessages(); renderHistory(); setRunning(false); setPhase(""); fields.question.focus();
    }

    function toggleHistory() {
      state.historyOpen = !state.historyOpen; q('[data-part="history"]').classList.toggle("hidden", !state.historyOpen); shell.classList.toggle("with-history", state.historyOpen); if (state.historyOpen) refreshConversations().catch((error) => setPhase(error.message));
    }

    async function open() {
      state.open = true; shell.classList.remove("hidden");
      document.getElementById(BUTTON_ID)?.setAttribute("aria-expanded", "true");
      fillSettings(); renderMessages(); refreshModels();
      syncDocumentContext();
      await refreshConversations().catch((error) => setPhase(error.message));
      if (state.conversationId && state.conversations.some((item) => item.id === state.conversationId)) await loadConversation(state.conversationId).catch(() => newChat());
      if (state.indexTimer) clearTimeout(state.indexTimer); refreshIndex();
      if (!state.indexState?.index_exists) setPhase("RAG index not built yet. Open settings and run Rebuild.");
      setTimeout(() => fields.question.focus(), 0);
    }

    function close() {
      state.open = false; shell.classList.add("hidden"); document.getElementById(BUTTON_ID)?.setAttribute("aria-expanded", "false");
      if (state.indexTimer) clearTimeout(state.indexTimer); state.indexTimer = null;
    }

    function toggle() { if (state.open) close(); else open(); }

    q('[data-action="close"]').addEventListener("click", close);
    q('[data-action="history"]').addEventListener("click", toggleHistory);
    q('[data-action="new"]').addEventListener("click", newChat);
    q('[data-action="new-side"]').addEventListener("click", newChat);
    q('[data-action="settings"]').addEventListener("click", () => q('[data-part="settings"]').classList.toggle("hidden"));
    q('[data-action="send"]').addEventListener("click", send);
    q('[data-action="stop"]').addEventListener("click", stop);
    q('[data-action="sync"]').addEventListener("click", () => indexAction("sync"));
    q('[data-action="rebuild"]').addEventListener("click", () => indexAction("rebuild"));
    q('[data-action="pause"]').addEventListener("click", () => indexAction("pause"));
    q('[data-action="save-index-config"]').addEventListener("click", saveIndexConfig);
    fields.scope.addEventListener("change", () => {
      state.scope = fields.scope.value;
      state.scopeId = null;
      state.scopeLabel = null;
      updateScopeUi();
    });
    fields.scope_query.addEventListener("focus", () => renderScopeOptions(true));
    fields.scope_query.addEventListener("input", () => {
      if (fields.scope_query.value !== state.scopeLabel) {
        state.scopeId = null;
        state.scopeLabel = null;
      }
      state.scopeActiveIndex = -1;
      renderScopeOptions(false);
    });
    fields.scope_query.addEventListener("keydown", (event) => {
      if (!["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(event.key)) return;
      if (event.key === "Escape") {
        event.preventDefault();
        closeScopeOptions();
        return;
      }
      const items = visibleScopeOptions(false);
      if (!items.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        state.scopeActiveIndex = Math.min(items.length - 1, state.scopeActiveIndex + 1);
        renderScopeOptions(false);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        state.scopeActiveIndex = Math.max(0, state.scopeActiveIndex <= 0 ? 0 : state.scopeActiveIndex - 1);
        renderScopeOptions(false);
      } else if (event.key === "Enter" && state.scopeActiveIndex >= 0) {
        event.preventDefault();
        selectScopeOption(items[state.scopeActiveIndex]);
      }
    });
    fields.scope_query.addEventListener("blur", () => setTimeout(closeScopeOptions, 100));
    fields.question.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } });

    fillSettings(); renderMessages(); renderIndex({ state: state.indexState, config: state.indexConfig });
    return {
      open, close, toggle, isOpen: () => state.open,
      syncNav: () => addSettingsShortcut(state.controlCenterUrl),
      syncContext: syncDocumentContext,
      state,
    };
  }

  async function start() {
    let boot; try { boot = await api("bootstrap"); } catch (_error) { return; }
    if (!boot?.ok) return;
    const panel = makePanel(boot);
    const sync = () => {
      ensureButton(panel.toggle, panel.isOpen);
      panel.syncNav();
      panel.syncContext();
    };
    new MutationObserver(sync).observe(document.documentElement, { childList: true, subtree: true });
    window.addEventListener("popstate", sync); window.addEventListener("hashchange", sync);
    sync();
  }

  start();
})();
