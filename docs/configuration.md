# Configuration

The **Control Center** is the main interface for normal `paperless-local-ai` configuration, testing and configuration history.

## Recommended first-time setup order

1. **App Settings → Connections** — configure and test Paperless and Ollama.
2. **App Settings → Pipeline & Tags** — choose classification queue/error/review tag names.
3. **App Settings → OCR** — choose OCR language, PaddleOCR model, image limit and inference device.
4. **App Settings → Runtime** — choose whether metadata writes are enabled; worker timing is available under Advanced worker settings.
5. **Classification → Test** — run a safe model test, then adjust prompts/settings only if needed.
6. **Correspondent fallback → Test** — optionally test and enable correspondent identification.
7. Complete the matching [Paperless setup](paperless-setup.md).

Saved runtime and prompt configurations are versioned and can be restored from the UI.

## Connections

Configure:

- Paperless URL;
- Ollama URL;
- Paperless token presence check.

The token remains a deployment secret and is never shown by the UI.

The URLs must be reachable **from the app containers**. `localhost` inside a container is not the Docker/TrueNAS host.

## Pipeline & tags

Configure:

- classification queue tag;
- classification error tag;
- review tag;
- additional tags excluded from classification.

OCR does not use queue or error tags. It runs as part of Paperless/OCRmyPDF document import.

Paperless tag names must match these values exactly.

## OCR

Configure:

- OCR language;
- PaddleOCR model;
- maximum OCR image dimension in pixels;
- automatic OCR retries;
- inference device.

The current validated model family is **PP-OCRv6**. The Control Center offers three matching detection/recognition model sizes:

| PaddleOCR model | Intended use |
|---|---|
| **PP-OCRv6 Medium** | highest recognition quality; default |
| **PP-OCRv6 Small** | lower inference cost with a quality/performance trade-off |
| **PP-OCRv6 Tiny** | lowest inference cost; lower recognition accuracy |

Each option selects the matching PP-OCRv6 detection and recognition models. **PP-OCRv6 Tiny does not support Japanese.**

The temporary OCR image is limited by `ocr.max_side_pixels`. The default is **3000 px** on the longest side; supported values are **2000–4000 px**. The OCRmyPDF bridge keeps the page aspect ratio and adjusts DPI proportionally, so this does not resize the original PDF or the visible archived page. The same limit is also passed to PaddleOCR text detection as a second safety boundary.

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

The 16k metadata value was measured during a real classification run (`1948` prompt tokens, `73` output tokens). The 4k and 8k values use the same model with a short fixed request. Actual memory use varies with model, document and runtime.

PaddleOCR and Ollama inference are serialized through the shared AI resource lock, so the heavy OCR and LLM peaks normally do not overlap.

If RAM is limited:

1. Lower **Maximum OCR image dimension** first when OCR is the problem. It only reduces the temporary image used for OCR; the original PDF is untouched.
2. Use **PP-OCRv6 Small** or **Tiny** if lower OCR inference cost matters more than maximum recognition quality. Their exact RAM savings have not been benchmarked yet.
3. Reduce the Classification/Correspondent **Context window** if the LLM phase is the problem. With qwen3.5:4b, 4k / 8k / 16k measured roughly 3.6 / 3.8 / 4.2 GiB.
4. Use a smaller Ollama model if more LLM memory needs to be saved.
5. Treat `OCR_MEMORY_LIMIT` as a deployment safety ceiling. Raising it does not reduce OCR memory use and can worsen host-wide OOM pressure when no headroom exists.

With about **5 GiB available for AI processing**, the tested 3000 px OCR setting and qwen3.5:4b at 16k context are close to the upper end of that budget individually. An 8k context gives the LLM more headroom; lower the OCR image dimension if OCR still approaches the available memory.

Existing saved configurations without `ocr.max_side_pixels` automatically use `3000`, and configurations without `ocr.model_profile` use `medium`.

### Automatic OCR retries

The default retry delays are **`[15, 60, 300, 600]`**. In the Control Center they are entered as `15, 60, 300, 600`: retry the same page after 15 seconds, then 1 minute, 5 minutes and 10 minutes if temporary errors continue. Each value adds one retry; an empty field disables automatic retries.

Only problems that may recover are retried, such as an unexpectedly terminated Paddle process, IPC loss, memory-allocation failure or temporarily unavailable OCR service. Invalid authentication, OCR-language mismatch, invalid configuration and malformed input fail immediately. A full page timeout is also treated as a failure rather than starting another potentially very long attempt.

