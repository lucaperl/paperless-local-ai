# Paperless RAG chat

`paperless-local-ai` can provide an optional lightweight RAG chat directly inside the Paperless-ngx web interface. Paperless remains unmodified and remains the document system of record.

## UI integration

When the optional Paperless UI integration is enabled, the integration injects a same-origin JavaScript asset into Paperless. After a successful authenticated PLAI bootstrap, it hides Paperless' native AI chat control and inserts the PLAI chat control in the same navbar area. The native component is hidden rather than removed. If PLAI cannot initialize after a future Paperless frontend change, the integration fails open and leaves Paperless' own UI available.

The chat panel is isolated in Shadow DOM. The same integration keeps the existing Settings shortcut to the Control Center; there is no second chat UI in the Control Center and index controls are kept in the chat panel instead of linking to a duplicate Control Center index page.

Browser requests stay on the Paperless origin below `/_plai/`. The browser does not connect directly to the Control Center port or Ollama. Paperless authenticates the browser session, requires a superuser for the initial implementation, applies CSRF protection to writes and relays only a fixed allow-list of RAG requests to `core-service`. The relay authenticates to the core with an internal random secret stored in the shared integration directory and never exposed to browser JavaScript.

## Chat behavior

The panel supports:

- persistent server-side conversations that can be resumed from another browser/device;
- new/open/rename/delete chat history without an extra LLM title-generation call;
- scope `Current document`, `All documents`, `Tag`, `Correspondent` or `Document type`; tag/correspondent/document-type values use a type-ahead combobox backed by Paperless IDs, and Current document follows Paperless SPA navigation while the panel stays open;
- clickable Paperless source documents;
- installed Ollama model discovery plus free model entry;
- Thinking `Auto`, `Off` or `On`;
- context size;
- retrieval Top-K;
- temperature;
- maximum output tokens;
- incremental answer/status updates and a Stop action;
- explicit index Sync, Rebuild and Pause/Resume controls.

Conversation history is stored persistently below `/data/chat` and is keyed by the authenticated Paperless user ID supplied by the trusted same-origin relay. Conversation files are protected by a server-side file lock; no chat content is stored in browser session storage. The browser remembers only the currently selected server-side conversation ID. The backend still sends only a bounded recent history to the model and never adds an LLM summarization/title call.

## RAG pipeline

A normal chat turn has a deliberately fixed heavy-work shape:

```text
question
  ↓
1 × Ollama /api/embed (Qwen query-side retrieval instruction)
  ↓
exact cosine retrieval from the PLAI index
  ↓
Top-K untrusted document excerpts
  ↓
1 × Ollama /api/chat
  ↓
answer + deterministic Paperless source links
```

There is no LlamaIndex response-refine chain, query-rewrite LLM, reranker LLM or agent loop. Retrieved document text is explicitly framed as untrusted data. Archive-specific claims should be based on the supplied excerpts.

The browser receives generation progress by polling a small same-origin job-status endpoint while the helper consumes Ollama's streaming response. This keeps the Rust core dependency graph small while still updating the visible answer during generation.

Embedding and chat inference use the existing `/coordination/ai.lock`. OCR, metadata classification, RAG chat and RAG-index slices remain serialized. `/coordination/ai-status.json` is informational metadata only and lets a waiting chat explain whether OCR, metadata, another chat or index embedding currently owns the slot; `ai.lock` remains the only synchronization primitive. Both interactive embedding and chat requests use `keep_alive=0`, so their models are released as the request completes before the AI transaction ends. Full-index embedding work is split into bounded slices; the embedding model is reused within a slice, unloaded before the AI lock is released, and other OCR/metadata work can acquire the slot between slices.

## Index

The RAG index is independent of Paperless' native LLM index. Paperless' embedding backend can therefore remain empty when PLAI RAG is used.

Persistent state lives below:

```text
/data/rag/
```

The active index is `rag.db`. A full rebuild uses `rag.db.build`, leaving an existing active index available until the rebuilt database is atomically activated. The SQLite store contains regenerable document chunks, float32 embedding vectors and minimal Paperless metadata. Paperless content remains authoritative.

Default index settings live in `/config/rag-config.json`:

```text
embedding model     qwen3-embedding:4b-q4_K_M
chunk target        4000 characters
chunk overlap       800 characters
embedding batch     16 chunks
embedding slice     64 chunks
sync interval       900 seconds
```

Chat defaults are `qwen3.5:4b`, 8192 context, 512 output tokens, temperature `0.1`, Thinking off and Top-K `5`. Per-chat settings do not alter metadata-classification settings.

The first full index build is explicit. PLAI never starts an expensive initial rebuild merely because the software was updated. Once an active index exists, a lightweight periodic sync checks for new/modified documents and reconciles deletions. Index settings are split conceptually into the active index signature and settings for the next rebuild: changing the configured embedding model does not invalidate the active chat index immediately. Automatic/incremental sync pauses until an explicit rebuild activates the new signature.

A rebuild snapshots target document IDs/modified timestamps into the build database and records completed documents. An interrupted rebuild can therefore resume without discarding completed document versions. A document interrupted during its embedding step is retried as a unit.

## Paperless AI settings

The native Paperless RAG index is not required. When the correspondent Suggestions bridge is used, the intended Paperless AI arrangement is:

```text
Enable AI features:        on
LLM backend:               ollama
LLM model:                 paperless-correspondent-bridge
LLM endpoint:              http://<bridge-host>:30149
LLM embedding backend:     none / empty
LLM embedding model:       empty
LLM embedding endpoint:    empty
```

Paperless uses the bridge only for the narrow Document Suggestions compatibility path. The injected PLAI chat calls the separate PLAI RAG endpoints.

## Upgrade boundary

The RAG indexer reads Paperless through REST API version 10 and does not depend on Paperless' Python RAG classes or native vector-store schema. Existing non-RAG metadata integration keeps its prior API behavior so adding RAG does not broaden that compatibility boundary.

The frontend integration primarily looks for Paperless' `chatDropdown` control. If that element changes, it falls back to the neighboring toast area and finally to a floating button. The chat panel itself is isolated from Paperless component CSS.

Paperless upgrades can therefore affect placement of the injected control, but they do not patch or replace the PLAI RAG implementation. Restart Paperless after updating the integration package so Django reloads the current middleware and assets.
