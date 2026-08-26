# Configuration

The **Control Center** is the main interface for `paperless-local-ai` configuration, testing and configuration history.

## Recommended first-time setup order

1. **App Settings → Connections** — configure and test Paperless and Ollama.
2. **App Settings → Pipeline & Tags** — choose classification queue/error/review tag names.
3. **App Settings → OCR** — choose OCR language, PaddleOCR model, maximum image side and retry behavior.
4. Complete the matching [Paperless setup](paperless-setup.md), including the review-tag lifecycle, Paperless matching settings, metadata workflow and OCRmyPDF integration.
5. **App Settings → Runtime** — leave metadata writes enabled or temporarily use Dry Run for read-only metadata testing.
6. **Classification → Tagging** — choose Hybrid tagging or LLM direct and optionally describe ambiguous tags.
7. **Classification → Prompt** — review the editable System, Base classification and Tagging prompts.
8. **Classification → Test** — run a safe preview/model test against an existing document.

Saved app/classification configurations are versioned and can be restored from the UI.

## Connections

Configure the Paperless and Ollama base URLs. The Paperless API token stays a deployment secret and is never shown by the UI or stored in JSON configuration history.

The URLs must be reachable **from the app containers**. `localhost` inside a container is not the Docker/TrueNAS host.

## Pipeline & tags

Configure the classification queue tag, classification error tag, review tag and any additional tags excluded from content classification. These names must match existing Paperless tags exactly.

The review tag can have any name; `Inbox` is only the fresh-install default. Keep the configured review tag on a document until human review is complete. Remove it after review; the document becomes eligible for trusted Hybrid retrieval only when the review, classification queue and classification error tags are all absent. The recommended Paperless setup marks the chosen review tag as an **Inbox tag** so Paperless adds it automatically on import. Alternatively, add that tag explicitly in the Document Added workflow.

