# Architecture

`paperless-local-ai` is a companion stack for Paperless-ngx. It improves scanned-page OCR through Paperless/OCRmyPDF plus a local PaddleOCR service and applies local metadata automation while keeping Paperless as the document system of record.

## Design goals

- **OCR quality before classification:** PP-OCRv6 Medium is the quality-focused default, with Small and Tiny profiles for lower inference cost.
- **One structured LLM request per document:** title, document type, date and sender/issuer are extracted together; tags join that request only when the selected tag route needs an LLM decision.
- **Hybrid tagging:** recurring reviewed patterns can reuse a complete known leaf-tag set behind a strict evidence gate; cases without a confident observed-set match use an LLM fallback with Tag Guidance and relevant reviewed examples.
- **Local correspondent resolution:** the LLM extracts one free-text sender/issuer; Rust resolves safe existing matches or exposes a plausible new name through Paperless Document Suggestions.
- **Bounded resource usage:** PaddleOCR/OpenVINO, Hybrid-history work and Ollama share one AI resource lock; heavyweight OCR/history subprocesses and the Ollama model are released after use.

## Pipeline

```text
Paperless import
      ↓
Paperless parser / OCRmyPDF
      ↓
OCR needed for a page?
  no  → existing Paperless text path
  yes → OCRmyPDF rasterizes page
          ↓
        paperless-local-ai OCR plugin
          ↓ authenticated HTTP
        ocr-service
        PaddleOCR / PP-OCRv6
          ↓
        native OcrElement tree
          ↓
OCRmyPDF searchable archive / PDF-A
Paperless extracted content
      ↓
Paperless Document Added workflow
      ↓
classification queue tag
      ↓
core-service metadata worker
      ↓
Tagging strategy
  Hybrid tagging:
    confident reviewed match → complete reviewed leaf-tag set fixed locally
    otherwise                → LLM tag fallback + reviewed examples
  LLM direct:
    LLM decides tags directly
      ↓
one structured LLM request
  title · type · date · sender
  + tags only when the LLM is responsible
      ↓
local correspondent resolver
  existing safe match → apply
  plausible new name  → optional Paperless Suggestions integration
  unreliable/empty    → leave empty
      ↓
Paperless metadata + review
      ↓
human review removes configured review tag
      ↓
eligible for trusted Hybrid history
```

The uploaded PDF stays Paperless' original. OCR happens while Paperless consumes the document; `paperless-local-ai` does not maintain a separate OCR queue.

## Services

One Compose project runs two long-lived services from two images:

| Service | Purpose |
|---|---|
| `ocr-service` | authenticated PaddleOCR service used by the OCRmyPDF plugin |
| `core-service` | one lightweight Rust process hosting metadata queue polling, the Control Center, the optional suggestion bridge and the on-demand History broker |

The optional `doctor` profile uses the core image as a one-shot deployment check. Paperless and Ollama are external services. The suggestion-bridge endpoint is included in `core-service`, but configuring Paperless to use it is optional; without it, safe matching to existing correspondents still works and unmatched sender candidates are handled manually during review.

The core image defaults to `/usr/local/bin/plai-core`. It retains `/app/core_service.py` as an exec-based compatibility shim for stored 0.3.4 commands and also keeps standalone `worker.py`, `prompt_ui.py` and `suggestion_bridge.py` entry points for deployments that explicitly invoke them. A separate std-only `/usr/local/bin/plai-healthcheck` probes the Control Center and suggestion bridge without starting the full core or Python. The same tiny probe is shipped statically in the OCR image and checks `/health` with `--ocr`, avoiding a recurring Python/urllib healthcheck process in the OCR cgroup.

## OCRmyPDF integration

The OCR image writes `ocrmypdf_plai.py` into the persistent `/integration` mount at startup. Paperless mounts that directory read-only and loads the plugin through `PAPERLESS_OCR_USER_ARGS`.

The plugin is verified against OCRmyPDF **17.7.1** as bundled by Paperless-ngx **3.1.0**. It implements OCRmyPDF 17's native `generate_ocr()` interface and returns `OcrElement` geometry directly.

## OCR service lifecycle

