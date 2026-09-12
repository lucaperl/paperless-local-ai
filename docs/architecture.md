# Architecture

`paperless-local-ai` is a local-AI companion for Paperless-ngx. It adds PaddleOCR-based scan OCR, structured metadata automation and document chat/RAG around an existing Paperless installation. Paperless remains the document system of record, while Ollama runs separately.

The architecture is designed around modest CPU-only home-server hardware. Only one heavy PLAI workload runs at a time, so PaddleOCR, Ollama, Hybrid-history work and index embedding do not reach their peak CPU and memory use at the same time. Heavy components are started when needed and released again afterward.

## Design goals

- **Work well without a GPU:** heavy workloads run one at a time, and large runtimes/models are released again after use.
- **Run better OCR only where it is needed:** Paperless/OCRmyPDF still decides whether a page needs OCR; PP-OCRv6 handles the recognition step for those pages.
- **Use one metadata model request per document:** title, document type, date and sender/issuer are extracted together; tags join the same request only when the selected tagging route needs the LLM.
- **Help compact models with reviewed history:** Hybrid tagging can reuse a complete reviewed tag set when the evidence is strong enough and falls back to the LLM when it is not.
- **Do not create correspondents automatically:** the model extracts a sender, then local matching resolves safe existing matches or leaves a new candidate for review.
- **Keep document chat simple:** a normal turn uses one embedding request and one chat-generation request, with no separate vector database or additional rewrite/rerank/refine/agent model stages.
- **Keep Paperless authoritative:** originals, searchable archives, document content and metadata stay in Paperless. PLAI's caches and indexes can be rebuilt.

## Pipeline

The import/automation and interactive-chat paths share the same Paperless archive but have different lifecycles.

### Import and metadata flow

The detailed import, OCR, metadata and review path:

<p align="center">
  <img src="../images/paperless-flow.svg" alt="paperless-local-ai import and metadata workflow" width="65%">
</p>

### End-to-end paths

```text
IMPORT / AUTOMATION

Paperless import
      ↓
Paperless parser / OCRmyPDF
      ↓
OCR needed for a page?
  no  → existing Paperless text path
  yes → OCRmyPDF rasterizes page
          ↓
        paperless-local-ai OCR plugin
          ↓
        PaddleOCR / PP-OCRv6
          ↓
        native OcrElement tree
          ↓
OCRmyPDF searchable archive / PDF-A
      ↓
Paperless extracted content
      ↓
Document Added workflow
      ↓
metadata queue
      ↓
Hybrid tagging or LLM direct
      ↓
one structured LLM request
      ↓
local correspondent resolution
      ↓
Paperless metadata + human review


INTERACTIVE DOCUMENT CHAT

Paperless chat panel
      ↓
scope + current question + selected prior context
      ↓
one Ollama query embedding
      ↓
exact cosine retrieval from /data/rag/rag.db
      ↓
optional adjacent chunks + current Paperless source metadata
      ↓
one Ollama chat generation
      ↓
answer + Paperless source links
```

The uploaded PDF stays Paperless' original. OCR happens while Paperless consumes the document. The RAG index is separate from Paperless and can be rebuilt at any time; it never becomes a second authoritative document store.

## Services

One Compose project runs two long-lived services from two images:

| Service | Purpose |
|---|---|
| `ocr-service` | authenticated PaddleOCR service used by the OCRmyPDF plugin |
| `core-service` | one lightweight Rust process hosting metadata queue polling, the Control Center, the optional suggestion bridge, the RAG relay/job launcher and the on-demand History broker |

On the reference system, the validated combined cold-idle footprint of `core-service` and `ocr-service` is about **18.6 MiB RAM** after heavy helpers have been released and both services have recycled back to idle.

The optional `doctor` profile uses the core image as a one-shot deployment check. Paperless and Ollama are external services. The suggestion-bridge endpoint is included in `core-service`, but configuring Paperless to use it is optional; without it, safe matching to existing correspondents still works and unmatched sender candidates are handled manually during review.

The core image defaults to `/usr/local/bin/plai-core`. It retains `/app/core_service.py` as an exec-based compatibility shim for stored 0.3.4 commands and also keeps standalone `worker.py`, `prompt_ui.py` and `suggestion_bridge.py` entry points for deployments that explicitly invoke them. A separate std-only `/usr/local/bin/plai-healthcheck` probes the Control Center and suggestion bridge without starting the full core or Python. The same tiny probe is shipped statically in the OCR image and checks `/health` with `--ocr`, avoiding a recurring Python/urllib healthcheck process in the OCR cgroup.

