# Architecture

`paperless-local-ai` is intentionally narrow: replace Tesseract OCR inference with PaddleOCR inside Paperless' normal OCR pipeline and apply local metadata automation while keeping Paperless as the document system of record.

## Why this architecture

The architecture is built around OCR quality, practical local inference on modest CPU-only hardware, and reliable automation inside Paperless:

- **OCR quality before classification:** PP-OCRv6 Medium is the quality-focused default; Small and Tiny trade recognition quality for lower inference cost. HPI/OpenVINO accelerates the selected profile on CPU.
- **One normal LLM request per document:** title, document type, date and sender/issuer are extracted together. Tags are included in that same response only when the active tagging route needs an LLM decision.
- **History-assisted tagging by default:** strong matches against already reviewed Paperless documents may reuse an established tag; unfamiliar documents fall back to the LLM with relevant reviewed examples.
- **Local correspondent resolution:** the LLM extracts the sender once. Python resolves safe existing matches or routes a plausible new name into Paperless Suggestions. No second correspondent-only inference stage is used.
- **Bounded resource usage:** PaddleOCR/OpenVINO and Ollama are serialized through the shared AI lock and heavy processes are released again after use.

## Pipeline

```text
Paperless import
      ↓
Paperless parser / OCRmyPDF
      ↓
OCR needed for a page?
  no  → keep normal Paperless text path
  yes → OCRmyPDF rasterizes page
          ↓
        OCRmyPDF plugin
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
metadata-worker
      ↓
Tagging strategy
  History-assisted:
    strong reviewed-history match → tag fixed by history
    otherwise                    → LLM fallback + reviewed examples
  LLM only:
    LLM decides tags directly
      ↓
one structured LLM request
  title · type · date · sender
  + tags when LLM is responsible
      ↓
local correspondent resolver
  existing safe match → apply
  plausible new name  → Paperless Suggestions
  unreliable/empty    → leave empty
      ↓
Paperless metadata + review
```

The original uploaded PDF remains Paperless' original. OCR happens while Paperless consumes the document; `paperless-local-ai` does not maintain a separate OCR queue.

## Services

One Compose project runs four long-lived services from two images:

| Service | Purpose |
|---|---|
| `ocr-service` | authenticated PaddleOCR service used by the OCRmyPDF plugin |
| `metadata-worker` | history routing, one-call metadata classification and local sender resolution |
| `prompt-ui` | Control Center: configuration, tagging diagnostics, testing and history |
| `suggestion-bridge` | exposes genuinely new correspondent candidates through Paperless Suggestions |

The optional `doctor` profile uses the core image as a one-shot deployment check. Paperless and Ollama remain external.

## OCRmyPDF integration

The OCR image writes `ocrmypdf_plai.py` into the persistent `/integration` mount at startup. Paperless mounts that same host directory read-only and loads the plugin through `PAPERLESS_OCR_USER_ARGS`.

The plugin is verified against OCRmyPDF **17.4.2** as bundled by Paperless-ngx **3.0.5**. It uses OCRmyPDF 17's native `generate_ocr()` interface. For pages handled by the plugin, PaddleOCR is the OCR inference engine instead of Tesseract. No hOCR/XML conversion is used.

## OCR service lifecycle

The OCR service keeps the heavyweight Paddle worker in a spawned subprocess. It acquires the shared global `ai.lock`, initializes the selected PP-OCRv6 profile on the first page, reuses the process briefly across consecutive pages and tears it down after the idle timeout before releasing the lock.

Transient worker/service failures use bounded automatic retries. Deterministic configuration/input failures fail immediately. The Control Center exposes recovery state without exposing document content through the unauthenticated health endpoint.

## Shared OCR/LLM resource lock

OCR and metadata inference share one exclusive file lock below `coordination/ai.lock`. This prevents Paddle/OpenVINO and Ollama from competing for the same CPU/RAM budget. The metadata worker explicitly unloads the configured Ollama model before leaving the AI transaction.

## One structured metadata request

The primary metadata stage produces:

- title;
- document type;
- date;
- actual sender/issuer as free text;
- tags when the active route requires an LLM tag decision.

Document type and LLM-selected tags remain constrained to current Paperless values. Sender extraction is deliberately not constrained to existing correspondents because a real document may introduce a new sender.

A high-confidence History-assisted tag is applied after LLM validation. In that route the schema requires the model to return an empty tag array, so the model cannot overwrite the historical decision.

## Why History-assisted tagging?

Understanding a document topic and consistently mapping that topic to a person's filing taxonomy are different tasks. On the reference CPU-only setup, the compact `qwen3.5:4b` model generally understood document semantics but **did not apply the personal Paperless taxonomy consistently enough across recurring and semantically similar document types to be the sole default tag decision-maker**.

The evaluation progressed from direct tag selection to explicit taxonomy guidance and finally relevant examples from reviewed documents. Relevant examples produced a substantial improvement. Further prompt-rule expansion then produced only marginal net gains and introduced regressions, indicating that additional prompt complexity was no longer a stable way to improve a 4B-class model.

The resulting design therefore separates two cases:

1. **Known/repeating document pattern:** a deliberately strict similarity gate can reuse an already reviewed filing decision.
2. **Unfamiliar/ambiguous document:** the LLM receives the current tag taxonomy, optional user guidance and relevant reviewed examples.

`LLM only` remains a supported strategy because larger or future models may perform substantially better at direct taxonomy mapping.

For the measured reference archive:

| Evaluation | Exact tag result |
|---|---:|
| Direct small-model fallback baseline | 18 / 43 overall fallback documents* |
| Rules + relevant reviewed examples | 33 / 43 |
| Strict historical fast path, retrospective leave-one-out | 89 / 89 routed documents |

\*The baseline completed 38 of 43 model calls successfully and was exact on 18; five calls ended in technical errors.

The historical fast path routed 89 of 132 reviewed documents at the chosen threshold in that archive. Combined with the evaluated few-shot fallback, the retrospective hybrid reached 122/132 exact tag results. These numbers are **archive-specific retrospective measurements, not accuracy guarantees for other archives or future documents**. The historical family holdout was also strongly dominated by work-related documents, so it must not be interpreted as broad 100% generalization.

See [Tagging](tagging.md) for the exact runtime behavior and user-facing diagnostics.

## Why not use Paperless' internal classifier directly?

Paperless-ngx 3.0.5 has its own automatic classifier and trains it from non-Inbox documents for metadata objects configured with automatic matching. That remains a useful Paperless feature.

`paperless-local-ai` uses its own read-only history index because the integration needs properties that are important to this routing design:

- an explicit similarity value for a conservative automatic threshold;
- support and agreement checks before a historical tag may be reused;
- the same nearest reviewed documents as few-shot examples for the LLM fallback;
- no dependency on Paperless' internal sklearn model format or probability internals;
- no requirement to change the user's Paperless tags to `Automatic` matching.

This is a control/integration choice, not a claim that the custom retriever is universally more accurate than Paperless' classifier.

## History index

History-assisted tagging reads documents that have **left the configured review tag** and are no longer in the classification queue/error state. The current document is excluded from its own lookup. Parent tags automatically present because of Paperless hierarchy are pruned when a more specific selected child is present.

Text similarity combines equal-weight TF-IDF cosine similarity from:

- word n-grams 1–2;
- `char_wb` character n-grams 3–5.

A tag is reused only when all strict gates pass: the nearest reviewed document has exactly one leaf tag, its similarity is at least `0.60`, that tag also wins the weighted top-five neighborhood, at least two neighbors support it, and its weighted share is at least `0.50`.

If the gate fails, up to five relevant reviewed examples are supplied to the LLM fallback. Empty-tag examples are not injected; at most two examples with the same tag combination are used.

The index checks for source changes at most every five minutes when used and is rebuilt only when relevant reviewed-document state or the Paperless tag taxonomy changed. The Control Center can request an immediate refresh. No separate model-training job is required.

## History diagnostics

The Control Center exposes user-facing History health rather than raw ML internals:

- reviewed document count;
- represented tags and per-tag history depth;
- retrospective estimated reuse using leave-one-out routing;
- last index update;
- **Potential tag inconsistencies**.

Potential inconsistencies use complete-linkage groups at the calibrated `0.50` similarity threshold and highlight groups that currently use different leaf-tag assignments. They are diagnostic hints only: different tags can be intentional, and the application never rewrites historical metadata from this check.

## Tag guidance

Tag guidance is separate from History-assisted matching. One optional description is stored per Paperless tag ID and rendered dynamically in the Control Center.

Guidance is supplied only when the LLM decides tags:

- every document in `LLM only`;
- only fallback documents in `History-assisted`.

A high-confidence history match does not use the descriptions. Storing guidance by Paperless tag ID allows a tag rename to keep its description.

## Correspondent resolution

The main LLM call extracts the actual sender/issuer without restricting it to existing Paperless values. The local resolver then:

1. normalizes Unicode, case, whitespace and punctuation and applies an exact existing match when unique;
2. allows only a deliberately strong and clearly separated fuzzy match to be applied automatically;
3. sends any other plausible sender name to the existing suggestion bridge for human review;
4. leaves empty/unreliable output unresolved.

A new correspondent is never auto-created.

## Configuration and state

Deployment owns secrets and Docker-level settings. The Control Center owns normal runtime and classification settings.

Persistent state lives below one `APP_DATA_DIR`:

```text
config/        app and classification configuration/history
core/          results and open correspondent review records
ocr/           PaddleX/OpenVINO cache and OCR runtime state
coordination/  shared ai.lock + OCR recovery + history refresh marker
integration/   generated OCRmyPDF plugin consumed by Paperless
```

The pre-0.3 separate correspondent configuration is no longer read by the runtime.

## Suggestion bridge identity

For Paperless-ngx 3.0.5, open correspondent review records are matched by a SHA-256 signature of normalized document content used by Paperless' no-RAG AI classifier. Ambiguous matches fail closed. Filename matching is deliberately not used because Paperless' internal model filename and normal REST filename fields are not equivalent.
