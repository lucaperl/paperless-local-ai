# Docker Compose installation

This guide covers a normal Docker Compose deployment. For TrueNAS SCALE, use the [TrueNAS guide](truenas.md).

## Before you start

You need:

- a running Paperless-ngx instance;
- a running Ollama instance that the app containers can reach;
- Docker Compose v2;
- a Paperless API token;
- an installed Ollama model (`qwen3.5:4b` is the default).

The tested reference workflow uses German OCR and German default prompts. OCR language and prompts are configurable; see [Compatibility](compatibility.md) for the currently tested scope.

## 1. Download

```bash
git clone https://github.com/lucaperl/paperless-local-ai.git
cd paperless-local-ai
cp .env.example .env
```

## 2. Create the Paperless token and configure deployment values

In Paperless, create an API token under **My Profile**. The token's user must be allowed to read and update the documents and taxonomy the app should manage.

Edit `.env` and set at least:

```text
PAPERLESS_TOKEN
APP_VERSION
APP_DATA_DIR
PROMPT_UI_BIND / PROMPT_UI_PORT
SUGGESTION_BRIDGE_BIND / SUGGESTION_BRIDGE_PORT
```

`APP_VERSION=stable` follows the newest non-prerelease image. Replace `stable` with an exact release number if you want the deployment to stay pinned.

Normal runtime settings such as Paperless/Ollama URLs, OCR language, workflow tags and prompts are configured in the Control Center, not duplicated in `.env`.

## 3. Start the Control Center

Start only the web UI first:

```bash
docker compose up -d prompt-ui
```

Default local URL:

```text
http://127.0.0.1:30148/
```

The Control Center has no built-in authentication. Only bind it to localhost or a trusted network.

If Docker runs on another machine and you want to open the Control Center from your workstation, set `PROMPT_UI_BIND` in `.env` to a trusted address on the Docker host, then open `http://<docker-host>:30148/`. Do not expose the Control Center directly to the public Internet.

If you later enable Paperless' native new-correspondent review, the suggestion bridge must also be reachable from Paperless. Keep `SUGGESTION_BRIDGE_BIND=127.0.0.1` unless you use that feature; otherwise bind it to a trusted host/LAN address Paperless can reach.

### Choose reachable Paperless and Ollama URLs

The fresh defaults are:

```text
http://paperless:8000
http://ollama:11434
```

Those names work only when `paperless` and `ollama` are resolvable from this Compose network. Separate Compose projects do **not** automatically share service-name DNS.

Common setups:

- **Paperless/Ollama on another machine:** use that machine's LAN address and published port.
- **Paperless/Ollama on the same Docker host but outside this Compose project:** use an address and published port that are reachable from the containers, typically the host's LAN address.
- **Shared user-defined Docker network:** service names can be used after you explicitly attach the relevant services to the same network.

Do not use `localhost` for Paperless or Ollama unless those services actually run inside the same container, which they normally do not.

Under **App Settings → Connections**, enter the URLs and use **Test connections with current draft** before saving.

## 4. Configure the app

In **App Settings**:

1. save the tested Paperless and Ollama connections;
2. review the pipeline tag names;
3. review OCR language, PaddleOCR generation and device;
4. review polling and Dry Run.

Then open **Classification** and **Correspondent fallback** and review the model/prompt settings.

The default model is `qwen3.5:4b`. If you select another model, it must already exist in the configured Ollama instance.

## 5. Configure Paperless

Follow [Paperless setup](paperless-setup.md) to create the required tags and import workflow.

The tag names in Paperless must exactly match the names saved in the Control Center.

## 6. Test before production

The interactive tests in the Control Center are the safest first check:

- **Classification → Preview** renders the exact request without calling Ollama.
- **Classification → Test** calls Ollama for an existing Paperless document without modifying that document.
- **Correspondent fallback → Preview/Test** does the same for the optional sender-identification stage.

For an automatic pipeline test, you can enable **Dry Run** before starting all workers.

Dry Run applies to the metadata worker only:

- it does not write title, document type, date, content tags or correspondent;
- it does not persist a new-correspondent review record;
- it still stores the processing result under `APP_DATA_DIR/core/results/`;
- technical queue/error tags still move as the workflow progresses.

The OCR worker is separate from Dry Run. If a queued scanned document is reprocessed with PaddleOCR, Paperless' extracted `content` may still be updated.

## 7. Start the full stack and verify

```bash
docker compose up -d
docker compose --profile tools run --rm doctor
```

The doctor checks the saved settings, Paperless/token access, required tags, Ollama and configured models.

For the first end-to-end test, use one document you can easily verify:

- add the configured OCR queue tag manually to an existing document; or
- import a new document after the Paperless workflow is enabled.

Only process a larger batch after that document completes as expected.

## First OCR run

PaddleOCR model assets are cached below `APP_DATA_DIR/ocr/`. The first OCR job may take longer while missing model files are downloaded.
