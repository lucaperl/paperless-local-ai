# Configuration

The **Control Center** is the main interface for normal `paperless-local-ai` configuration, testing and configuration history.

## Recommended first-time setup order

1. **App Settings → Connections** — configure and test Paperless and Ollama.
2. **App Settings → Pipeline & Tags** — choose LLM queue/error/review tag names.
3. **App Settings → OCR** — choose OCR language/version/model profile/device.
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
- device.

The current validated OCR generation is **PP-OCRv6**. The Control Center exposes three matching detection/recognition profiles:

| Profile | Intended use |
|---|---|
| **Medium** | highest quality; default and recommended |
| **Small** | balance of quality and inference cost |
| **Tiny** | lowest inference cost; lower recognition accuracy |

Each profile selects the matching PP-OCRv6 detection and recognition models. **Tiny does not support Japanese.**

Existing saved configurations without `ocr.model_profile` automatically use `medium`, so the setting does not require a deployment migration.

The configured language is also checked against the language requested by Paperless through the OCRmyPDF plugin. A mismatch is rejected rather than silently running a different model language.

HPI/OpenVINO enablement, CPU threads, memory, shared memory and the warm-session timeout are deployment-owned settings because they affect container/runtime construction.

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