For an exclusive paperless-local-ai metadata workflow, set Paperless **Matching algorithm** to **None** for the content tags, document types, correspondents and technical workflow/review tags managed by paperless-local-ai. This prevents Paperless matching from independently assigning the same metadata before paperless-local-ai writes its result. Storage paths are not managed by paperless-local-ai and do not need this change. See [Paperless setup](paperless-setup.md#2-metadata-and-review-tags).

OCR runs inside Paperless/OCRmyPDF import and does not use classification queue/error tags.

## OCR

Configure OCR language, PaddleOCR model, maximum OCR image side, retry schedule and inference device.

| PaddleOCR model | Intended use |
|---|---|
| **PP-OCRv6 Medium** | highest recognition quality; default |
| **PP-OCRv6 Small** | lower inference cost with a quality/performance trade-off |
| **PP-OCRv6 Tiny** | lowest inference cost; lower recognition accuracy |

PP-OCRv6 Tiny does not support Japanese.

The temporary OCR raster is limited by `ocr.max_side_pixels`. Default: **3000 px** on the longest side; supported range: **2000–4000 px**. This changes only the temporary OCR input and never resizes the original/archive page.

### Automatic OCR retries

Default retry delays: **`15, 60, 300, 600`** seconds. Each value adds one retry. Leave the field empty to disable automatic retries.

Only potentially recoverable failures are retried. Invalid authentication, OCR-language mismatch, malformed input and invalid configuration fail immediately. During a retry wait the failed Paddle process is stopped and the shared AI lock is released. **Retry now** skips the remaining delay before the next already-scheduled attempt; it does not add attempts.

Paperless defaults `PAPERLESS_WORKER_TIMEOUT` to 1800 seconds; if the configured total retry window substantially exceeds that, raise the Paperless timeout accordingly.

HPI/OpenVINO, CPU/thread/RAM/shared-memory and OCR idle limits stay deployment settings because they affect container/runtime construction.

## Reference performance and resource tuning

Measured on an **Intel Core i3-8100 · 4 cores / 4 threads · 16 GB RAM · no GPU · qwen3.5:4b Q4_K_M · PP-OCRv6 Medium / HPI / OpenVINO**.

| Workload | Document size | Prompt size | Processing time | Peak RAM |
|---|---|---:|---:|---:|
| OCR · PP-OCRv6 Medium · 3000 px | per page | — | ~23 s/page | ~4.3 GiB |
| Metadata · qwen3.5:4b Q4_K_M | ~1–2 pages | ~1–4k tokens | ~40 s–2.5 min | ~4.2 GiB |
| Metadata · qwen3.5:4b Q4_K_M | ~3–4 pages | ~5–9k tokens | ~3–5.5 min | ~4.2 GiB |
| Metadata · qwen3.5:4b Q4_K_M | ~5–6 pages | ~9–12k tokens | ~5.5–7.5 min | ~4.2 GiB |

Page count is only a rough indication of metadata cost. Runtime primarily follows the number of prompt tokens actually processed. Hybrid matches tend toward the lower end because tagging context is omitted, while fallback requests also include the tag taxonomy, guidance and retrieved examples. A 7-page fallback with ~14k prompt tokens took ~8.7 minutes.

The **Context window** sets the maximum context available to Ollama and affects RAM usage. It does not mean every request processes the full configured context. A larger context window allows larger prompts; large prompts can substantially increase CPU inference time. The **Document text limit** is measured in characters and controls how much Paperless text can enter the prompt before head/tail truncation.

Additional memory reference points:

| Workload | Configuration | Measured peak |
|---|---|---:|
| OCR | PP-OCRv6 Medium · 3000 px | ~4.3 GiB |
| OCR | PP-OCRv6 Medium · 3200 px | ~4.9–5.1 GiB |
| OCR | PP-OCRv6 Medium · 4000 px | ~6.5 GiB |
| Metadata | qwen3.5:4b Q4_K_M · 4k context | ~3.6 GiB |
| Metadata | qwen3.5:4b Q4_K_M · 8k context | ~3.8 GiB |
| Metadata | qwen3.5:4b Q4_K_M · 16k context | ~4.2 GiB |

PaddleOCR, on-demand Hybrid-history work and Ollama inference are serialized through the shared AI resource lock. The scientific history helper is released before automatic/model-test Ollama inference, so its temporary memory does not remain resident through the LLM phase.

If RAM is limited, lower **Maximum OCR image side** first when OCR is the problem and reduce the Classification **Context window** when the LLM is the problem. `OCR_MEMORY_LIMIT` is a deployment safety ceiling; raising it does not reduce memory use.

## Runtime

Configure metadata Dry Run plus advanced worker polling/review-cleanup intervals.

### Dry Run

Dry Run is optional and defaults to **Off**. It affects the metadata worker, not Paperless import/OCR. With Dry Run enabled, the worker still performs routing/classification and stores result JSON, but it does not write title, type, date, content tags, correspondent or a persistent new-correspondent review record. Technical workflow/error tags may still change.

## Classification

Classification controls one structured local-LLM request. The model always handles title, document type, date and the actual sender/issuer. Tags join the request only when the active tag route needs an LLM decision.

Document type and LLM-selected tags are constrained to current Paperless values. Correspondent output is free text and is resolved locally after the call.

The **Context window** is the maximum capacity available to the request, not the number of tokens processed by every classification. Actual latency mainly follows the rendered prompt size. The **Document text limit** is a character limit; longer Paperless text is truncated by keeping the configured share from the beginning and the remainder from the end.

### Prompt composition

Three prompt fields are editable and versioned together:

- **System prompt** — global model behavior and untrusted-content framing.
- **Base classification prompt** — title, document type, sender/issuer, date and `{{DOCUMENT_TEXT}}`.
- **Tagging prompt** — tag-selection behavior and the dynamic tag context.

The Tagging prompt is appended only when the LLM is responsible for tag selection. On a confident Hybrid match, the Tagging prompt is not sent and the generated structured schema contains no `tags` property. The complete reviewed leaf-tag set is inserted after the base metadata result validates.

The Tagging prompt can use `{{TAGS_JSON}}`, `{{TAGS_LINES}}`, `{{MAX_TAGS}}`, `{{TAG_GUIDANCE}}` and `{{TAG_EXAMPLES}}`. The final rendered messages and schema are always visible under **Classification → Test → Preview prompts**.

English and German presets populate all three prompt fields. Loading a preset changes the draft only; save to activate it.

### Tagging strategy

**Hybrid tagging — Recommended for small models**
Compares documents with reviewed examples and reuses a complete known leaf-tag set only when similarity and neighbor agreement are strong. Otherwise the LLM decides using Tag Guidance and relevant examples. [How Hybrid tagging works](tagging.md#hybrid-tagging).

**LLM direct — For more capable models**
The configured model chooses tags for every document. Reviewed examples are not used for routing or retrieved prompt examples.

### Advanced History matching

The collapsed **Advanced History matching** section under **Classification → Tagging → History health** exposes the three supported confidence controls. They are stored in versioned App Settings even though they are shown next to the History diagnostics.

| Setting | Default | Meaning |
|---|---:|---|
| Minimum similarity | `0.62` | the closest reviewed document must reach this cosine similarity before its complete leaf-tag set can be reused |
| Minimum support | `2` | at least this many of the five nearest reviewed documents must carry the winning complete leaf-tag set |
| Minimum winner share | `0.50` | the winning complete set must receive at least this share of the similarity-weighted neighborhood vote |

Lower values increase automatic History reuse but also increase the risk of an incorrect tag set. The existing **Maximum LLM tags** setting also caps a History fast-path set: a reviewed set larger than that limit falls back to the LLM. History only reuses complete combinations that are present in reviewed documents; it never constructs an unseen combination from individually supported tags.

Changing one of these values invalidates the derived History status/cache signature. The next Hybrid use rebuilds it automatically, or **Refresh reviewed history** can rebuild it immediately.

### Tag Guidance

The Control Center dynamically shows one optional guidance field per current Paperless content tag. Guidance is stored by Paperless tag ID, so renaming a tag keeps its description.

Guidance is supplied whenever the LLM chooses tags. A confident Hybrid match does not send Tag Guidance to the model.

### History health

The Tagging tab shows reviewed-document count, represented tags, **Retrospective history reuse**, **History depth by tag** and **Potential tag inconsistencies**.

History depth is based only on the number of reviewed examples for a tag:

| Reviewed examples | Depth |
|---:|---|
| 0 | No history |
| 1 | Very limited |
| 2–4 | Limited |
| 5–9 | Good |
| 10+ | Strong |

This is an evidence-depth indicator, not an accuracy score or match probability.

The reuse estimate uses retrospective leave-one-out routing and counts only cases where the strict Hybrid gate reproduces the existing complete reviewed leaf-tag set. It does not predict future accuracy.

Potential tag inconsistencies group at least three strongly similar reviewed documents when their leaf-tag assignments differ. They are review hints only and never change Paperless metadata.

The persistent Control Center and metadata worker do not keep the scientific TF-IDF runtime resident. A lightweight source-signature check detects relevant Paperless/taxonomy changes. On Hybrid use, an on-demand helper loads a validated local cache or rebuilds it when the source, algorithm or runtime versions changed. **Refresh reviewed history** forces an immediate rebuild. Interactive preview work can reuse the helper briefly; automatic metadata batches and model tests release it before Ollama inference.

### Safe interactive testing

For an existing Paperless document, **Preview prompts** shows the exact tag route, structured schema and rendered messages without calling Ollama. **Run model test** performs the real local model request and local sender resolution. Neither modifies the selected Paperless document or persists a suggestion. On CPU-only systems a model test can take from tens of seconds to several minutes; prompt size is the main driver.

## Correspondents

The classification request extracts the actual sender/issuer as a short free-text name. Local resolution can apply a normalized exact match or a deliberately strong unambiguous fuzzy match. Other plausible names can be exposed through Paperless Document Suggestions when the optional suggestion bridge is configured; unreliable output is left empty.

New correspondents are never auto-created. The optional Paperless Suggestions integration exposes plausible unmatched sender names in Paperless' native Document Suggestions. Without that integration, classification and safe matching to existing correspondents continue normally, but paperless-local-ai does not surface unmatched sender candidates in Paperless Suggestions; handle those manually during review.

## Ollama lifecycle

The metadata worker uses the configured model for the structured request and unloads it before releasing the shared AI transaction. `keep_alive` is still available as an Ollama request parameter, while explicit unload is the standard end-of-document behavior.

## Language

The Control Center interface is English. Fresh installations start with OCR language `en` and English prompt presets. English and German presets are available for System, Base classification and Tagging prompts.

OCR language is independent from prompt/UI language.

## Deployment-only settings

These values stay outside the Control Center because Docker/Paperless needs them before startup or because they are secrets:

- `PAPERLESS_TOKEN`;
- `OCR_SERVICE_TOKEN`;
- image/version;
- `APP_DATA_DIR`;
- host bind addresses and ports;
- OCR HPI/OpenVINO enablement;
- OCR CPU/thread/RAM/shared-memory/idle limits;
- Paperless-side `PLAI_OCR_*` values and OCRmyPDF plugin configuration.

Changing deployment-owned values requires recreating/redeploying the affected containers.
