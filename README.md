# paperless-local-ai

[![Tests](https://github.com/lucaperl/paperless-local-ai/actions/workflows/test.yml/badge.svg)](https://github.com/lucaperl/paperless-local-ai/actions/workflows/test.yml)

CPU-first selective OCR and local metadata automation for Paperless-ngx.

`paperless-local-ai` is a companion application for people who already run **Paperless-ngx** and **Ollama**. It can re-OCR scan-like PDF pages with PaddleOCR, classify document metadata with a small local text model, and surface genuinely new correspondent names through Paperless' native Suggestions UI for human approval.

It does **not** replace Paperless, bundle Ollama, modify original PDF files, or auto-create new correspondents.

> **Release status:** `0.1.0`. The complete workflow is production-tested with Paperless-ngx **3.0.5** on **linux/amd64**. The native suggestion bridge is intentionally version-sensitive; do not assume a newer Paperless release is compatible until it has been tested.
>
> **Language note:** the Studio UI and the shipped default prompts are German in `0.1.0`. OCR language is configurable, and prompts can be edited in the Studio, but non-German end-to-end behavior is not yet claimed as tested.

## Why this exists

Paperless already provides OCR and metadata tools. This project adds a deliberately small post-processing pipeline for a different operating point:

- keep trustworthy native PDF text instead of OCRing everything again;
- distrust hidden OCR layers on scan-like pages and run PaddleOCR where the page structure indicates it is needed;
- use a small **text-only** Ollama model for metadata instead of a vision model for every document;
- serialize heavy OCR/LLM work so low-power homeservers are not overloaded;
- keep final review in Paperless.

## How the pipeline works

```text
Paperless imports a document
        |
        | workflow adds the configured OCR queue tag
        v
ocr-worker
        |
        | per page
        |-- trustworthy native text --> keep native text
        |-- scan / sandwich PDF ------> PaddleOCR that page
        |-- ambiguous page -----------> OCR for verification
        |
        | updates Paperless extracted content when justified
        | hands document to LLM queue
        v
metadata-worker
        |
        |-- main structured classification
        |     title / document type / tags / date / existing correspondent
        |
        `-- optional correspondent-only fallback
              exact existing name --> apply
              genuinely new name --> save review candidate
                                      (never auto-create)
        v
Paperless metadata + Inbox/review

Paperless native AI Suggestions request
        |
        v
suggestion-bridge
        |
        | preserves classic Paperless suggestions
        ` adds one uniquely matched open correspondent candidate
        v
Human accepts/rejects inside Paperless
```

The original file stored by Paperless is not replaced. The OCR worker changes Paperless' extracted `content` only.

## Components

One Compose project runs four long-lived services from two images:

| Service | Image | Purpose |
|---|---|---|
| `ocr-worker` | `paperless-local-ai-ocr` | PDF page analysis and PaddleOCR |
| `metadata-worker` | `paperless-local-ai-core` | metadata classification and optional correspondent fallback |
| `prompt-ui` | `paperless-local-ai-core` | central settings/prompt/testing UI |
| `suggestion-bridge` | `paperless-local-ai-core` | adapter for Paperless 3.0.5 native correspondent review |

Ollama stays external and is never started by this Compose project.

## Requirements

For the currently tested release:

- Paperless-ngx **3.0.5**;
- Docker Engine with Docker Compose v2, or a Compose-capable platform such as a TrueNAS Custom App;
- an existing Ollama server reachable from the containers;
- the configured Ollama model installed there (`qwen3.5:4b` is the shipped default);
- linux/amd64 for the published OCR image;
- about 6 GiB of RAM available to the OCR container with the tested defaults.

See [Compatibility](docs/compatibility.md) before using another Paperless version or architecture.

## Quick start — normal Docker Compose

### 1. Get the deployment files

```bash
git clone https://github.com/lucaperl/paperless-local-ai.git
cd paperless-local-ai
cp .env.example .env
```

If you do not want Git installed on the server, download the source archive for the release and use its `compose.yaml` and `.env.example` instead.

### 2. Create a Paperless API token

In Paperless open **My Profile** and create/regenerate an API token. Put it in `.env`:

```text
PAPERLESS_TOKEN=...
```

Use a Paperless user that is allowed to read and update the documents and taxonomy this app will manage. See [Paperless setup](docs/paperless-setup.md).

### 3. Review deployment settings

The upstream images are already the default:

```text
IMAGE_PREFIX=ghcr.io/lucaperl/paperless-local-ai
APP_VERSION=stable
```

`stable` tracks the newest non-prerelease release. Pin `APP_VERSION=0.1.0` if you prefer a reproducible deployment that never moves automatically.

Set `APP_DATA_DIR` to a persistent directory and review the bind addresses/ports. The Studio has **no built-in authentication**, so its default bind is localhost.

### 4. Start only the Studio

```bash
docker compose up -d prompt-ui
```

Open the Studio. If you want to reach it from another machine, first change `PROMPT_UI_BIND` in `.env` to a trusted LAN address and recreate the service.

Configure **App-Einstellungen**:

- Paperless URL;
- Ollama URL;
- queue/error/review tag names;
- OCR language/version/device;
- polling and review cleanup;
- dry-run mode.

Important networking rule: URLs are resolved **from inside the containers**. `http://localhost:...` therefore means the current container, not your Docker host. Use a DNS name or IP address that the app containers can actually reach.

### 5. Prepare Paperless

Create the technical tags and the import workflow from [docs/paperless-setup.md](docs/paperless-setup.md).

### 6. Review the two LLM stages

In the Studio:

- **Klassifizierung** owns the main metadata prompt and model parameters;
- **Korrespondent-Vorschlag** owns a separate correspondent-only prompt and model parameters.

The correspondent fallback is **disabled on a fresh install**. Test it manually before enabling `Produktiv verwenden`.

### 7. Start the complete app and run the doctor

```bash
docker compose up -d
docker compose --profile tools run --rm doctor
```

Then import **one normal test document** before processing a larger archive.

### 8. Optional: native new-correspondent review

If a new correspondent should appear in Paperless' native Suggestions UI, configure Paperless 3.0.5 to use the suggestion bridge as described in [Paperless setup](docs/paperless-setup.md). The bridge must be bound to an address reachable by the Paperless container.

For a longer walkthrough, use [Installation](docs/installation.md).

## TrueNAS SCALE

TrueNAS uses the same public GHCR images and the same four-service architecture; there is no TrueNAS fork.

Use the dedicated [TrueNAS guide](docs/truenas.md) and the ready-to-edit YAML template in [`deploy/truenas/compose.example.yaml`](deploy/truenas/compose.example.yaml).

For a Custom App that follows the floating `stable` image tag, TrueNAS can detect upstream image changes and present its normal **Update** action. No custom update script is required for code-only releases. Compose-structure changes are different and are called out in release notes.

## Published images

```text
ghcr.io/lucaperl/paperless-local-ai-core:<tag>
ghcr.io/lucaperl/paperless-local-ai-ocr:<tag>
```

Release tags:

- `0.1.0`, `0.1.1`, ...: immutable-by-convention release tags for pinning;
- `stable`: newest non-prerelease release, intended for update-aware installations;
- `latest`: same non-prerelease release as `stable`.

The GitHub release workflow builds both images from this repository and publishes build-provenance attestations.

## Where configuration lives

Settings have one owner instead of being duplicated across `.env`, JSON files and UI fields.

| Owner | Examples |
|---|---|
| deployment `.env` / Compose | Paperless token, image tag, app-data path, host ports, resource limits |
| **Studio -> App-Einstellungen** | Paperless/Ollama URL, workflow tags, OCR settings, polling, cleanup, dry-run |
| **Studio -> Klassifizierung** | classification prompt + model/request parameters |
| **Studio -> Korrespondent-Vorschlag** | fallback prompt + model/request parameters + enable switch |

See [Configuration](docs/configuration.md).

## Persistent data and backups

All instance state lives below one `APP_DATA_DIR`:

```text
APP_DATA_DIR/
├── config/        # app config + prompt configs + version history
├── core/          # result JSON + open correspondent review records
├── ocr/           # PaddleOCR model/cache/temp state
└── coordination/  # shared ai.lock
```

The OCR model cache is regenerable. The important app-specific backup content is primarily `config/` plus any open review state in `core/`; Paperless remains the source of truth for document metadata and files.

## Security and privacy

- Never commit `.env` or a Paperless API token.
- Prompt Studio has no authentication; bind it only to localhost or a trusted LAN.
- The suggestion bridge should be reachable by Paperless, not by the public Internet.
- There is no built-in telemetry or cloud inference endpoint.
- Document text is sent to the **Ollama endpoint you configure**. Keep that endpoint local/self-hosted if local-only processing is a requirement.
- PaddleOCR models may need network access on first use unless they are already cached.

See [SECURITY.md](SECURITY.md).


## Current limitations

- Paperless native-suggestion compatibility is verified only for 3.0.5.
- Published OCR image is currently linux/amd64 only.
- Studio UI and shipped prompts are German in 0.1.0.
- Ollama is the only inference backend in 0.1.0.
- The app does not create required Paperless tags/workflows for you.
- TrueNAS image updates cannot rewrite a Custom App's Compose YAML.

## Development with Codex or other coding agents

Start with [`AGENTS.md`](AGENTS.md). It records the project invariants that should not be accidentally broken: the four-service/two-image architecture, external Ollama, selective OCR policy, configuration ownership, shared AI lock and fail-closed correspondent matching.

Local source build:

```bash
cp .env.example .env
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```

Tests:

```bash
make test
```

See [Contributing](CONTRIBUTING.md), [Testing](docs/testing.md) and [Releasing](docs/releasing.md).

## Documentation

- [Installation](docs/installation.md)
- [Paperless setup](docs/paperless-setup.md)
- [TrueNAS deployment](docs/truenas.md)
- [Updating](docs/upgrading.md)
- [Configuration ownership](docs/configuration.md)
- [Architecture](docs/architecture.md)
- [Prompt Studio](docs/prompt-studio.md)
- [Compatibility](docs/compatibility.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Testing](docs/testing.md)
- [Releasing](docs/releasing.md)

## License and project relationship

The project source in this repository is released under the [MIT License](LICENSE). Container images also contain third-party software under its own licenses. In particular, the OCR image directly uses PyMuPDF, whose upstream licensing is GNU AGPL v3 / commercial. Read [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) before redistributing images or using the stack in a proprietary/commercial product.

Paperless-ngx, PaddleOCR/PaddlePaddle, PyMuPDF and Ollama are separate projects with their own licenses and trademarks. `paperless-local-ai` is an independent community project and is not affiliated with or endorsed by those projects.
