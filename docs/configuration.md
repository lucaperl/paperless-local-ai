# Configuration

The **Control Center** is the main interface for normal `paperless-local-ai` configuration, testing and configuration history.

## Recommended first-time setup order

Work through the UI in this order:

1. **App Settings → Connections** — configure and test Paperless and Ollama.
2. **App Settings → Pipeline & Tags** — choose queue/error/review tag names.
3. **App Settings → OCR** — review language, PaddleOCR generation and device.
4. **App Settings → Runtime** — review polling, cleanup and Dry Run.
5. **Classification** — review the primary prompt/model settings and run a test.
6. **Correspondent fallback** — optionally configure and test the separate sender-identification stage.
7. Complete the matching [Paperless setup](paperless-setup.md) if you have not already done so.

Saved runtime and prompt configurations are versioned and can be restored from the UI.

## Connections

Configure:

- Paperless URL;
- Ollama URL;
- Paperless token presence check.

The token itself remains a deployment secret and is never shown by the UI.

The URLs must be reachable **from the app containers**. `localhost` inside a container is not the Docker/TrueNAS host. See the networking examples in the [Docker](installation.md) or [TrueNAS](truenas.md) installation guide.

## Pipeline & tags

Configure:

- OCR queue/error tags;
- LLM queue/error tags;
- human-review tag;
- extra tags excluded from normal LLM content-tag candidates.

Paperless tag names must match these values exactly.

## OCR

Configure:

- language;
- PaddleOCR generation;
- device.

Native digital PDF text is kept. Scan/raster pages are selectively reprocessed when the OCR worker classifies them as needing PaddleOCR.

## Runtime

Configure:

- poll interval;
- review cleanup interval;
- Dry Run.

These values are stored in `APP_DATA_DIR/config/app-config.json` and hot-reloaded by the workers.

### Dry Run

Dry Run is a safety mode for the **metadata worker**, not a read-only mode for the entire pipeline.

With Dry Run enabled, automatic metadata processing:

- does **not** write title, document type, date, content tags or correspondent;
- does **not** persist a new-correspondent review record;
- still stores the processing result below `APP_DATA_DIR/core/results/`;
- still manages technical queue/error tags.

The OCR worker is separate. If a queued scanned document is reprocessed with PaddleOCR, Paperless' extracted `content` may still be updated even while Dry Run is enabled.

## Classification

Classification controls the main structured metadata request: prompt, model/request parameters, output limits, testing and version history.

One request covers:

- title;
- document type;
- date;
- content tags;
- an existing correspondent.

The structured response is constrained to the current eligible Paperless taxonomy for document type, tags and existing correspondent.

### Safe interactive testing

For an existing Paperless document you can:

- **Preview** the exact rendered request without calling Ollama;
- run a real **Test** request against Ollama.

These interactive actions do not modify the selected Paperless document.

## Correspondent fallback

This is an optional second LLM stage used only when the primary classification returns no correspondent and the fallback is enabled.

It receives the document text plus the current Paperless correspondent list and has its own prompt, model settings, tests, history and production enable switch.

Possible outcomes:

- exact match to an existing correspondent → apply automatically;
- genuinely new sender → keep as a human-review candidate;
- no reliable sender → leave correspondent unresolved.

New correspondents are never auto-created.

The fallback can be previewed and tested while its production switch is off.

## Language

The Control Center interface is English.

The current default classification prompts are German, and the tested reference OCR language is German. Both prompts and OCR language are configurable; non-German end-to-end behavior is not currently claimed as tested.

## Deployment-only settings

These remain outside the Control Center because Docker needs them before the app starts or because they are secrets:

- `PAPERLESS_TOKEN`;
- image/version;
- `APP_DATA_DIR`;
- host bind addresses and ports;
- container CPU/RAM/shared-memory limits.

Changing deployment-owned values requires recreating or redeploying the affected containers.
