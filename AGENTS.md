# AGENTS.md

This file describes project invariants for coding agents and contributors.

## Project scope

`paperless-local-ai` is a small companion stack for Paperless-ngx. It improves scan OCR through Paperless/OCRmyPDF plus a local PaddleOCR service and applies text-only metadata classification through an external Ollama server.

Do not turn it into a bundled Paperless distribution, an Ollama distribution, or a RAG/document-chat suite without an explicit project decision.

## Architecture invariants

- One Compose application, two long-running services: `ocr-service` and `core-service`. The core service hosts metadata polling, the Control Center, the optional suggestion bridge and the lightweight History broker in one persistent Rust process.
- Two images only: OCR image and core image.
- Ollama stays external.
- Paperless stays the document system of record.
- OCR integrates through the Paperless/OCRmyPDF plugin path.
- The uploaded Paperless original must remain untouched by this project.
- Expensive OCR and LLM inference share `/coordination/ai.lock` and are serialized by default.
- `/health.session_active=false` must mean the OCR service no longer owns the global AI slot.
- OCR worker teardown and OCR container recycle are separate lifecycle boundaries: release the heavyweight Paddle worker and `ai.lock` after the short warm-session idle timeout, while keeping the lightweight OCR service available through an extended quiet period before cold-idle cgroup recycle.
- Normal metadata processing unloads the configured Ollama model before leaving the AI transaction.
- Normal metadata processing uses one structured LLM request per document.
- Correspondent output is free-text extraction; local resolver logic decides whether an existing correspondent is safe to apply. Genuinely new correspondents are never auto-created.
- The user-facing tag strategies are **Hybrid tagging** and **LLM direct**. Internal config values stay `history_assisted` and `llm_only` for stability.
- Hybrid automatic reuse is confidence-gated and read-only with respect to historical Paperless metadata. A confident route may reuse one complete reviewed leaf-tag set (including multiple tags); History never synthesizes an unseen tag combination.
- Documents carrying the configured review tag are not trusted as retrieval/examples. The current document is excluded from its own lookup.
- Tag Guidance affects LLM tag decisions only and must not change deterministic confident Hybrid matches.
- Potential tag inconsistency diagnostics are advisory only and must never rewrite historical tags.
- Native suggestion matching must fail closed when identity is missing or ambiguous.

## Prompt ownership

Classification prompt behavior is user-configurable in `/config/prompt-config.json` and the Control Center:

- `system_prompt` — always sent;
- `classification_template` — always sent and owns the base metadata task;
- `tagging_prompt` — appended only when the LLM is responsible for tag selection.

Do not hide normal tag-classification policy in hardcoded runtime prose. The runtime may enforce structural invariants, schema constraints and route composition, but user-facing model instructions belong in editable prompt fields/presets.

A confident Hybrid route must omit the Tagging prompt, Tag Guidance, retrieved examples, tag list and the `tags` property from the LLM schema. The application inserts the deterministic complete reviewed leaf-tag set after base-result validation.

## Configuration ownership

Do not scatter settings.

- Deployment/secrets: `.env` / Compose only when Docker needs the value before process start, or when it is a secret.
- Paperless-side OCR plugin values stay in the Paperless deployment because Paperless must know them at start.
- Shared runtime: `/config/app-config.json`, owned by Control Center → App Settings.
- Classification: `/config/prompt-config.json`, including prompt components, model settings, tagging strategy and per-tag guidance.
- The supported History gate controls are versioned App Settings: minimum similarity, minimum support and minimum winner share. Other History implementation constants stay in code unless a supported operator use case is explicitly added.
- Internal implementation constants stay code unless there is a supported operator use case.

The Paperless API token and OCR service token must never be written to app-config/history or returned by the Control Center API.

The public Control Center UI is English. Fresh-install OCR and prompt defaults are English, with English/German prompt presets available. Keep UI language, OCR language and prompt language independent.

Keep externally documented ports, secrets and integration contracts stable unless a migration is explicitly planned. The core image defaults to `/usr/local/bin/plai-core`; it retains `/app/core_service.py` as an exec-based compatibility shim and also retains standalone `worker.py`, `prompt_ui.py` and `suggestion_bridge.py` entry points for deployments that explicitly invoke them.

## Compatibility

The OCRmyPDF plugin and native suggestion bridge are verified against Paperless-ngx 3.0.5; the plugin targets OCRmyPDF 17.4.2's native `generate_ocr()` / `OcrElement` contract.

Hybrid tagging uses documented Paperless REST document/tag fields and depends on the configured review-tag workflow semantics. Do not broaden compatibility claims without integration testing the target Paperless release.

Current published OCR support is linux/amd64. Do not claim ARM64 until the Paddle image/runtime is validated.

## Safety and privacy

- Never commit real tokens, `.env`, private document text, OCR dumps, private IP addresses or user-specific paths.
- Tests, documentation and examples must use clearly synthetic fixtures. Never reuse names, organizations, addresses, document IDs, titles, excerpts or other values taken from a private Paperless archive.
- Do not add telemetry or cloud dependencies by default.
- The Control Center has no authentication; documentation must warn against public exposure.
- The OCR service is token-authenticated but must still be documented as a private/LAN endpoint.
- Preserve the original Paperless document; searchable OCR belongs in Paperless' archive/content path.
- Retrieved document excerpts may be sent only to the configured local Ollama endpoint and must be framed as untrusted document content by the editable default prompt.

## Required checks

Before merging code changes:

```bash
cargo fmt --all -- --check
cargo check --locked --workspace --all-targets
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
python -m compileall -q src tests scripts
pytest -q
docker compose -f compose.yaml config
docker compose -f compose.yaml -f compose.dev.yaml config
```

For Hybrid tagging changes, also test confidence-gated routing, fast-path schema omission, parent-tag pruning, review-tag exclusion, few-shot selection and potential-inconsistency diagnostics.

For correspondent resolver changes, test exact, strong fuzzy, ambiguous and genuinely new-name behavior.

For OCR lifecycle/plugin changes, also verify the session/lock contract and one real Paperless end-to-end document.

## Release discipline

- `VERSION` contains the release version without a leading `v`.
- GitHub Release tag must be `v<VERSION>`.
- Release workflow publishes exact GHCR tags; non-prerelease releases also update `stable` and `latest`.
- `SOURCE-MANIFEST.json` must match runtime source.
- Do not silently change mounts, ports, required environment variables or service graph in an image-only patch release; TrueNAS Custom App image updates do not rewrite stored Compose YAML.
