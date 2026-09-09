# Architecture

`paperless-local-ai` is a CPU-first local-AI companion stack for Paperless-ngx. It adds three bounded capabilities around an existing Paperless installation: PaddleOCR-based scan OCR, structured metadata automation, and a lightweight document-chat/RAG path. Paperless stays the document system of record and Ollama stays external.

The architecture intentionally targets modest CPU-only home-server hardware. Heavy OCR, scientific-history work, metadata inference, query embedding, chat generation and index embedding are coordinated instead of competing for memory and CPU.

## Design goals

- **Modest hardware is a first-class target:** no GPU is required; heavy AI work is serialized and heavyweight runtimes/models are released after use.
- **OCR quality before downstream AI:** PP-OCRv6 Medium is the quality-focused default, with Small and Tiny profiles for lower inference cost.
- **One structured metadata request per document:** title, document type, date and sender/issuer are extracted together; tags join that request only when the selected tag route needs an LLM decision.
- **Hybrid tagging for compact models:** recurring reviewed patterns can reuse a complete known leaf-tag set behind a strict evidence gate; uncertain cases use an LLM fallback with Tag Guidance and relevant reviewed examples.
- **Conservative correspondent resolution:** the LLM extracts one free-text sender/issuer; local Rust logic resolves safe existing matches or exposes a plausible new name through Paperless Document Suggestions.
- **Lightweight RAG instead of an AI platform:** the chat uses a regenerable SQLite index, exact cosine retrieval, one embed + one chat call per normal turn, and no vector database, reranker LLM, refine chain or agent framework.
- **Paperless remains authoritative:** originals, searchable archives, document content and metadata live in Paperless; PLAI caches/indexes are disposable application state.

## Pipeline

The import/automation and interactive-chat paths share the same Paperless archive but have different lifecycles.

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
scope + current question + bounded prior context
      ↓
one Ollama query embedding
      ↓
exact cosine retrieval from /data/rag/rag.db
      ↓
optional adjacent chunks + live Paperless source metadata
      ↓
one Ollama chat generation
      ↓