## RAG chat

Document chat reuses the existing `core-service` and does not require a separate long-running RAG service or vector database.

`core-service` exposes the protected `/api/rag/*` job endpoints and starts `/app/rag_engine.py` only when index or chat work is needed. The helper reads documents through Paperless REST API v10, stores a rebuildable SQLite index below `/data/rag`, performs cosine retrieval locally and exits after the job.

A normal chat turn uses one Ollama `/api/embed` request and one streaming `/api/chat` request. The shared AI lock prevents that heavy model work from running at the same time as OCR, metadata inference or another PLAI heavy workload.

Query embeddings use the configured query template; indexed chunks use the configured document template. Both interactive requests use `keep_alive=0`. A normal turn does not add separate LLM calls for query rewriting, reranking, refinement, summarization or an agent loop.

Retrieved chunks can be expanded with neighboring chunks without another model call. Before the answer prompt is built, source metadata is refreshed from Paperless. The default source template supplies source number, title, created date, correspondent, document type, document ID and retrieved text; the Control Center exposes additional Paperless document fields as optional template variables. These metadata lookups add Paperless API requests, not additional Ollama requests.

The first full index build never starts automatically. On CPU-only hardware it can take hours, so the user starts it when appropriate. Rebuilds are prepared in `rag.db.build` while the existing `rag.db` remains usable. Structural embedding changes mark the configured state as requiring a rebuild, but the current index continues serving queries until the replacement is ready. Embedding work runs in slices and releases the shared AI slot between slices, allowing waiting OCR or metadata work to run. Interrupted rebuilds remain available for Resume instead of starting from zero.

The Paperless-side integration is same-origin and currently superuser-only. It validates CSRF-protected writes and forwards only a fixed allow-list using an internal relay secret. The browser never receives that secret or the Paperless API token.

See [RAG chat](rag-chat.md).

## OCRmyPDF integration

The OCR image writes `ocrmypdf_plai.py` into the persistent `/integration` mount at startup. Paperless mounts that directory read-only and loads the plugin through `PAPERLESS_OCR_USER_ARGS`.

The plugin is verified against OCRmyPDF **17.7.1** as bundled by Paperless-ngx **3.1.0**. It implements OCRmyPDF 17's native `generate_ocr()` interface and returns `OcrElement` geometry directly.

For OCRmyPDF 17.7.1, the plugin installs a narrow version-gated compatibility shim through OCRmyPDF's `initialize()` plugin hook. The native `generate_ocr()` / fpdf2 path can otherwise pass an unusable zero `PdfInfo` DPI to the renderer for hybrid/vector PDFs after PaddleOCR has already completed successfully. Immediately before fpdf2 rendering, the shim selects DPI from the returned OCR `OcrElement`, then PDFInfo, then OCRmyPDF's `VECTOR_PAGE_DPI`. This mirrors OCRmyPDF's hOCR fallback order and keeps text geometry aligned when the OCR-only raster is downsampled. Installed OCRmyPDF files are never modified.

## OCR service lifecycle

The OCR service keeps the expensive PaddleOCR runtime alive only while it is useful.

The lightweight OCR HTTP service starts a separate Paddle worker when the first page needs OCR. That worker acquires the shared `ai.lock`, loads the selected PP-OCRv6 profile and can be reused briefly for consecutive pages. After the configured warm-session idle timeout, the Paddle worker stops and releases the AI lock immediately.

The lightweight HTTP service remains available for another five minutes before its container exits cleanly. This avoids restarting the container between closely spaced documents while still returning the OCR container to a genuinely cold idle state after the batch has ended. The existing `restart: unless-stopped` policy then starts a fresh lightweight container.

The restarted service stays small because its recurring healthcheck uses the static `plai-healthcheck` probe instead of starting Python. No Python multiprocessing helper remains resident after the Paddle worker has stopped.

Transient worker/service failures use bounded automatic retries. Configuration errors, invalid input and other failures that are not expected to recover are returned immediately. Recovery state is shown in the Control Center without exposing document content through the unauthenticated health endpoint.

## Shared AI resource lock

Only one heavy PLAI workload runs at a time.

OCR, Hybrid-history work, metadata inference, RAG chat and RAG index embedding coordinate through the exclusive file lock at `/coordination/ai.lock`. If another heavy task is already running, the next one waits until the lock is free.

