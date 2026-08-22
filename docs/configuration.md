# Configuration

The **Control Center** is the main interface for normal `paperless-local-ai` configuration, testing and configuration history.

## Recommended first-time setup order

1. **App Settings → Connections** — configure and test Paperless and Ollama.
2. **App Settings → Pipeline & Tags** — choose LLM queue/error/review tag names.
3. **App Settings → OCR** — choose OCR language/version/model profile/max image side/device.
4. **App Settings → Runtime** — review polling, cleanup and Dry Run.
5. **Classification** — review the primary prompt/model settings and run a test.
6. **Correspondent fallback** — optionally configure/test correspondent identification.
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

- LLM queue tag;
- LLM error tag;
- human-review tag;
- extra tags excluded from normal LLM content-tag candidates.

OCR does not use queue or error tags. It runs as part of Paperless/OCRmyPDF document import.

Paperless tag names must match these values exactly.

## OCR

Configure:

- language;
- PaddleOCR generation;
- PP-OCRv6 model profile;
- maximum OCR image side in pixels;
- automatic retry delays;
- device.

The current validated OCR generation is **PP-OCRv6**. The Control Center exposes three matching detection/recognition profiles:

| Profile | Intended use |
|---|---|
| **Medium** | highest quality; default and recommended |
| **Small** | balance of quality and inference cost |
| **Tiny** | lowest inference cost; lower recognition accuracy |

Each profile selects the matching PP-OCRv6 detection and recognition models. **Tiny does not support Japanese.**

Existing saved configurations without `ocr.model_profile` automatically use `medium`.

The temporary OCR-only raster is limited by `ocr.max_side_pixels`. The default is **3000 px** on the longest side; supported values are **2000–4000 px**. The OCRmyPDF bridge keeps the page aspect ratio and adjusts DPI proportionally, so this does not resize the original PDF or the visible archived page. The same limit is also passed to PaddleOCR text detection as a second safety boundary.

Reference measurements with PP-OCRv6 Medium on the CPU-only 16 GiB test host were approximately **4.4–4.7 GiB** OCR-service peak at 3000 px, **4.9–5.1 GiB** at 3200 px and **6.5 GiB** at 4000 px. These are observed test values, not universal RAM requirements; page content, model profile and runtime can change memory use. **3000 px is the recommended default for 16 GiB hosts.**

Existing saved configurations without `ocr.max_side_pixels` automatically use `3000`, so the setting does not require a deployment migration.

`ocr.retry_delays_seconds` controls bounded automatic recovery for transient OCR failures. The default is **`[15, 60, 300, 600]`**, meaning one initial attempt followed by retries after 15 seconds, 1 minute, 5 minutes and 10 minutes. In the Control Center this is edited as a comma-separated list (`15, 60, 300, 600`). Each value adds one retry; an empty field disables automatic retries. Up to 10 delays are accepted, each from 1 to 86400 seconds. Paperless defaults `PAPERLESS_WORKER_TIMEOUT` to 1800 seconds, so the shipped schedule deliberately leaves headroom for the OCR attempts themselves. If you configure substantially longer backoffs, increase the Paperless worker timeout as well.

Retries are intentionally limited to failures that can plausibly recover later, such as an unexpectedly terminated Paddle worker, IPC loss, memory-allocation failure or temporary OCR-service/network unavailability. Authentication, language/configuration, malformed-input and other deterministic errors fail immediately. A long Paddle page timeout remains a final error rather than starting another potentially 30-minute attempt.

During retry backoff the failed Paddle subprocess is torn down and the shared `ai.lock` is released. The OCRmyPDF bridge keeps the Paperless consume task alive and starts the next attempt after the configured delay. The Control Center's **OCR recovery** card shows the current state and can skip an active wait with **Retry now**. The retry count remains bounded; `Retry now` does not add another attempt.

Existing saved configurations without `ocr.retry_delays_seconds` automatically receive the default schedule.

The configured language is also checked against the language requested by Paperless through the OCRmyPDF plugin. A mismatch is rejected rather than silently running a different model language.

HPI/OpenVINO enablement, CPU threads, container memory, shared memory and the warm-session timeout are deployment-owned settings because they affect container/runtime construction. The OCR raster limit itself is runtime-owned and can be changed in the Control Center without recreating the containers.

## Runtime

Configure:

- metadata-worker poll interval;
- review cleanup interval;
- Dry Run.

These values are stored in `APP_DATA_DIR/config/app-config.json` and hot-reloaded by the app.

### Dry Run

Dry Run is a safety mode for the **metadata worker**, not for Paperless import/OCR.

With Dry Run enabled, automatic metadata processing:

- does **not** write title, document type, date, content tags or correspondent;
- does **not** persist a new-correspondent review record;
- still stores the processing result below `APP_DATA_DIR/core/results/`;
- still manages technical LLM/review workflow tags.

OCR remains part of Paperless' own import path and is unaffected by metadata Dry Run.

## Classification

Classification controls the main structured metadata request and automatic Paperless write-back: prompt, model/request parameters, output limits, testing and version history.

One request covers:

- title;
- document type;
- date;
- content tags;
- an existing correspondent.

The full document context is processed once for normal classification rather than separately for every metadata field. On a normal successful production run, the resulting title, document type, date, eligible content tags and resolved existing correspondent are written back to the Paperless document automatically.

The structured response is constrained to the current eligible Paperless taxonomy.

### Safe interactive testing

For an existing Paperless document you can:

- **Preview** the exact rendered request without calling Ollama;
- run a real **Test** request against Ollama.

These interactive actions do not modify the selected Paperless document.

Interactive LLM tests use the same global `ai.lock` as OCR and production metadata jobs.

## Correspondent fallback

This optional second LLM stage runs only when the primary classification returns no correspondent and the fallback is enabled.

It receives the document text plus the current Paperless correspondent list and has its own prompt/model settings.

Possible outcomes:

- exact match to existing correspondent → apply automatically;
- genuinely new correspondent → expose through **Paperless Suggestions**;
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
