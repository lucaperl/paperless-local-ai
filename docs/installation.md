# Installation

This guide covers a normal Docker Compose deployment. For TrueNAS SCALE, use the [TrueNAS guide](truenas.md).

## Before you start

You need:

- a running Paperless-ngx instance;
- a running Ollama instance reachable from the app containers;
- Docker Compose v2;
- a Paperless API token;
- an installed Ollama model (`qwen3.5:4b` is the default).

Release 0.1.0 is tested on linux/amd64 with Paperless-ngx 3.0.5. See [Compatibility](compatibility.md).

## 1. Download

```bash
git clone https://github.com/lucaperl/paperless-local-ai.git
cd paperless-local-ai
cp .env.example .env
```

## 2. Configure deployment values

Edit `.env` and review at least:

```text
PAPERLESS_TOKEN
APP_VERSION
APP_DATA_DIR
PROMPT_UI_BIND / PROMPT_UI_PORT
SUGGESTION_BRIDGE_BIND / SUGGESTION_BRIDGE_PORT
```

Use `APP_VERSION=stable` to follow the newest non-prerelease image, or pin an exact release such as `0.1.0`.

Normal runtime settings such as Paperless/Ollama URLs, OCR language, workflow tags and prompts are configured in Prompt Studio, not duplicated in `.env`.

## 3. Start Prompt Studio

```bash
docker compose up -d prompt-ui
```

Default local URL:

```text
http://127.0.0.1:30148/
```

Prompt Studio has no built-in authentication. Only bind it to localhost or a trusted network.

In **App-Einstellungen**, configure and test the Paperless and Ollama connections, then review tags, OCR and runtime settings.

Container networking matters: `localhost` inside a container is not the Docker host. Use addresses the containers can actually reach.

## 4. Configure Paperless

Create the required technical tags and import workflow from [Paperless setup](paperless-setup.md).

## 5. Review the LLM stages

In Prompt Studio:

- **Klassifizierung** controls the main structured metadata request;
- **Korrespondent-Vorschlag** controls the optional second pass used only when the main classifier cannot resolve a correspondent.

Test both stages with known documents before enabling the correspondent fallback for production use.

## 6. Start and verify

```bash
docker compose up -d
docker compose --profile tools run --rm doctor
```

The doctor checks Paperless, the token, required tags, Ollama and configured models.

Import one normal test document before processing a larger batch.

## First OCR run

PaddleOCR model assets are cached below `APP_DATA_DIR/ocr/`. The first OCR run may take longer while missing model files are downloaded.