This prevents Paddle/OpenVINO, Ollama and the scientific History helper from reaching their peak CPU and memory use at the same time.

Automatic metadata processing stops the History helper before starting Ollama, and the metadata worker unloads the configured Ollama model before allowing the next heavy workload to start. These heavy resources are therefore released as soon as their part of the work is finished.

After a complete metadata batch or manual History refresh, `core-service` waits for a five-minute quiet period before allowing its container to recycle. New metadata work cancels the pending recycle, and Suggestion Bridge activity postpones it. This keeps the Control Center and Suggestion Bridge available for normal follow-up requests while still allowing the container to return to a clean idle state after genuine inactivity.

## Structured metadata request

The LLM always produces:

- title;
- document type;
- date;
- actual sender/issuer as free text.

Tags are included only when the active tag route assigns the decision to the LLM. Document type and LLM-selected tags are constrained to current Paperless values. Sender extraction is free text because a document can introduce a sender that does not yet exist in Paperless.

### Editable prompt composition

Classification uses three editable prompt components:

1. **System prompt** — global model instructions and untrusted-content framing.
2. **Base classification prompt** — the always-present metadata task and document text.
3. **Tagging prompt** — tag-selection instructions plus placeholders for the current taxonomy, Tag Guidance and retrieved examples.

Which prompt parts are sent depends on the selected tag route. A confident Hybrid match sends only System + Base classification and builds a schema **without a `tags` property**. The complete reviewed leaf-tag set is inserted after the base result validates. Hybrid fallback and LLM direct append the configured Tagging prompt and include constrained tags in the schema.

The application decides which components are required; the prompt text itself stays user-configurable. The Control Center preview shows the final messages and schema.

## Hybrid tagging

Hybrid tagging uses a read-only similarity index over reviewed Paperless documents. Full text is represented by equal-weight TF-IDF word 1–2-grams and `char_wb` character 3–5-grams.

History votes on complete reviewed leaf-tag sets rather than labels independently. A set is reused only when the nearest reviewed document reaches the configured similarity gate (default `0.62`), its complete set wins the similarity-weighted top-five neighborhood, enough neighbors carry that exact set (default support `2`), the set reaches the configured winner share (default `0.50`), and it does not exceed the configured maximum tag count. History never synthesizes an unseen combination; those cases fall back to the LLM.

If the confidence checks do not all pass, Hybrid falls back to the LLM. Up to five relevant reviewed examples are then supplied through the editable Tagging prompt. At most two examples with the same tag combination are used.

The configured review tag is the trust boundary and can have any name. It stays on a document until human review is complete. Documents still carrying review, classification-queue or classification-error tags are excluded, and the current document is excluded from its own lookup.

The persistent unified core is Rust and does not load NumPy, SciPy or scikit-learn. It hosts a lightweight Unix-socket broker that starts one Python scientific-history subprocess on demand. A validated local TF-IDF cache avoids refitting unchanged reviewed history, and the helper reconstructs the existing cosine nearest-neighbor view from the cached sparse matrix. Interactive Control Center lookups can reuse the helper for a short idle window; automatic metadata batches and model tests shut it down before Ollama starts. On final helper shutdown, read-only file-backed scientific-runtime mappings are paged out before immediate process exit so they do not become persistent core cgroup cache.

The cache is internal application state below `/data/history-cache`. It uses Python pickle protocol 5 only for artifacts created by this application, records exact Python/NumPy/SciPy/scikit-learn plus algorithm/source signatures, and is SHA-256 verified inside the disposable helper immediately before unpickling. The persistent UI checks only lightweight metadata/source state and never reads the cache blob into memory. Invalid caches are rebuilt and cache files are written atomically.

See [Tagging](tagging.md) for the detailed rationale, Paperless-native comparison and diagnostics.

## History diagnostics

The Control Center exposes:

- supported History matching controls for minimum similarity, support and winner share;
- reviewed-document count;
- represented tags;
- retrospective estimated reusable history;
- History depth by tag;
- last index update;
- Potential tag inconsistencies.

Potential inconsistencies use complete-linkage clustering on the same document representation at minimum similarity `0.50`. Only groups with at least three documents and multiple leaf-tag assignments are shown. They are review hints and never rewrite historical metadata.

## Tag Guidance

One optional description is stored per Paperless tag ID. Guidance is supplied only when the LLM is responsible for tags, so a confident Hybrid match is unaffected by it.

## Native Paperless AI and PLAI

