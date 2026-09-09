# Paperless document chat / RAG

`paperless-local-ai` provides a deliberately lightweight local document-chat path directly inside the Paperless-ngx web interface. It is a first-class project capability, while remaining opt-in for deployments that only want OCR/metadata automation.

The design target is the same as the rest of the project: **useful local AI on modest CPU-only hardware**. RAG therefore reuses the existing core service and shared AI lock, stores vectors in SQLite, and keeps the normal turn to one embedding request plus one chat-generation request.

Paperless remains unmodified and remains the document system of record.

## UI integration

When the Paperless UI integration is enabled, a same-origin JavaScript asset injects the PLAI chat control into Paperless. The native Paperless chat component is hidden only after a successful PLAI bootstrap; if PLAI cannot initialize after a future Paperless frontend change, the integration fails open and leaves Paperless usable.

The chat panel is isolated in Shadow DOM. Keyboard events are stopped at that boundary after PLAI controls handle them, so typing in chat/model/scope/settings fields does not trigger Paperless global shortcuts.

Browser requests stay on the Paperless origin below `/_plai/`. Paperless authenticates the browser session, requires a superuser for the current implementation, applies CSRF protection to writes and relays only a fixed allow-list of requests to `core-service`. The relay uses an internal random secret stored in the shared integration directory. Neither that secret nor the Paperless API token is exposed to browser JavaScript.

Global RAG/index administration lives in the **Control Center → Document Chat** page. The Paperless chat panel contains conversation and per-chat controls, not a second copy of the index administration UI.

## Chat behavior

The panel supports:

- persistent server-side conversations that can be opened from another browser/device;
- new/open/rename/delete chat history without an LLM title-generation call;
- scopes `Current document`, `All documents`, `Tag`, `Correspondent` and `Document type`;
- type-ahead Paperless scope selection by stable IDs;
- Current-document scope that follows Paperless SPA navigation while the panel remains open;
- clickable Paperless source documents;
- installed Ollama model discovery plus free model entry;
- Thinking `Auto`, `Off` or `On`;
- context size, temperature and maximum output tokens;
- retrieval Top-K plus per-chat overrides for conversation history, adjacent chunks, document-context budget and retrieval diagnostics;
- incremental answer/status updates, explicit Stop and smart auto-scroll.

Conversation history is stored below `/data/chat` and keyed by the authenticated Paperless user ID supplied by the trusted relay. No chat content is stored in browser session storage. The browser remembers only the current server-side conversation ID.

Closing or navigating away from a chat does not implicitly cancel a running generation. **Stop** is the explicit cancellation action.

## Normal RAG pipeline

A normal chat turn has a fixed heavy-work shape:

```text
question + bounded retrieval history
  ↓
1 × Ollama /api/embed
  ↓
exact cosine retrieval from the PLAI SQLite index
  ↓
optional adjacent chunks (local only)
  ↓
live Paperless metadata for selected source documents
  ↓
prompt assembly / context budgeting
  ↓
1 × Ollama /api/chat
  ↓
answer + deterministic Paperless source links
```

There is no query-rewrite LLM, reranker LLM, response-refine chain, summarizer or agent loop on the normal path.

Paperless metadata lookups and adjacent-chunk expansion are local/API work and do not add model calls.

## Prompt assembly and source metadata

Three global prompt layers are configurable under **Control Center → Document Chat**:

- **System prompt** — global answer behavior, time/user/search-scope variables and untrusted-document framing;
- **Retrieved source template** — rendered once per selected source;
- **Answer prompt template** — wraps the rendered source blocks plus the current question.

The default source template is:

```text
[Source {{SOURCE_NUMBER}}]
Title: {{DOCUMENT_TITLE}}
Created: {{DOCUMENT_CREATED}}
Correspondent: {{DOCUMENT_CORRESPONDENT}}
Document type: {{DOCUMENT_TYPE}}
Document ID: {{DOCUMENT_ID}}

{{CHUNK}}
```

Source metadata is refreshed from Paperless at chat time, so metadata edits do not require a RAG rebuild. Correspondent/document-type/tag/storage-path names are resolved from Paperless IDs. If supplementary metadata lookup fails, retrieval still has indexed document identity/text and fails open rather than making metadata resolution a second AI dependency.

The variable catalog also exposes fields such as tags, storage path, page count, MIME type, notes, custom fields, versions, owner/permissions and raw/metadata JSON. `DOCUMENT_CONTENT` and `DOCUMENT_RAW_JSON` can be very large and are intended for expert templates only.

