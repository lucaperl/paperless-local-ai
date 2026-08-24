# Configuration

The **Control Center** is the main interface for normal `paperless-local-ai` configuration, testing and configuration history.

## Recommended first-time setup order

1. **App Settings → Connections** — configure and test Paperless and Ollama.
2. **App Settings → Pipeline & Tags** — choose classification queue/error/review tag names.
3. **App Settings → OCR** — choose OCR language, PaddleOCR model, image limit and retry behavior.
4. **App Settings → Runtime** — choose whether metadata writes are enabled.
5. **Classification → Tagging** — choose Hybrid tagging or LLM direct and optionally describe ambiguous tags.
6. **Classification → Prompt** — review the editable System, Base classification and Tagging prompts.
7. **Classification → Test** — run a safe preview/model test against an existing document.
8. Complete the matching [Paperless setup](paperless-setup.md).

Saved app/classification configurations are versioned and can be restored from the UI.

## Connections

Configure the Paperless and Ollama base URLs. The Paperless API token stays a deployment secret and is never shown by the UI or stored in JSON configuration history.

The URLs must be reachable **from the app containers**. `localhost` inside a container is not the Docker/TrueNAS host.

## Pipeline & tags

Configure the classification queue tag, classification error tag, review tag and any additional tags excluded from content classification.

OCR runs inside Paperless/OCRmyPDF import and does not use classification queue/error tags.

The **review tag is also the trust boundary for Hybrid tagging**. Documents become eligible for reviewed retrieval after they leave this tag. Documents still carrying the classification queue or error tag are excluded as well.

## OCR

Configure OCR language, PaddleOCR model, maximum temporary OCR image dimension, retry schedule and inference device.

| PaddleOCR model | Intended use |
|---|---|
| **PP-OCRv6 Medium** | highest recognition quality; default |
| **PP-OCRv6 Small** | lower inference cost with a quality/performance trade-off |
| **PP-OCRv6 Tiny** | lowest inference cost; lower recognition accuracy |

PP-OCRv6 Tiny does not support Japanese.

The temporary OCR image is limited by `ocr.max_side_pixels`. Default: **3000 px** on the longest side; supported range: **2000–4000 px**. This changes only the temporary OCR input and never resizes the original/archive page.

### RAM usage and tuning

| Workload | Configuration | Measured peak |
|---|---|---:|
| OCR | PP-OCRv6 Medium · 3000 px | ~4.4–4.7 GiB |
| OCR | PP-OCRv6 Medium · 3200 px | ~4.9–5.1 GiB |
| OCR | PP-OCRv6 Medium · 4000 px | ~6.5 GiB |
| Metadata | qwen3.5:4b Q4_K_M · 4k context | ~3.6 GiB |
| Metadata | qwen3.5:4b Q4_K_M · 8k context | ~3.8 GiB |
| Metadata | qwen3.5:4b Q4_K_M · 16k context | ~4.2 GiB |

PaddleOCR and Ollama inference are serialized through the shared AI resource lock, so the heavy peaks normally do not overlap.

If RAM is limited, lower **Maximum OCR image dimension** first when OCR is the problem and reduce the Classification **Context window** when the LLM is the problem. `OCR_MEMORY_LIMIT` is a deployment safety ceiling; raising it does not reduce memory use.

### Automatic OCR retries

Default retry delays: **`15, 60, 300, 600`** seconds. Each value adds one retry. Leave the field empty to disable automatic retries.

Only potentially recoverable failures are retried. Invalid authentication, OCR-language mismatch, malformed input and invalid configuration fail immediately. During a retry wait the failed Paddle process is stopped and the shared AI lock is released. **Retry now** skips the remaining delay before the next already-scheduled attempt; it does not add attempts.

Paperless defaults `PAPERLESS_WORKER_TIMEOUT` to 1800 seconds; if the configured total retry window substantially exceeds that, raise the Paperless timeout accordingly.

HPI/OpenVINO, CPU/thread/RAM/shared-memory and OCR idle limits stay deployment settings because they affect container/runtime construction.