The OCR service keeps the heavyweight Paddle worker in a normal short-lived Python subprocess connected over a private local socket. It acquires the shared `ai.lock`, initializes the selected PP-OCRv6 profile on the first required page and reuses the process briefly across consecutive pages. After the configured short warm-session idle timeout it stops the Paddle worker and releases `ai.lock` immediately. The lightweight OCR HTTP service then remains available for a fixed five-minute quiet period after the Paddle worker has become idle, allowing later pages or documents in the same batch to start a fresh Paddle worker without colliding with an intentional container restart. Only after that extended quiet period does the OCR service exit cleanly so the existing `restart: unless-stopped` policy starts a fresh container/cgroup. The restarted service stays lightweight because its recurring healthcheck uses the static std-only probe instead of launching Python. This keeps heavyweight OCR memory and the shared AI slot short-lived while still returning OCR to a genuinely cold idle memory state after the batch has ended, without cgroup privileges or global cache manipulation; no Python multiprocessing helper remains resident.

Transient worker/service failures use bounded automatic retries. Deterministic configuration/input failures fail immediately. Recovery state is exposed through the Control Center without exposing document content through the unauthenticated health endpoint.

## Shared AI resource lock

OCR, Hybrid-history work and metadata inference share one exclusive file lock at `/coordination/ai.lock`. This prevents Paddle/OpenVINO, the scientific history helper and Ollama from performing heavy work concurrently. Automatic metadata routing shuts the history helper down before the Ollama request starts, and the core metadata worker unloads the configured Ollama model before leaving the AI transaction. Heavy resources are therefore released immediately when their work completes, independently of the lightweight unified core lifecycle. After a complete metadata batch or explicit History refresh, the core schedules a clean container recycle only after a fixed five-minute quiet period. New metadata work cancels the pending recycle, and Suggestion Bridge classification activity during the grace period postpones it. This keeps the Control Center and Suggestion Bridge available for normal follow-up requests while still allowing the existing `restart: unless-stopped` policy to start a fresh core cgroup after genuine inactivity, clearing file cache accumulated by the on-demand scientific helper and heavy Rust code paths while preserving all persistent state on mounted storage.

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

## Paperless native classifier

Paperless-ngx 3.1.0 includes its own trained automatic classifier. Hybrid tagging uses a separate retrieval/gating layer because this workflow needs an explicit similarity/support decision, a deliberate LLM fallback and the same nearest reviewed documents as prompt examples. This is an integration/control choice rather than a universal accuracy claim. See [Paperless native classifier vs Hybrid tagging](tagging.md#paperless-native-classifier-vs-hybrid-tagging).

## Correspondent resolution

The main LLM request extracts the sender/issuer without restricting it to existing Paperless values. The resolver then:

1. applies a unique normalized exact match;
2. otherwise ranks existing correspondents with the project's SequenceMatcher-compatible name metric;
3. accepts the fuzzy winner only when it reaches the configured minimum similarity (default `0.93`) and leads the runner-up by the configured minimum winner margin (default `0.04`);
4. exposes other plausible names through the suggestion bridge for human review;
5. leaves empty/unreliable extraction unresolved.

The two fuzzy thresholds are versioned App Settings. **App Settings → Matching** also includes a read-only simulator that runs the same resolver against the current Paperless correspondent list and returns the top three candidates plus both decision gates. Unique normalized exact matches bypass the fuzzy thresholds.

The resolver is intentionally fail-closed: an uncertain name is preferable as a review suggestion rather than being mapped automatically to the wrong existing correspondent. New correspondents are never auto-created.

## Configuration and state

Deployment owns secrets and Docker-level settings. The Control Center owns normal runtime and classification settings.

Persistent state lives below one `APP_DATA_DIR`:

```text
config/        app and classification configuration/history
core/          results, open correspondent review records and history index cache
ocr/           PaddleX/OpenVINO cache and OCR runtime state
coordination/  shared ai.lock + OCR recovery + history broker socket
integration/   generated OCRmyPDF plugin consumed by Paperless
```

## Suggestion bridge identity

For Paperless-ngx 3.1.0, open correspondent review records are matched by a SHA-256 signature of normalized document content used by Paperless' no-RAG AI classifier. Ambiguous matches fail closed. Filename matching is deliberately not used because Paperless' internal model filename and normal REST filename fields are not equivalent.