Retrieved document text is untrusted data. The default System prompt instructs the model not to follow instructions contained inside source documents.

## Retrieval controls

Global defaults are:

| Setting | Default |
|---|---|
| Retrieval Top-K | `5` |
| Retrieval history mode | user messages only |
| Previous user turns for retrieval | `3` |
| Minimum similarity | disabled |
| Max primary chunks per document | unlimited |
| Adjacent chunks | Off |
| Document context budget | Auto |
| Retrieval diagnostics | Off |

Retrieval history is separate from answer-model conversation history. The answer model receives up to **8 previous user/assistant messages** by default, while the embedding query uses the current question plus up to **3 previous user turns**.

Adjacent chunks add neighboring text around a primary similarity hit after ranking. They do not change Top-K ranking and do not cause another embedding/chat request.

Diagnostics can persist the effective retrieval query, similarity scores, selected chunk ordinals/neighbors, rendered source previews and prompt-budget statistics. They are disabled by default and do not add inference.

## Index and current defaults

The PLAI RAG index is independent of Paperless' native LLM index. Paperless' embedding backend can remain empty when PLAI RAG is used.

Persistent state lives below:

```text
/data/rag/
```

`rag.db` is the active index. `rag.db.build` is a staging database for a full rebuild. The SQLite store contains regenerable document chunks, float32 embedding vectors and minimal index metadata; Paperless remains authoritative.

Current defaults:

| Setting | Default |
|---|---|
| Embedding model | `qwen3-embedding:4b-q4_K_M` |
| Query template | Qwen3-Embedding retrieval instruction |
| Document template | `{{CHUNK}}` |
| Chunk target | `2000` characters |
| Chunk overlap | `400` characters |
| Embedding batch size | `1` |
| Embedding slice size | `16` chunks |
| Sync interval | `900` seconds |
| Query/document truncation | enabled |
| Embedding dimensions/context override | model default / Auto |

Chat defaults are `qwen3.5:4b`, 8192 context, 512 output tokens, temperature `0.1`, Thinking off, Top-K `5` and 8 previous answer-history messages.

The first full index build is explicit. PLAI never starts an expensive initial rebuild merely because the software was installed or updated. Once an active index exists, periodic sync checks for new/modified documents and reconciles deletions.

Structural embedding changes are tracked separately from the active index signature. The active index remains usable until an explicit rebuild completes and atomically replaces it. Batch size, slice size, sync interval and query-side/runtime controls do not invalidate the active corpus vectors.

A rebuild snapshots target document versions and records completed documents in the staging database. Interrupted rebuilds retain completed work. If the core restarts with an interrupted staging index, startup reconciles it to **Paused** and requires explicit Resume rather than automatically resuming heavy work.

## Resource behavior on modest hardware

OCR, metadata classification, Hybrid-history work, RAG chat and index embedding share `/coordination/ai.lock`.

A waiting chat can report which heavy workload currently owns the slot. `/coordination/ai-status.json` is display metadata only; the file lock is the synchronization primitive.

Interactive embedding and chat requests use `keep_alive=0`, so each model is released when its request completes. Full-index work is split into bounded slices; the embedding model is reused only within the slice and unloaded before the lock is released.

The default embedding batch size of `1` and slice size of `16` favor predictable CPU-only behavior. On limited CPUs a full index build should be expected to take substantially longer than on GPU hardware, potentially hours for a non-trivial archive. This is why initial/rebuild work is explicit, resumable and non-destructive to the active index.

## Paperless AI settings

Paperless' native embedding/RAG backend is not required.

If the optional correspondent Suggestions bridge is used, Paperless AI can point only its LLM/suggestions path at the bridge while leaving embedding settings empty. The bridge does not provide general chat; PLAI document chat uses the separate same-origin RAG endpoints.

See [Paperless setup](paperless-setup.md) for the current bridge arrangement.

## Compatibility boundary

The indexer reads Paperless through REST API version 10 and does not depend on Paperless' internal Python RAG classes or vector-store schema.

The frontend integration primarily looks for Paperless' `chatDropdown` area and has fallback placement. A Paperless frontend upgrade can therefore affect placement, but it does not replace the PLAI RAG backend. Restart Paperless after updating the integration package so Django reloads the current middleware/assets.

See [Compatibility](compatibility.md) before broadening version claims.