Paperless-ngx already provides optional native AI features. The comparison below reflects the Paperless versions currently covered by this project; see [Compatibility](compatibility.md) for the exact tested and source-checked versions.

### Metadata

Paperless can generate one structured AI suggestion covering title, tags, correspondents, document types, storage paths and dates. Depending on the configured output-language behavior, localization can add another model request.

PLAI also keeps normal metadata generation to one structured request. The main differences are the surrounding workflow and controls: classification runs automatically from the configured Paperless Document Added workflow, Hybrid tagging can reuse reviewed history or provide reviewed examples to the LLM, the classification prompts and final schema can be inspected, and correspondent matching happens locally after generation.

PLAI currently does not manage storage paths. Native Paperless AI can still be used for features that PLAI does not replace.

See [Paperless native classifier vs Hybrid tagging](tagging.md#paperless-native-classifier-vs-hybrid-tagging).

### Document chat

In the Paperless versions currently covered by this project, the native server-side chat handles the current question and selected documents without receiving earlier user/assistant turns.

Its retrieval and answer path uses LlamaIndex:

1. create a `VectorIndexRetriever` with `similarity_top_k=5`;
2. retrieve once to determine the source-document references returned to the UI;
3. create the QA/refine templates and response synthesizer;
4. pass the retriever to `RetrieverQueryEngine`;
5. run the query, which retrieves again for answer generation;
6. generate the answer through LlamaIndex's `COMPACT` / `CompactAndRefine` response mode.

Paperless lets users configure the generation and embedding backends/models, context size, embedding chunk size and connection settings. Its native chat does not provide user settings for the prompts, retrieval Top-K, conversation/retrieval history, similarity or per-document retrieval limits, adjacent chunks, retrieval diagnostics or index lifecycle.

PLAI handles this path itself, which allows those parts to be configured:

```text
current question + selected retrieval history
  -> one Ollama /api/embed request
  -> local cosine retrieval from SQLite
  -> optional adjacent chunks + current Paperless source metadata
  -> prompt/context-budget assembly
  -> one Ollama /api/chat request
  -> answer + Paperless source links
```

A normal PLAI turn does not add query-rewrite, reranker, refine, summarizer or agent LLM calls. Adjacent chunks, metadata lookup and retrieval diagnostics are local/API work and do not add another model request.

PLAI also stores conversations server-side. Retrieval history and answer-model history are configured separately, so follow-up questions can use earlier turns without forcing the same amount of history into every stage.

This matters on modest CPU-only hardware because every additional model request can add noticeable latency, while the shared AI lock prevents chat from running its heavy work at the same time as OCR, metadata inference or index embedding.

## Correspondent resolution

The main LLM request extracts the sender/issuer without restricting it to existing Paperless values. The resolver then:

1. applies a unique normalized exact match;
2. otherwise ranks existing correspondents with the project's SequenceMatcher-compatible name metric;
3. accepts the fuzzy winner only when it reaches the configured minimum similarity (default `0.91`) and leads the runner-up by the configured minimum winner margin (default `0.04`);
4. exposes other plausible names through the suggestion bridge for human review;
5. leaves empty/unreliable extraction unresolved.

The two fuzzy thresholds are versioned App Settings and support their complete natural `0.0-1.0` ranges. **App Settings → Matching** also includes a read-only simulator that runs the same resolver against the current Paperless correspondent list and returns the top three candidates plus both decision gates. Unique normalized exact matches bypass the fuzzy thresholds.

There is no additional minimum-name-length fuzzy gate: every plausible non-exact sender is scored. The defaults remain conservative, while installations that prefer best-effort correspondent population during human review can deliberately lower the thresholds without adding another LLM call. New correspondents are never auto-created.

## Configuration and state

Deployment stores secrets and Docker-level settings. The Control Center stores normal runtime and classification settings.

Persistent state lives below one `APP_DATA_DIR`:

```text
config/        app and classification configuration/history
core/          results, review records, history cache, server-side chats and regenerable RAG index
ocr/           PaddleX/OpenVINO cache and OCR runtime state
coordination/  shared ai.lock + OCR recovery + history broker socket
integration/   generated OCRmyPDF plugin consumed by Paperless
```

## Suggestion bridge identity

For Paperless-ngx 3.1.0, open correspondent review records are matched by a SHA-256 signature of normalized document content used by Paperless' no-RAG AI classifier. Ambiguous matches fail closed. Filename matching is deliberately not used because Paperless' internal model filename and normal REST filename fields are not equivalent.