## Runtime

Configure metadata Dry Run plus advanced worker polling/review-cleanup intervals.

### Dry Run

Dry Run affects the metadata worker, not Paperless import/OCR. The worker still performs routing/classification and stores result JSON, but it does not write title, type, date, content tags, correspondent or a persistent new-correspondent review record. Technical workflow/error tags may still change.

## Classification

Classification controls one structured local-LLM request. The model always handles title, document type, date and the actual sender/issuer. Tags join the request only when the active tag route needs an LLM decision.

Document type and LLM-selected tags are constrained to current Paperless values. Correspondent output is free text and is resolved locally after the call.

### Prompt composition

Three prompt fields are editable and versioned together:

- **System prompt** — global model behavior and untrusted-content framing.
- **Base classification prompt** — title, document type, sender/issuer, date and `{{DOCUMENT_TEXT}}`.
- **Tagging prompt** — tag-selection behavior and the dynamic tag context.

The Tagging prompt is appended only when the LLM is responsible for tag selection. On a confident Hybrid match, the Tagging prompt is not sent and the generated structured schema contains no `tags` property. The reviewed tag is inserted after the base metadata result validates.

The Tagging prompt can use `{{TAGS_JSON}}`, `{{TAGS_LINES}}`, `{{MAX_TAGS}}`, `{{TAG_GUIDANCE}}` and `{{TAG_EXAMPLES}}`. The final rendered messages and schema are always visible under **Classification → Test → Preview prompts**.

English and German presets populate all three prompt fields. Loading a preset changes the draft only; save to activate it.

### Tagging strategy

**Hybrid tagging — Recommended for small models**
Compares documents with reviewed examples and reuses a tag only when similarity and neighbor agreement are strong. Otherwise the LLM decides using Tag Guidance and relevant examples. [How Hybrid tagging works](tagging.md#hybrid-tagging).

**LLM direct — For more capable models**
The configured model chooses tags for every document. Reviewed examples are not used for routing or retrieved prompt examples.

### Tag Guidance

The Control Center dynamically shows one optional guidance field per current Paperless content tag. Guidance is stored by Paperless tag ID, so renaming a tag keeps its description.

Guidance is supplied whenever the LLM chooses tags. A confident Hybrid match does not send Tag Guidance to the model.

### History health

The Tagging tab shows reviewed-document count, represented tags, a retrospective estimated reuse percentage, **History depth by tag** and **Potential tag inconsistencies**.

History depth is based only on the number of reviewed examples for a tag:

| Reviewed examples | Depth |
|---:|---|
| 0 | No history |
| 1 | Very limited |
| 2–4 | Limited |
| 5–9 | Good |
| 10+ | Strong |

This is an evidence-depth indicator, not an accuracy score or match probability.

The reuse estimate uses retrospective leave-one-out routing and counts only cases where the strict Hybrid gate reproduces the existing reviewed leaf-tag assignment. It does not predict future accuracy.

Potential tag inconsistencies group at least three strongly similar reviewed documents when their leaf-tag assignments differ. They are review hints only and never change Paperless metadata.

The index checks for relevant Paperless changes at most every five minutes when used and rebuilds only after a change. **Refresh history** forces an immediate Control Center rebuild and asks the metadata worker to refresh before its next Hybrid route.

### Safe interactive testing

For an existing Paperless document, **Preview prompts** shows the exact tag route, structured schema and rendered messages without calling Ollama. **Run model test** performs the real local model request and local sender resolution. Neither modifies the selected Paperless document or persists a suggestion.

## Correspondents

The classification request extracts the actual sender/issuer as a short free-text name. Local resolution can apply a normalized exact match or a deliberately strong unambiguous fuzzy match. Other plausible names are exposed through Paperless Document Suggestions; unreliable output is left empty.

New correspondents are never auto-created.

## Ollama lifecycle

The metadata worker uses the configured model for the structured request and unloads it before releasing the shared AI transaction. `keep_alive` is still available as an Ollama request parameter, while explicit unload is the normal end-of-document behavior.

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
