# Paperless document chat / RAG

`paperless-local-ai` adds multi-turn document chat directly inside the Paperless-ngx web interface. It is optional; OCR and metadata automation continue to work without it.

The chat follows the same hardware design as the rest of PLAI. A normal turn uses one embedding request and one chat-generation request, and heavy chat work waits if OCR, metadata processing or index embedding is already using the shared AI resources.

Vectors are stored in SQLite, so no separate vector-database service is required.

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
- optional Ollama generation controls for Sampler Top-K, Top-P, Min-P, repeat penalty, Repeat last N, seed and stop strings;
- Retrieval Top-K plus per-chat overrides for conversation history, adjacent chunks, document-context budget and retrieval diagnostics;
- incremental answer/status updates, explicit Stop and smart auto-scroll.

Conversation history is stored below `/data/chat` and keyed by the authenticated Paperless user ID supplied by the trusted relay. No chat content is stored in browser session storage. The browser remembers only the current server-side conversation ID.

Closing or navigating away from a chat does not implicitly cancel a running generation. **Stop** is the explicit cancellation action.

### Generation controls

The Control Center defines the global chat defaults. Model, Thinking, context size, temperature and maximum output tokens cover the common settings.

Advanced Ollama generation controls are also available:

- **Sampler Top-K**;
- **Top-P**;
- **Min-P**;
- **Repeat penalty**;
- **Repeat last N**;
- **Seed**;
- **Stop strings**.

When an optional advanced value is left empty, PLAI does not override the corresponding Ollama/model default.

**Sampler Top-K** controls token generation and is separate from **Retrieval Top-K**, which controls how many document chunks are selected from the RAG index.

## Normal RAG pipeline

A normal chat turn always uses the same expensive model steps:

```text
question + selected retrieval history
  ↓
1 × Ollama /api/embed
  ↓
find relevant passages in the PLAI index
  ↓
optionally add neighboring passages
  ↓
read current source metadata from Paperless
  ↓
build the answer prompt within the configured context budget
  ↓
1 × Ollama /api/chat
  ↓
answer + Paperless source links
```

There are no additional LLM calls for query rewriting, reranking, answer refinement, summarization or an agent loop.

Paperless metadata lookups and adjacent-chunk expansion do not add model calls.

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

Source metadata is refreshed from Paperless at chat time, so metadata edits do not require a RAG rebuild. Correspondent/document-type/tag/storage-path names are resolved from Paperless IDs. If supplementary metadata lookup fails, retrieval still has indexed document identity/text and continues without making metadata resolution a second AI dependency.

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

`rag.db` is the active index. `rag.db.build` is a staging database for a full rebuild. The SQLite store contains rebuildable document chunks, float32 embedding vectors and minimal index metadata; Paperless remains authoritative.

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

Chat defaults are `qwen3.5:4b`, 8192 context, 512 output tokens, temperature `0.1`, Thinking off, Retrieval Top-K `5` and 8 previous answer-history messages. Advanced generation settings use the Ollama/model defaults unless configured.

The first full index build starts only when requested. PLAI never begins an expensive initial build merely because the software was installed or updated. Once an active index exists, periodic sync checks for new/modified documents and reconciles deletions.

Structural embedding changes are tracked separately from the active index signature. The active index remains usable until a rebuild completes and atomically replaces it. Batch size, slice size, sync interval and query-side/runtime controls do not invalidate the active corpus vectors.

A rebuild snapshots target document versions and records completed documents in the staging database. Interrupted rebuilds retain completed work. If the core restarts with an interrupted staging index, startup marks it **Paused** and requires Resume rather than automatically continuing heavy work.

## Resource behavior on modest hardware

Only one heavy PLAI workload runs at a time. OCR, metadata classification, Hybrid-history work, document chat and index embedding coordinate through `/coordination/ai.lock`.

If another heavy task is already running, chat waits until it finishes. The UI can show which task it is waiting for. `/coordination/ai-status.json` contains the status shown to the user; the file lock itself is what prevents the workloads from running concurrently.

Interactive embedding and chat requests use `keep_alive=0`, so the model is released when each request finishes.

Full-index work runs in slices. The embedding model is reused within a slice, unloaded at the end of that slice, and the shared AI lock is released before the next slice. This gives waiting OCR or metadata work a chance to run during a long index build.

The default embedding batch size of `1` and slice size of `16` favor predictable CPU and memory use. A full build can take hours on a non-trivial CPU-only archive; this is why initial builds and rebuilds start only when requested, can be paused/resumed and do not replace the active index until the new one is ready.

## Paperless AI settings

Paperless' native embedding/RAG backend is not required.

If the optional correspondent Suggestions bridge is used, Paperless AI can point only its LLM/suggestions path at the bridge while leaving embedding settings empty. The bridge does not provide general chat; PLAI document chat uses the separate same-origin RAG endpoints.

See [Paperless setup](paperless-setup.md) for the current bridge arrangement.

## Compatibility boundary

The indexer reads Paperless through REST API version 10 and does not depend on Paperless' internal Python RAG classes or vector-store schema.

The frontend integration primarily looks for Paperless' `chatDropdown` area and has fallback placement. A Paperless frontend upgrade can therefore affect placement, but it does not replace the PLAI RAG backend. Restart Paperless after updating the integration package so Django reloads the current middleware/assets.

See [Compatibility](compatibility.md) before broadening version claims.
