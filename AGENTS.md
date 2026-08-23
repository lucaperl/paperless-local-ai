# AGENTS.md

This file describes project invariants for coding agents and contributors.

## Project scope

`paperless-local-ai` is a small companion stack for Paperless-ngx. It improves scan OCR through Paperless/OCRmyPDF plus a local PaddleOCR service and applies text-only metadata classification through an external Ollama server.

Do not turn it into a bundled Paperless distribution, an Ollama distribution, or a RAG/document-chat suite without an explicit project decision.

## Architecture invariants

- One Compose application, four long-running services: `ocr-service`, `metadata-worker`, `prompt-ui`, `suggestion-bridge`.
- Two images only: OCR image and core image.
- Ollama stays external.
- Paperless stays the document system of record.
- OCR integrates through the Paperless/OCRmyPDF plugin path; do not reintroduce a second tag-driven OCR queue without an explicit architecture decision.
- The uploaded Paperless original must remain untouched by this project.
- Expensive OCR and LLM inference share `/coordination/ai.lock` and are serialized by default.
- `/health.session_active=false` must mean the OCR service no longer owns the global AI slot.
- Normal metadata processing explicitly unloads the configured Ollama model before leaving the AI transaction.
- Normal metadata processing uses one structured LLM request per document. Do not reintroduce a second correspondent-only inference stage without an explicit architecture decision.
- Correspondent output is free-text extraction; local resolver logic decides whether an existing correspondent is safe to apply. Genuinely new correspondents are never auto-created.
- The default tag strategy is `history_assisted`; `llm_only` remains a supported user choice.
- History-assisted automatic reuse must remain confidence-gated and read-only with respect to historical Paperless metadata.
- Documents carrying the configured review tag are not trusted as history/examples. The current document must be excluded from its own lookup.
- Tag guidance affects LLM tag decisions only and must not change deterministic high-confidence history matches.
- Potential tag inconsistency diagnostics are advisory only and must never rewrite historical tags.
- Native suggestion matching must fail closed when identity is missing or ambiguous.

## Configuration ownership

Do not scatter settings.

- Deployment/secrets: `.env` / Compose only when Docker needs the value before process start, or when it is a secret.
- Paperless-side OCR plugin values remain in the Paperless deployment because Paperless must know them at start.
- Shared runtime: `/config/app-config.json`, owned by Control Center → App Settings.
- Classification stage: `/config/prompt-config.json`, including model/prompt settings, tagging strategy and per-tag guidance.
- History similarity thresholds remain implementation constants unless a supported operator use case is explicitly added.
- Internal implementation constants stay code unless there is a supported operator use case.

The pre-0.3 `/config/correspondent-suggestion.json` file is not part of the active runtime configuration. Do not recreate a separate correspondent settings surface without an architecture decision.

The Paperless API token and OCR service token must never be written to app-config/history or returned by the Control Center API.

The public Control Center UI is English. Fresh-install OCR and prompt defaults are English, with English/German classification prompt presets available in the UI. Keep UI language, OCR language and prompt language independent.

Keep internal deployment identifiers such as `prompt-ui`, `OCR_SERVICE_TOKEN` and the published service names stable unless a migration is explicitly planned.

## Compatibility

The OCRmyPDF plugin and native suggestion bridge are currently verified against Paperless-ngx 3.0.5; the plugin specifically targets OCRmyPDF 17.4.2's native `generate_ocr()` / `OcrElement` contract.

History-assisted tagging uses documented Paperless REST document/tag fields but depends on the configured review-tag workflow semantics. Do not broaden compatibility claims without integration testing the target Paperless release.

Current published OCR support is linux/amd64. Do not claim ARM64 until the Paddle image/runtime is validated.

## Safety and privacy

- Never commit real tokens, `.env`, private document text, OCR dumps, private IP addresses or user-specific paths.
- Do not add telemetry or cloud dependencies by default.
- The Control Center has no authentication; documentation must continue to warn against public exposure.
- The OCR service is token-authenticated but must still be documented as a private/LAN endpoint.
- Preserve the original Paperless document; searchable OCR belongs in Paperless' archive/content path.
- Historical document excerpts may be sent only to the configured local Ollama endpoint and must remain framed as untrusted document content.

## Required checks

Before merging code changes:

```bash
python -m compileall -q src tests scripts
pytest -q
docker compose -f compose.yaml config
docker compose -f compose.yaml -f compose.dev.yaml config
```

For History-assisted tagging changes, also test confidence-gated routing, parent-tag pruning, review-tag exclusion, few-shot selection and potential-inconsistency diagnostics.

For OCR lifecycle/plugin changes, also verify the session/lock contract and one real Paperless end-to-end document.

For changes to native suggestion identity, Paperless AI integration or Compose structure, add/perform an integration test and update compatibility/release notes.

## Release discipline

- `VERSION` contains the release version without a leading `v`.
- GitHub Release tag must be `v<VERSION>`.
- Release workflow publishes exact GHCR tags; non-prerelease releases also update `stable` and `latest`.
- `SOURCE-MANIFEST.json` must match runtime source.
- Do not silently change mounts, ports, required environment variables or service graph in an image-only patch release; TrueNAS Custom App image updates do not rewrite stored Compose YAML.
