# Changelog

## Unreleased

- rename the TrueNAS portal button to **Control Center** in the published Custom App template and document the one-time YAML metadata change for existing installations that still show **Prompt UI**.
- redesign the Control Center around an Overview and persistent sidebar while keeping the existing configuration, testing and history workflows;
- add a visual end-to-end pipeline overview from Paperless import through OCR/classification, optional correspondent fallback and write-back to Paperless;
- keep the existing in-UI guidance while moving section and field details into collapsible help and info controls where appropriate.

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

- fix atomic review-record persistence in the packaged core image;
- harden native suggestion request matching and collision behavior.

## 0.1.0-alpha.2 - 2026-08-18

- centralize shared runtime settings and add versioned App-Einstellungen;
- move to one persistent `APP_DATA_DIR`;
- make shared runtime settings hot-reloadable.

## 0.1.0-alpha.1 - 2026-08-18

- package OCR and core runtimes into images;
- provide one Compose application with four services;
- keep Ollama external;
- add doctor checks, documentation and initial CI.
