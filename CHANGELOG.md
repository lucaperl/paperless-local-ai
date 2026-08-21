# Changelog

## Unreleased

## 0.2.0 - 2026-08-21

### OCR architecture

- replace the separate tag-driven `ocr-worker` with an authenticated `ocr-service` used directly by Paperless' OCRmyPDF pipeline;
- add an OCRmyPDF 17 `OcrEngine.generate_ocr()` plugin that streams rasterized pages to the local service and returns native `OcrElement` geometry without an hOCR/XML roundtrip;
- preserve the Paperless original while OCRmyPDF creates the searchable archive/PDF-A representation and Paperless stores the resulting OCR text;
- remove the old PaddleOCR queue/error tags from the app configuration and keep metadata queuing as a normal Paperless **Document Added → LLM tag** workflow.

### PaddleOCR runtime

- use PaddleOCR 3.7.0 / PaddleX 3.7.2 with explicit **PP-OCRv6 Medium** detection and recognition models;
- enable PaddleX HPI/OpenVINO for the CPU reference deployment;
- use a persistent PaddleX/OpenVINO cache, 4 CPU threads, a 7 GiB OCR limit and a 5-second warm-session timeout by default;
- keep OCR and Ollama serialized through the shared `ai.lock`;
- make `/health.session_active` follow ownership of the global AI slot so the service cannot report idle before the lock is actually released.

### Metadata runtime

- keep the primary structured metadata request plus optional correspondent fallback as two distinct LLM stages;
- retain the configured Ollama model only across the current metadata transaction, then explicitly unload it;
- preserve a finite keep-alive as a crash fail-safe while ensuring normal processing ends with Ollama unloaded.

### Deployment and configuration

- keep four long-running services: `ocr-service`, `metadata-worker`, `prompt-ui` and `suggestion-bridge`;
- add the persistent `/integration` bridge path used to publish the OCRmyPDF plugin to Paperless;
- add deployment settings for the authenticated OCR endpoint, HPI/OpenVINO runtime, shared memory and OCR resource limits;
- document the required Paperless plugin mount and `PLAI_OCR_*` / `PAPERLESS_OCR_USER_ARGS` integration;
- update the Control Center and AppConfig contracts so OCR queue/error settings from 0.1.x are ignored instead of carried forward.

### Cleanup and validation

- remove the legacy direct PyMuPDF dependency from the OCR image while retaining the `requests` pin required by the PaddleOCR/PaddleX stack;
- add regression coverage for the OCR service, removed queue settings, public deployment contracts and session/lock state;
- validate the final local candidate end-to-end on Paperless-ngx 3.0.5: two-page API upload, searchable PDF/A-2b, byte-identical original, PP-OCRv6/OpenVINO OCR, metadata write-back, Inbox handoff, explicit Ollama unload and zero observed Paddle/Ollama overlap.

> [!IMPORTANT]
> 0.2.0 changes the deployment contract. Existing 0.1.x installations must update the app Compose/YAML **and** Paperless' OCRmyPDF integration before switching to the 0.2.0 images. See [Updating](docs/upgrading.md).

## 0.1.3 - 2026-08-19

- switch fresh-install OCR, technical error-tag and prompt defaults to English while preserving existing saved configurations;
- add English/German prompt presets for Classification and Correspondent fallback, improve PP-OCRv6 language selection in the Control Center and make runtime logs/errors English-facing;
- streamline first-time installation and configuration documentation, clarify container networking, workflow scope, Dry Run behavior and metadata write semantics, and remove duplicated Control Center guidance.

## 0.1.2 - 2026-08-19

- rename the TrueNAS portal button to **Control Center** in the published Custom App template and document the one-time YAML metadata change for existing installations that still show **Prompt UI**;
- redesign the Control Center around an Overview and persistent sidebar while keeping the existing configuration, testing and history workflows;
- add a visual end-to-end pipeline overview from Paperless import through OCR/classification, optional correspondent fallback and write-back to Paperless;
- keep the existing in-UI guidance while moving section and field details into collapsible help and info controls where appropriate;
- update the README workflow diagram and correspondent description to match the current Paperless → OCR → classification → optional fallback → write-back flow.

## 0.1.1 - 2026-08-19

- rename the web UI from Prompt Studio to **Control Center** to reflect its app-wide role;
- switch the Control Center interface and UI-facing validation messages to English;
- make safe pre-production testing explicit: connection tests, prompt previews, live LLM tests and Dry Run.

## 0.1.0 - 2026-08-18

Initial public release.

- ship one four-service Compose application using two images (`core` and `ocr`);
- production-test the unified deployment end-to-end with Paperless-ngx 3.0.5 on x86-64 Linux / TrueNAS SCALE 25.10.4;
- preserve selective per-page OCR, shared OCR/LLM serialization and text-only metadata classification;
- use review-record schema v4 for exact/fail-closed native Paperless correspondent suggestions;
- centralize shared runtime settings in versioned `app-config.json` while keeping secrets and Docker-owned settings in deployment configuration;
- set the default worker polling interval to 10 seconds and support runtime hot-reload;
- pin the validated PaddleOCR/PaddleX/OpenCV/Numpy runtime stack so rebuilding `0.1.0` does not silently change OCR behavior;
- publish release images to GHCR with exact version plus `stable`/`latest` tags for non-prerelease releases;
- add GitHub Actions tests, Compose validation, GHCR publication and build-provenance attestations;
- document generic Docker Compose and TrueNAS Custom App deployment from the same codebase;
- add an explicit third-party licensing notice for the OCR runtime instead of presenting the whole container image as MIT-only;
- document the `0.1.0` language scope explicitly: German Studio/default prompts, configurable OCR language, no untested multilingual claim.

## 0.1.0-alpha.4 - 2026-08-18

- introduce review-record schema v4 based on normalized Paperless AI prompt content;
- remove unsafe filename-based request identity assumptions;
- keep exact, fail-closed compatibility behavior for ambiguous requests;
- add regression coverage for prompt-content collisions.

## 0.1.0-alpha.3 - 2026-08-18

- clean up stale review records;
- test real filename collisions;
- keep review matching fail closed when identity is ambiguous.

## 0.1.0-alpha.2 - 2026-08-18

- unify PaddleOCR and metadata processing into one deployable project;
- add the Control Center configuration path and shared runtime configuration;
- add review persistence and the native Paperless correspondent suggestion bridge.

## 0.1.0-alpha.1 - 2026-08-18

- initial staged unified-app prototype.
