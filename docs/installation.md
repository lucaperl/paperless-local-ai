# Docker Compose installation

This guide covers a Docker Compose deployment. For TrueNAS SCALE, use the [TrueNAS guide](truenas.md).

## Before you start

You need:

- a running Paperless-ngx instance;
- a running Ollama instance reachable from the app containers;
- Docker Compose v2;
- a Paperless API token;
- an installed Ollama model (`qwen3.5:4b` is the default);
- permission to add the OCRmyPDF plugin mount/environment to Paperless.

Fresh installations use English OCR and English prompt defaults. OCR language and the three editable prompt components can be changed independently in the Control Center.

## 1. Download

```bash
git clone https://github.com/lucaperl/paperless-local-ai.git
cd paperless-local-ai
cp .env.example .env
```

## 2. Configure deployment secrets and paths

Create a Paperless API token under **My Profile**. The token's user must be allowed to read/update the documents and taxonomy the app should manage.

Edit `.env` and set at least:

```text
PAPERLESS_TOKEN
OCR_SERVICE_TOKEN
APP_VERSION
APP_DATA_DIR
```

Generate `OCR_SERVICE_TOKEN` as a separate random secret, for example:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

The same secret is later configured in Paperless as `PLAI_OCR_TOKEN`.

`APP_VERSION=stable` follows the newest non-prerelease image. Replace it with an exact release number for a pinned deployment.

Runtime settings such as Paperless/Ollama URLs, OCR language, workflow tags and prompts are configured in the Control Center.

## 3. Start the app

```bash
docker compose up -d
```

Default host bindings are loopback-only:

```text
Control Center:     http://127.0.0.1:30148/
Suggestion bridge:  http://127.0.0.1:30149/
OCR service:        http://127.0.0.1:30150/
```

The Control Center has no built-in authentication. Keep it on localhost or a trusted network.

Paperless must be able to reach the OCR service. If Paperless is not attached to this Compose network, change `OCR_SERVICE_BIND` from `127.0.0.1` to a trusted host/LAN address (or `0.0.0.0` with appropriate firewalling) and use that reachable address in `PLAI_OCR_URL`. If Paperless is explicitly attached to the same Docker network, it can instead use `http://ocr-service:8082` without relying on the published host port.

The OCR service requires its bearer token for OCR requests. Keep it private/LAN-only even with authentication enabled.

### Container networking

The fresh app defaults for external services are:

```text
http://paperless:8000
http://ollama:11434
```

Those names work only when they resolve from this Compose network.

Common alternatives:

- use another machine's LAN address and published port;
- use the Docker host's reachable LAN address for services in another Compose project on the same host;
- explicitly attach projects to a shared user-defined Docker network.

Do not use `localhost` for Paperless or Ollama unless the target service really runs inside that same container.

Open **App Settings → Connections** and use **Test connections with current draft** before saving.

## 4. Configure Paperless OCRmyPDF

Paperless must load the included OCRmyPDF plugin so scanned pages are processed by PaddleOCR.

The OCR service publishes the plugin below:

```text
APP_DATA_DIR/integration/ocrmypdf_plai.py
```

Mount that directory into the Paperless container read-only, for example:

```yaml
volumes:
  - /absolute/path/to/paperless-local-ai/data/integration:/opt/paperless-local-ai:ro
```

Then add these Paperless environment values:

```text
PLAI_OCR_URL=http://<host-or-service-reachable-from-paperless>:30150
PLAI_OCR_TOKEN=<same value as OCR_SERVICE_TOKEN>
PLAI_OCR_TIMEOUT_SECONDS=1800
PAPERLESS_OCR_USER_ARGS={"plugins":["/opt/paperless-local-ai/ocrmypdf_plai.py"],"pdf_renderer":"fpdf2","optimize":0}
```

`PLAI_OCR_URL` is resolved from inside the Paperless container. Choose an address it can actually reach.

The OCR language requested by Paperless must correspond to the language configured under **App Settings → OCR**. Common Paperless/Tesseract codes such as `deu`/`eng` are normalized to PP-OCRv6 codes such as `de`/`en`.

See [Paperless setup](paperless-setup.md) for the full tested integration contract.

## 5. Configure metadata processing

In the Control Center:

1. save the tested Paperless and Ollama connections;
2. review the classification queue/error/review tag names;
3. review OCR language/version/model profile/maximum image side/device;
4. complete [Paperless setup](paperless-setup.md), including the review-tag lifecycle and matching-algorithm settings;
5. review polling and optional Dry Run;
6. review Classification model/prompt settings;
7. open **Classification → Tagging**, keep **Hybrid tagging** for compact models unless you intentionally want LLM direct tag decisions, and add optional Tag Guidance where your taxonomy needs explanation.

The default model is `qwen3.5:4b`. Any selected model must already exist in Ollama. Hybrid tagging is the recommended tag strategy for the 4B reference model; see [Tagging](tagging.md) for the rationale, confidence gate and evaluation.

## 6. Configure Paperless workflow/tags

Follow [Paperless setup](paperless-setup.md).

Only the metadata/review workflow tags are required by the app. OCR runs directly during Paperless import through OCRmyPDF.

## 7. Verify

Run:

```bash
docker compose --profile tools run --rm doctor
```

Then import one scanned document you can verify.

Expected sequence:

```text
Paperless import
→ OCRmyPDF / PaddleOCR / PP-OCRv6 when OCR is needed
→ Document Added workflow adds LLM tag
→ metadata worker
→ configured review tag / human review
```

For a scanned PDF, verify both the extracted text and Paperless' archive file before processing a larger batch.

## Dry Run

Dry Run applies to the **metadata worker only**.

With Dry Run enabled it suppresses title/type/date/content-tag/correspondent write-back and persistent new-correspondent review records, but it still stores the processing result and manages technical metadata tags.

OCR is part of Paperless import and is therefore independent from metadata Dry Run.

## First OCR run

PaddleOCR models and HPI/OpenVINO artifacts are cached below `APP_DATA_DIR/ocr/`. The first run on a fresh cache can take substantially longer while models and optimized inference artifacts are prepared.

## Updates

The default `APP_VERSION=stable` follows the newest non-prerelease image.

For an image-only update:

```bash
docker compose pull
docker compose up -d
docker compose --profile tools run --rm doctor
```

If the release notes describe a deployment-contract change, update the Compose configuration and any required Paperless mounts/environment before redeploying. A container image cannot add new stored mounts, ports or environment variables to an existing deployment by itself.

For a pinned deployment, set `APP_VERSION` to the exact release tag you want to run.

