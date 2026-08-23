# Configuration

The **Control Center** is the main interface for normal `paperless-local-ai` configuration, testing and configuration history.

## Recommended first-time setup order

1. **App Settings → Connections** — configure and test Paperless and Ollama.
2. **App Settings → Pipeline & Tags** — choose classification queue/error/review tag names.
3. **App Settings → OCR** — choose OCR language, PaddleOCR model, image limit and retry behavior.
4. **App Settings → Runtime** — choose whether metadata writes are enabled.
5. **Classification → Tagging** — choose History-assisted or LLM-only tagging and optionally describe ambiguous tags.
6. **Classification → Test** — run a safe preview/model test against an existing document.
7. Adjust **Classification → Prompt / Settings** only when needed.
8. Complete the matching [Paperless setup](paperless-setup.md).

Saved app/classification configurations are versioned and can be restored from the UI.

## Connections

Configure the Paperless and Ollama base URLs. The Paperless API token remains a deployment secret and is never shown by the UI or stored in JSON history.

The URLs must be reachable **from the app containers**. `localhost` inside a container is not the Docker/TrueNAS host.

## Pipeline & tags

Configure:

- classification queue tag;
- classification error tag;
- review tag;
- additional tags excluded from content classification.

OCR does not use queue/error tags. It runs inside Paperless/OCRmyPDF import.

The **review tag is also the trust boundary for History-assisted tagging**: a document becomes eligible only after it has left this tag. Documents still carrying the classification queue or classification error tag are also excluded. This keeps fresh, unfinished or failed LLM output from immediately becoming future history.

## OCR

Configure OCR language, PaddleOCR model, maximum temporary OCR image dimension, retry schedule and inference device.

The validated model family is **PP-OCRv6**:

| PaddleOCR model | Intended use |
|---|---|
| **PP-OCRv6 Medium** | highest recognition quality; default |
| **PP-OCRv6 Small** | lower inference cost with a quality/performance trade-off |
| **PP-OCRv6 Tiny** | lowest inference cost; lower recognition accuracy |

PP-OCRv6 Tiny does not support Japanese.

The temporary OCR image is limited by `ocr.max_side_pixels`. Default: **3000 px** on the longest side; supported range: **2000–4000 px**. This changes only the temporary OCR input and never resizes the original/archive page.

### RAM usage and tuning

Measured on the reference setup:

| Workload | Configuration | Measured peak |
|---|---|---:|
| OCR | PP-OCRv6 Medium · 3000 px | ~4.4–4.7 GiB |
| OCR | PP-OCRv6 Medium · 3200 px | ~4.9–5.1 GiB |
| OCR | PP-OCRv6 Medium · 4000 px | ~6.5 GiB |
| Metadata | qwen3.5:4b Q4_K_M · 4k context | ~3.6 GiB |
| Metadata | qwen3.5:4b Q4_K_M · 8k context | ~3.8 GiB |
| Metadata | qwen3.5:4b Q4_K_M · 16k context | ~4.2 GiB |

PaddleOCR and Ollama inference are serialized through the shared AI resource lock, so the heavy peaks normally do not overlap.

If RAM is limited, lower **Maximum OCR image dimension** first when OCR is the problem and reduce the Classification **Context window** when the LLM is the problem. `OCR_MEMORY_LIMIT` remains a deployment safety ceiling; raising it does not reduce memory use.

### Automatic OCR retries

Default retry delays: **`15, 60, 300, 600`** seconds. Each value adds one retry. Leave the field empty to disable automatic retries.

Only potentially recoverable failures are retried. Invalid authentication, OCR-language mismatch, malformed input and invalid configuration fail immediately. During a retry wait the failed Paddle process is stopped and the shared AI lock is released. **Retry now** skips the remaining delay before the next already-scheduled attempt; it does not add attempts.

The Control Center shows **Ready**, **OCR running**, **Waiting to retry** or **Needs attention** and keeps raw exception details behind Technical details.

