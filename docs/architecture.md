# Architecture

`paperless-local-ai` is a companion stack for Paperless-ngx. It improves scanned-page OCR through Paperless/OCRmyPDF plus a local PaddleOCR service and applies local metadata automation while keeping Paperless as the document system of record.

## Design goals

- **OCR quality before classification:** PP-OCRv6 Medium is the quality-focused default, with Small and Tiny profiles for lower inference cost.
- **One structured LLM request per document:** title, document type, date and sender/issuer are extracted together; tags join that request only when the selected tag route needs an LLM decision.
- **Hybrid tagging:** recurring reviewed patterns can reuse a tag behind a strict evidence gate; uncertain cases use an LLM fallback with Tag Guidance and relevant reviewed examples.
- **Local correspondent resolution:** the LLM extracts one free-text sender/issuer; Python resolves safe existing matches or exposes a plausible new name through Paperless Document Suggestions.
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
    confident reviewed match → tag fixed locally
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
| `core-service` | one lightweight Python process hosting metadata queue polling, the Control Center, the optional suggestion bridge and the on-demand History broker |

The optional `doctor` profile uses the core image as a one-shot deployment check. Paperless and Ollama are external services. The suggestion-bridge endpoint is included in `core-service`, but configuring Paperless to use it is optional; without it, safe matching to existing correspondents still works and unmatched sender candidates are handled manually during review.

The core image also provides standalone `worker.py`, `prompt_ui.py` and `suggestion_bridge.py` entry points for deployments that explicitly invoke those components.

## OCRmyPDF integration

The OCR image writes `ocrmypdf_plai.py` into the persistent `/integration` mount at startup. Paperless mounts that directory read-only and loads the plugin through `PAPERLESS_OCR_USER_ARGS`.

The plugin is verified against OCRmyPDF **17.4.2** as bundled by Paperless-ngx **3.0.5**. It implements OCRmyPDF 17's native `generate_ocr()` interface and returns `OcrElement` geometry directly.

## OCR service lifecycle

The OCR service keeps the heavyweight Paddle worker in a spawned subprocess. It acquires the shared `ai.lock`, initializes the selected PP-OCRv6 profile on the first required page, reuses the process briefly across consecutive pages and tears it down after the idle timeout before releasing the lock.

Transient worker/service failures use bounded automatic retries. Deterministic configuration/input failures fail immediately. Recovery state is exposed through the Control Center without exposing document content through the unauthenticated health endpoint.

## Shared AI resource lock

OCR, Hybrid-history work and metadata inference share one exclusive file lock at `/coordination/ai.lock`. This prevents Paddle/OpenVINO, the scientific history helper and Ollama from performing heavy work concurrently. Automatic metadata routing shuts the history helper down before the Ollama request starts, and the core metadata worker unloads the configured Ollama model before leaving the AI transaction.

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

The runtime composes the request according to the tag route. A confident Hybrid match sends only System + Base classification and builds a schema **without a `tags` property**. The reviewed tag is inserted after the base result validates. Hybrid fallback and LLM direct append the configured Tagging prompt and include constrained tags in the schema.

The application controls composition; the prompt text itself stays user-configurable. The Control Center preview shows the final messages and schema.

## Hybrid tagging

Hybrid tagging uses a read-only similarity index over reviewed Paperless documents. Full text is represented by equal-weight TF-IDF word 1–2-grams and `char_wb` character 3–5-grams.

A tag is reused only when the nearest reviewed document has exactly one leaf tag, similarity is at least `0.60`, that tag wins the weighted top-five neighborhood, at least two neighbors support it, and its weighted share is at least `0.50`.

If the gate abstains, up to five relevant positive reviewed examples are supplied through the editable Tagging prompt. At most two examples with the same tag combination are used.

The configured review tag is the trust boundary and can have any name. It stays on a document until human review is complete. Documents still carrying review, classification-queue or classification-error tags are excluded, and the current document is excluded from its own lookup.

The persistent unified core process does not import NumPy, SciPy or scikit-learn. `core-service` hosts a lightweight Unix-socket broker that starts one scientific history subprocess on demand. A validated local TF-IDF cache avoids refitting unchanged reviewed history, and the helper reconstructs the existing cosine nearest-neighbor view from the cached sparse matrix. Interactive Control Center lookups can reuse the helper for a short idle window; automatic metadata batches and model tests shut it down before Ollama starts.

The cache is internal application state below `/data/history-cache`. It uses Python pickle protocol 5 only for artifacts created by this application, records exact Python/NumPy/SciPy/scikit-learn plus algorithm/source signatures, and is SHA-256 verified inside the disposable helper immediately before unpickling. The persistent UI checks only lightweight metadata/source state and never reads the cache blob into memory. Invalid caches are rebuilt and cache files are written atomically.

See [Tagging](tagging.md) for the detailed rationale, Paperless-native comparison and diagnostics.

## History diagnostics

The Control Center exposes:

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

Paperless-ngx 3.0.5 includes its own trained automatic classifier. Hybrid tagging uses a separate retrieval/gating layer because this workflow needs an explicit similarity/support decision, a deliberate LLM fallback and the same nearest reviewed documents as prompt examples. This is an integration/control choice rather than a universal accuracy claim. See [Paperless native classifier vs Hybrid tagging](tagging.md#paperless-native-classifier-vs-hybrid-tagging).

## Correspondent resolution

The main LLM request extracts the sender/issuer without restricting it to existing Paperless values. The resolver then:

1. applies a unique normalized exact match;
2. accepts a deliberately strong, clearly separated fuzzy match;
3. exposes other plausible names through the suggestion bridge for human review;
4. leaves empty/unreliable extraction unresolved.

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

For Paperless-ngx 3.0.5, open correspondent review records are matched by a SHA-256 signature of normalized document content used by Paperless' no-RAG AI classifier. Ambiguous matches fail closed. Filename matching is deliberately not used because Paperless' internal model filename and normal REST filename fields are not equivalent.