answer + deterministic Paperless source links
```

The uploaded PDF stays Paperless' original. OCR happens while Paperless consumes the document. RAG indexing is independent, explicit/regenerable background work and never becomes a second authoritative archive.

## Services

One Compose project runs two long-lived services from two images:

| Service | Purpose |
|---|---|
| `ocr-service` | authenticated PaddleOCR service used by the OCRmyPDF plugin |
| `core-service` | one lightweight Rust process hosting metadata queue polling, the Control Center, the optional suggestion bridge, the RAG relay/job launcher and the on-demand History broker |

The optional `doctor` profile uses the core image as a one-shot deployment check. Paperless and Ollama are external services. The suggestion-bridge endpoint is included in `core-service`, but configuring Paperless to use it is optional; without it, safe matching to existing correspondents still works and unmatched sender candidates are handled manually during review.

The core image defaults to `/usr/local/bin/plai-core`. It retains `/app/core_service.py` as an exec-based compatibility shim for stored 0.3.4 commands and also keeps standalone `worker.py`, `prompt_ui.py` and `suggestion_bridge.py` entry points for deployments that explicitly invoke them. A separate std-only `/usr/local/bin/plai-healthcheck` probes the Control Center and suggestion bridge without starting the full core or Python. The same tiny probe is shipped statically in the OCR image and checks `/health` with `--ocr`, avoiding a recurring Python/urllib healthcheck process in the OCR cgroup.

## RAG chat

Document chat is a supported project capability, but its implementation is intentionally small enough for resource-constrained CPU-only servers.

`core-service` exposes secret-protected `/api/rag/*` job endpoints and launches `/app/rag_engine.py` only for index/chat work. The helper uses Paperless REST API v10, stores a regenerable SQLite index under `/data/rag`, performs exact cosine retrieval locally and exits after the job. No additional long-running RAG service or vector database is used.

For a normal turn, the helper uses the shared AI lock across one Ollama `/api/embed` request, local retrieval/prompt assembly and one streaming `/api/chat` request. Query-side embeddings use the configured query template; indexed chunks use the configured document template. Both interactive requests use `keep_alive=0`. This fixed path deliberately excludes query-rewrite, reranker, refine, summarizer and agent LLM calls.

Retrieved chunks can be expanded with adjacent chunks without another model call. Before prompt assembly, source metadata is refreshed from Paperless. The default source template supplies source number, title, created date, correspondent, document type, document ID and retrieved text; the Control Center exposes additional Paperless document fields as optional template variables. Live metadata lookup adds Paperless HTTP requests, not extra Ollama requests.

The first full index build is explicit. `rag.db.build` keeps completed rebuild work separate from the active `rag.db`, and activation is atomic. Structural embedding changes mark the configured index as requiring a rebuild while the active index continues serving queries. Rebuild embedding is split into bounded slices and releases the shared AI slot between slices so OCR and metadata are not starved. Interrupted rebuild staging is retained and reconciled to a paused state for explicit resume.

The Paperless-side integration is same-origin and currently superuser-only. It performs CSRF validation for writes and forwards only a fixed allow-list using an internal relay secret. The browser never receives that secret or the Paperless API token.

See [RAG chat](rag-chat.md).

## OCRmyPDF integration

The OCR image writes `ocrmypdf_plai.py` into the persistent `/integration` mount at startup. Paperless mounts that directory read-only and loads the plugin through `PAPERLESS_OCR_USER_ARGS`.

The plugin is verified against OCRmyPDF **17.7.1** as bundled by Paperless-ngx **3.1.0**. It implements OCRmyPDF 17's native `generate_ocr()` interface and returns `OcrElement` geometry directly.

For OCRmyPDF 17.7.1, the plugin installs a narrow version-gated compatibility shim through OCRmyPDF's `initialize()` plugin hook. The native `generate_ocr()` / fpdf2 path can otherwise pass an unusable zero `PdfInfo` DPI to the renderer for hybrid/vector PDFs after PaddleOCR has already completed successfully. Immediately before fpdf2 rendering, the shim selects DPI from the returned OCR `OcrElement`, then PDFInfo, then OCRmyPDF's `VECTOR_PAGE_DPI`. This mirrors OCRmyPDF's hOCR fallback order and keeps text geometry aligned when the OCR-only raster is downsampled. Installed OCRmyPDF files are never modified.

## OCR service lifecycle

The OCR service keeps the heavyweight Paddle worker in a normal short-lived Python subprocess connected over a private local socket. It acquires the shared `ai.lock`, initializes the selected PP-OCRv6 profile on the first required page and reuses the process briefly across consecutive pages. After the configured short warm-session idle timeout it stops the Paddle worker and releases `ai.lock` immediately. The lightweight OCR HTTP service then remains available for a fixed five-minute quiet period after the Paddle worker has become idle, allowing later pages or documents in the same batch to start a fresh Paddle worker without colliding with an intentional container restart. Only after that extended quiet period does the OCR service exit cleanly so the existing `restart: unless-stopped` policy starts a fresh container/cgroup. The restarted service stays lightweight because its recurring healthcheck uses the static std-only probe instead of launching Python. This keeps heavyweight OCR memory and the shared AI slot short-lived while still returning OCR to a genuinely cold idle memory state after the batch has ended, without cgroup privileges or global cache manipulation; no Python multiprocessing helper remains resident.

Transient worker/service failures use bounded automatic retries. Deterministic configuration/input failures fail immediately. Recovery state is exposed through the Control Center without exposing document content through the unauthenticated health endpoint.

## Shared AI resource lock

OCR, Hybrid-history work, metadata inference, RAG query/chat inference and RAG index slices share one exclusive file lock at `/coordination/ai.lock`. This prevents Paddle/OpenVINO, the scientific history helper and Ollama from performing heavy work concurrently. Automatic metadata routing shuts the history helper down before the Ollama request starts, and the core metadata worker unloads the configured Ollama model before leaving the AI transaction. Heavy resources are therefore released immediately when their work completes, independently of the lightweight unified core lifecycle. After a complete metadata batch or explicit History refresh, the core schedules a clean container recycle only after a fixed five-minute quiet period. New metadata work cancels the pending recycle, and Suggestion Bridge classification activity during the grace period postpones it. This keeps the Control Center and Suggestion Bridge available for normal follow-up requests while still allowing the existing `restart: unless-stopped` policy to start a fresh core cgroup after genuine inactivity, clearing file cache accumulated by the on-demand scientific helper and heavy Rust code paths while preserving all persistent state on mounted storage.

## Structured metadata request

The LLM always produces:

- title;
- document type;
- date;
- actual sender/issuer as free text.

Tags are included only when the active tag route assigns the decision to the LLM. Document type and LLM-selected tags are constrained to current Paperless values. Sender extraction is free text because a document can introduce a sender that does not yet exist in Paperless.

### Editable prompt composition

Classification configuration owns three editable prompt components:

1. **System prompt** — global model instructions and untrusted-content framing.
2. **Base classification prompt** — the always-present metadata task and document text.
3. **Tagging prompt** — tag-selection instructions plus placeholders for the current taxonomy, Tag Guidance and retrieved examples.

The runtime composes the request according to the tag route. A confident Hybrid match sends only System + Base classification and builds a schema **without a `tags` property**. The complete reviewed leaf-tag set is inserted after the base result validates. Hybrid fallback and LLM direct append the configured Tagging prompt and include constrained tags in the schema.

The application controls composition; the prompt text itself stays user-configurable. The Control Center preview shows the final messages and schema.

## Hybrid tagging

Hybrid tagging uses a read-only similarity index over reviewed Paperless documents. Full text is represented by equal-weight TF-IDF word 1–2-grams and `char_wb` character 3–5-grams.

History votes on complete reviewed leaf-tag sets rather than labels independently. A set is reused only when the nearest reviewed document reaches the configured similarity gate (default `0.62`), its complete set wins the similarity-weighted top-five neighborhood, enough neighbors carry that exact set (default support `2`), the set reaches the configured winner share (default `0.50`), and it does not exceed the configured maximum tag count. History never synthesizes an unseen combination; those cases fall back to the LLM.

If the gate abstains, up to five relevant positive reviewed examples are supplied through the editable Tagging prompt. At most two examples with the same tag combination are used.

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

Paperless-ngx already provides optional native AI features. The comparison here is anchored to **Paperless-ngx 3.1.0**, the current end-to-end tested reference for this project. The native chat contract described below was also source-checked in Paperless-ngx 3.1.1, 3.1.2 and 3.1.3.

### Metadata

Paperless 3.1.0 builds one structured AI suggestion request for title, tags, correspondents, document types, storage paths and dates. If output localization is requested, a second model request can localize supported returned text fields.

PLAI also keeps its normal metadata generation to one structured request. The difference is workflow and control: classification is triggered automatically from the configured Paperless Document Added workflow, tags can take the Hybrid-history fast path or receive reviewed examples on fallback, prompt components and rendered schema are inspectable, correspondent resolution is performed conservatively after generation, and the resulting metadata is written back behind an explicit human-review boundary.

PLAI currently does not manage storage paths. Paperless native AI suggestions remain a separate feature and can still be used for capabilities that PLAI does not replace.

See [Paperless native classifier vs Hybrid tagging](tagging.md#paperless-native-classifier-vs-hybrid-tagging).

### Document chat

Paperless 3.1.0 through 3.1.3 use a single-turn native chat backend. `stream_chat_with_documents()` receives a current `query_str` and a document queryset plus access/output-language flags; it does not receive a conversation identifier or previous user/assistant messages.

Its retrieval/synthesis path is also framework-driven:

1. create a LlamaIndex `VectorIndexRetriever` with `similarity_top_k=5`;
2. retrieve once to determine the source-document references returned to the UI;
3. create LlamaIndex QA and refine templates plus the default response synthesizer;
4. pass the same retriever to `RetrieverQueryEngine`;
5. execute the query, causing the query engine to retrieve again before response synthesis;
6. synthesize the answer through LlamaIndex's default `COMPACT` mode, implemented as `CompactAndRefine`.

The native AI configuration exposes generation and embedding backends/models, context size, embedding chunk size and related connection settings. Retrieval Top-K, conversation/retrieval history, similarity/document caps, adjacent chunks, retrieval diagnostics and prompt/index lifecycle controls are not exposed as native chat controls in the Paperless 3.1.0 through 3.1.3 path described above.

PLAI owns this path directly instead:

```text
current question + bounded retrieval history
  -> exactly one Ollama /api/embed request
  -> exact local cosine retrieval from SQLite
  -> optional adjacent chunks + live Paperless source metadata
  -> explicit prompt/context-budget assembly
  -> exactly one Ollama /api/chat request
  -> answer + deterministic Paperless source links
```

There is no query-rewrite LLM, reranker LLM, refine chain, summarizer or agent loop on the normal PLAI path. Adjacent-chunk expansion, live metadata lookup and retrieval diagnostics add no model request.

PLAI also persists conversations server-side. Retrieval history and answer-model history are separate bounded controls, so follow-up questions can intentionally use earlier turns rather than every question being an isolated request.

This bounded execution model is part of the CPU-first architecture: on modest local hardware, each heavyweight model operation is explicit and shares the same global AI resource slot as OCR, metadata work and index embedding.

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

Deployment owns secrets and Docker-level settings. The Control Center owns normal runtime and classification settings.

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