Paperless defaults `PAPERLESS_WORKER_TIMEOUT` to 1800 seconds; if the configured total retry window substantially exceeds that, raise the Paperless timeout accordingly.

HPI/OpenVINO, CPU/thread/RAM/shared-memory and OCR idle limits remain deployment settings because they affect container/runtime construction.

## Runtime

Configure metadata Dry run plus advanced worker polling/review-cleanup intervals.

### Dry run

Dry run affects the metadata worker, not Paperless import/OCR. With Dry run enabled the worker still performs routing/classification and stores result JSON, but it does not write title, type, date, content tags, correspondent or a persistent new-correspondent review record. Technical workflow/error tags may still change.

## Classification

Classification controls the one structured local-LLM request. Depending on the tag route, the response contains:

- title;
- document type;
- date;
- actual sender/issuer as free text;
- content tags when the LLM is responsible for tag selection.

Document type and LLM-selected tags are constrained to current Paperless values. Correspondent is intentionally free text and is resolved locally after the call.

### Tagging strategy

**History-assisted (Recommended for small models)** is the default. Strong matches against reviewed Paperless documents reuse an established tag. When the strict gate cannot make a decision, the LLM receives relevant reviewed examples and decides tags.

**LLM only (For more capable models)** lets the configured LLM choose tags for every document and does not use reviewed history for routing/examples.

The strategy is independent from the normal prompt text and is saved as part of the classification configuration. See [Tagging](tagging.md) for thresholds, evaluation and limitations.

### Tag guidance

The Control Center dynamically shows one optional guidance field per current Paperless content tag. Guidance is stored by Paperless tag ID, so renaming a tag keeps its description.

Guidance is used only when the LLM makes the tag decision:

- every document in **LLM only**;
- only fallback documents in **History-assisted**.

A high-confidence history match never uses tag guidance.

### History health

The Tagging tab shows reviewed document count, represented tags, per-tag history depth, a retrospective estimated reuse percentage and **Potential tag inconsistencies**. The reuse estimate counts only leave-one-out cases where the strict history route fires and reproduces the document's existing reviewed leaf-tag assignment.

The index checks for relevant Paperless changes at most every five minutes when used and rebuilds only after a change. **Refresh history** forces an immediate Control Center rebuild and asks the metadata worker to refresh before its next history route.

Potential inconsistencies are review hints only. They group similar reviewed documents with different tag assignments and never change Paperless metadata automatically.

### Safe interactive testing

For an existing Paperless document, **Preview prompts** shows the exact tag route, structured schema and rendered messages without calling Ollama. **Run model test** additionally performs the real local model request and local sender resolution. Neither modifies the selected Paperless document or persists a suggestion.

## Correspondents

There is no separate correspondent model stage.

The primary classification request extracts the actual sender/issuer as a short free-text name. Local resolution then has three outcomes:

- normalized exact or deliberately strong unambiguous match → apply existing correspondent automatically;
- plausible new sender → expose through **Paperless Document Suggestions**;
- empty/unreliable extraction → leave correspondent empty.

New correspondents are never auto-created.

## Ollama lifecycle

The metadata worker uses the configured model for the one structured request and explicitly unloads it before releasing the shared AI transaction. `keep_alive` remains available as a model/runtime parameter, while explicit unload is the normal end-of-document behavior.

## Language

The Control Center interface is English. Fresh installations start with OCR language `en` and an English classification prompt. English and German classification prompt presets are available.

OCR language is independent from prompt/UI language.

## Deployment-only settings

These remain outside the Control Center because Docker/Paperless needs them before startup or because they are secrets:

- `PAPERLESS_TOKEN`;
- `OCR_SERVICE_TOKEN`;
- image/version;
- `APP_DATA_DIR`;
- host bind addresses and ports;
- OCR HPI/OpenVINO enablement;
- OCR CPU/thread/RAM/shared-memory/idle limits;
- Paperless-side `PLAI_OCR_*` values and OCRmyPDF plugin configuration.

Changing deployment-owned values requires recreating/redeploying the affected containers.