During a retry wait, the failed Paddle process is already stopped and the shared AI resource lock is released. **Retry now** skips the remaining delay before the next already-scheduled attempt; it does not increase the retry limit.

The Control Center shows the current state as **Ready**, **OCR running**, **Waiting to retry** or **Needs attention**. Raw exception text is available under **Technical details** instead of being placed in the main status message.

Up to 10 retry delays are accepted, each from 1 to 86400 seconds. Paperless defaults `PAPERLESS_WORKER_TIMEOUT` to 1800 seconds; if you configure substantially longer total waits, raise that timeout accordingly.

With one Paperless task worker, later imports remain queued while the current import waits for its retry. This avoids immediately starting another heavy OCR job after a likely resource-pressure failure; the Paddle process itself is not kept in RAM during the wait.

The configured OCR language is checked against the language requested by Paperless through the OCRmyPDF plugin. The values must match; a mismatch is rejected rather than silently running a different language model.

HPI/OpenVINO enablement, CPU threads, container memory, shared memory and the warm-session timeout remain deployment settings because they affect container/runtime construction. The OCR image limit itself is runtime-owned and can be changed in the Control Center without recreating the containers.

## Runtime

Configure:

- metadata Dry run;
- advanced worker polling and review-cleanup intervals.

These values are stored in `APP_DATA_DIR/config/app-config.json` and hot-reloaded by the app.

### Dry run

Dry run is a safety mode for the **metadata worker**, not for Paperless import/OCR.

With Dry run enabled, automatic metadata processing:

- does **not** write title, document type, date, content tags or correspondent;
- does **not** persist a new-correspondent review record;
- still stores the processing result below `APP_DATA_DIR/core/results/`;
- still manages technical LLM/review workflow tags.

OCR remains part of Paperless' own import path and is unaffected by metadata Dry run.

## Classification

Classification controls the main metadata request and automatic metadata updates in Paperless: prompts, model settings, output limits, testing and version history.

One request covers:

- title;
- document type;
- date;
- content tags;
- an existing correspondent.

The full document context is processed once for normal classification rather than separately for every metadata field. On a normal successful production run, the resulting title, document type, date, eligible content tags and resolved existing correspondent are written back to the Paperless document automatically.

The structured response is constrained to the current eligible Paperless document types, correspondents and tags.

### Safe interactive testing

For an existing Paperless document you can:

- **Preview** the exact rendered request without calling Ollama;
- run a real **Test** request against Ollama.

These interactive actions do not modify the selected Paperless document.

Interactive model tests use the same shared AI resource lock as OCR and automatic metadata jobs, so heavy OCR and LLM inference do not run at the same time.

## Correspondent fallback

The optional Correspondent fallback runs only when Classification returns no correspondent and automatic fallback is enabled.

It receives the document text plus the current Paperless correspondent list and has its own prompt/model settings.

Possible outcomes:

- exact match to existing correspondent → apply automatically;
- genuinely new correspondent → expose through **Paperless Document Suggestions**;
- no reliable correspondent → leave correspondent unresolved.

New correspondents are never auto-created.

## Ollama lifecycle

The metadata worker keeps configured models alive across the primary request and optional correspondent fallback for the current document, then explicitly unloads them before leaving the shared AI transaction.

The finite keep-alive value is a crash fail-safe, not the normal unload mechanism.

## Language

The Control Center interface is English. Fresh installations start with OCR language `en` plus English Classification and Correspondent fallback prompts.

Classification and Correspondent fallback each include English and German prompt presets.

OCR language is independent from prompt language. Choose the language of the scanned documents under **App Settings → OCR**.

Saved configurations are validated against the current schema; unsupported keys are not carried into the active configuration.

## Deployment-only settings

These remain outside the Control Center because Docker/Paperless needs them before the app starts or because they are secrets:

- `PAPERLESS_TOKEN`;
- `OCR_SERVICE_TOKEN`;
- image/version;
- `APP_DATA_DIR`;
- host bind addresses and ports;
- OCR HPI/OpenVINO enablement;
- OCR CPU/thread/RAM/shared-memory/idle limits;
- Paperless-side `PLAI_OCR_*` values and OCRmyPDF plugin configuration.

Changing deployment-owned values requires recreating/redeploying the affected containers.
