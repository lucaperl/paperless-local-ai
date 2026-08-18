# AGENTS.md

This file describes project invariants for coding agents and contributors.

## Project scope

`paperless-local-ai` is a small companion stack for Paperless-ngx. It improves OCR with PaddleOCR and applies text-only metadata classification through an external Ollama server.

Do not turn it into a bundled Paperless distribution, an Ollama distribution, or a RAG/document-chat suite without an explicit project decision.

## Architecture invariants

- One Compose application, four services: `ocr-worker`, `metadata-worker`, `prompt-ui`, `suggestion-bridge`.
- Two images only: OCR image and core image.
- Ollama stays external.
- Paperless stays stock; integrate through supported HTTP/API behavior.
- Expensive OCR and LLM inference share `/coordination/ai.lock` and are serialized by default.
- Genuinely new correspondents are never auto-created.
- Native suggestion matching must fail closed when identity is missing or ambiguous.

## Configuration ownership

Do not scatter settings.

- Deployment/secrets: `.env` / Compose only when Docker needs the value before process start, or when it is a secret.
- Shared runtime: `/config/app-config.json`, owned by Studio -> App-Einstellungen.
- Classification stage: `/config/prompt-config.json`.
- Correspondent stage: `/config/correspondent-suggestion.json`.
- Internal implementation constants stay code unless there is a supported operator use case.

The Paperless API token must never be written to app-config/history or returned by the Studio API.

## Compatibility

The native suggestion bridge is currently verified against Paperless-ngx 3.0.5. Do not broaden the compatibility claim without an integration test against the target Paperless release.

Current published OCR support is linux/amd64. Do not claim ARM64 until the Paddle image/runtime is validated.

## Safety and privacy

- Never commit real tokens, `.env`, private document text, OCR dumps, private IP addresses or user-specific paths.
- Do not add telemetry or cloud dependencies by default.
- Prompt Studio has no authentication; documentation must continue to warn against public exposure.
- Preserve original Paperless documents; OCR updates Paperless extracted content, not the source file.

## Required checks

Before merging code changes:

```bash
python -m compileall -q src tests scripts
pytest -q
docker compose -f compose.yaml -f compose.dev.yaml config
```

For changes to OCR classification, native suggestion identity, Paperless AI integration or Compose structure, add/perform an integration test and update compatibility/release notes.

## Release discipline

- `VERSION` contains the release version without a leading `v`.
- GitHub Release tag must be `v<VERSION>`.
- Release workflow publishes exact GHCR tags; non-prerelease releases also update `stable` and `latest`.
- Do not silently change mounts, ports, required env vars or service graph in a code-only patch release; TrueNAS Custom App image updates do not rewrite existing Compose YAML.
