# Installation

This guide assumes you have never used `paperless-local-ai` before.

The application is a **companion** to an existing Paperless-ngx and Ollama installation. It does not install either dependency.

## 1. Check the compatibility target

Release 0.1.0 is fully tested with:

```text
Paperless-ngx: 3.0.5
Platform:      linux/amd64
Inference:     external Ollama
OCR:           CPU PaddleOCR / PP-OCRv6
```

Read [compatibility.md](compatibility.md) before using another Paperless version.

The Studio UI and the default prompts are German in 0.1.0. OCR language itself is configurable.

## 2. Make the default Ollama model available

The shipped prompt configurations use:

```text
qwen3.5:4b
```

Make sure that model is installed on the Ollama server, or select another installed model later in the Studio.

Ollama must be reachable **from the paperless-local-ai containers**. If Ollama runs on the Docker host, do not enter `localhost` unless the networking setup specifically makes the host available there; container localhost normally points back to that container.

## 3. Get the repository deployment files

```bash
git clone https://github.com/lucaperl/paperless-local-ai.git
cd paperless-local-ai
cp .env.example .env
```

Alternatively, download a GitHub release/source archive and extract it.

## 4. Create a Paperless API token

In Paperless:

1. open the user menu;
2. open **My Profile**;
3. create/regenerate the API token;
4. copy it into `.env` as `PAPERLESS_TOKEN`.

Paperless token authentication is the normal REST API mechanism used by the app. The token belongs to a Paperless user, so that user must be allowed to read and update the documents/taxonomy the app should manage.

Never commit `.env`.

## 5. Configure deployment-only values

Edit `.env`.

Required/recommended review:

```text
PAPERLESS_TOKEN
APP_VERSION
APP_DATA_DIR
PROMPT_UI_BIND / PROMPT_UI_PORT
SUGGESTION_BRIDGE_BIND / SUGGESTION_BRIDGE_PORT
resource limits
```

The default image prefix already points to the upstream project:

```text
ghcr.io/lucaperl/paperless-local-ai
```

Use:

```text
APP_VERSION=stable
```

to follow the newest non-prerelease image, or:

```text
APP_VERSION=0.1.0
```

to pin the first release.

Do **not** put Paperless/Ollama URLs, OCR language or workflow-tag names in `.env`; those are runtime settings owned by the Studio.

## 6. Start only Prompt Studio

```bash
docker compose up -d prompt-ui
```

Default URL on the Docker host:

```text
http://127.0.0.1:30148/
```

To open Studio from another trusted LAN machine, change `PROMPT_UI_BIND` from `127.0.0.1` to the host's LAN address and recreate the service:

```bash
docker compose up -d --force-recreate prompt-ui
```

Do not expose Studio directly to the Internet; it has no built-in authentication.

## 7. Configure App-Einstellungen

Open **App-Einstellungen** in Studio and set:

### Connections

- Paperless URL, for example `http://192.0.2.10:8000`;
- Ollama URL, for example `http://192.0.2.20:11434`.

Use addresses that are routable **from inside the containers**.

Run the connection test before saving.

### Pipeline & tags

Choose names for:

- OCR queue tag;
- OCR error tag;
- LLM queue tag;
- LLM error tag;
- human-review tag;
- optional taxonomy-excluded tags.

The defaults are documented in [paperless-setup.md](paperless-setup.md).

### OCR

Choose PaddleOCR language/version/device. Release 0.1.0 is tested with:

```text
PP-OCRv6 / de / cpu
```

### Runtime

The shipped defaults are:

```text
polling:        10 seconds
review cleanup: 3600 seconds
dry-run:        false
```

Workers hot-reload App-Einstellungen while running.

## 8. Create the required Paperless tags and workflow

Follow [paperless-setup.md](paperless-setup.md).

The app intentionally does not create or rename Paperless taxonomy objects automatically.

## 9. Review the LLM configurations

Studio has two independent LLM stages:

### Klassifizierung

Main structured metadata classification.

Review the prompt and model settings, then use **Mit Modell testen** on a known document before production processing.

### Korrespondent-Vorschlag

Optional second model pass used only when the main classifier returns no correspondent.

A fresh installation starts this fallback **disabled**. Test it manually, then enable **Produktiv verwenden** if the results are acceptable.

## 10. Start all runtime services

```bash
docker compose up -d
```

Check:

```bash
docker compose ps
```

Expected long-lived services:

```text
ocr-worker
metadata-worker
prompt-ui
suggestion-bridge
```

## 11. Run the doctor

```bash
docker compose --profile tools run --rm doctor
```

The doctor checks:

- App-Einstellungen are readable;
- Paperless is reachable and the token works;
- required Paperless tags exist;
- Ollama is reachable;
- configured model names exist in Ollama.

Fix every `FAIL` before processing real documents.

## 12. Process one test document

Import one ordinary document through the normal Paperless consume/import path.

Watch:

```bash
docker compose logs -f ocr-worker metadata-worker
```

Confirm the expected flow:

```text
OCR queue -> selective OCR -> LLM queue -> metadata write -> review
```

Do not bulk-reprocess an archive until the one-document test is correct.

## 13. Optional native correspondent Suggestions integration

This is not required for OCR or main metadata classification.

If you want genuinely new correspondent names to appear in Paperless' native Suggestions UI:

1. bind `SUGGESTION_BRIDGE_BIND` to an address Paperless can reach;
2. recreate `suggestion-bridge` if the deployment setting changed;
3. configure Paperless 3.0.5 AI settings exactly as described in [paperless-setup.md](paperless-setup.md);
4. verify `http://<bridge-host>:30149/health` from a network location equivalent to Paperless.

The bridge deliberately does not auto-create a correspondent.

## 14. First OCR model download

The OCR image contains the Paddle software stack, but PaddleX/PaddleOCR model assets are cached under:

```text
APP_DATA_DIR/ocr/.paddlex
```

The first OCR use can therefore require network access and take longer while model files are downloaded. Later runs reuse the persistent cache.

## Next steps

- [Configuration ownership](configuration.md)
- [Architecture](architecture.md)
- [Prompt Studio](prompt-studio.md)
- [TrueNAS](truenas.md)
- [Updating](upgrading.md)
- [Troubleshooting](troubleshooting.md)
