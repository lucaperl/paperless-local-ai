# Updating paperless-local-ai

Software and instance state are deliberately separate:

```text
GitHub/GHCR images  = application software
APP_DATA_DIR         = settings, prompt history, OCR cache and review state
```

## Before any update

1. Read the release notes and `CHANGELOG.md`.
2. Check [Compatibility](compatibility.md).
3. Back up at least `APP_DATA_DIR/config` and open review state under `APP_DATA_DIR/core`.
4. Keep the previous exact images available until a one-document smoke test passes.

## 0.1.x → 0.2.0

0.2.0 is a **deployment-contract change**, not an image-only update.

Before switching to the 0.2.0 images:

1. update the app Compose/TrueNAS YAML from the 0.2.0 template;
2. add a persistent `integration` directory/mount;
3. add `OCR_SERVICE_TOKEN`;
4. mount that integration directory read-only into Paperless;
5. configure Paperless `PLAI_OCR_URL`, `PLAI_OCR_TOKEN`, `PLAI_OCR_TIMEOUT_SECONDS` and `PAPERLESS_OCR_USER_ARGS`;
6. replace the old `PaddleOCR` import queue workflow with the 0.2.0 **Document Added → LLM** workflow;
7. remove obsolete PaddleOCR queue/error tags after confirming nothing else uses them;
8. process one scanned test document end-to-end before normal use.

Existing `app-config.json` files are validated against the current schema. Old OCR queue/error fields are ignored automatically.

Adding `LLM` to an existing document only queues metadata classification; it does not re-OCR that document.

## Docker Compose using `stable`

For an image-only compatible release:

```bash
docker compose pull
docker compose up -d
docker compose --profile tools run --rm doctor
```

If release notes describe a deployment-contract change, update Compose/Paperless integration first.

## Docker Compose pinned to an exact release

Set:

```text
APP_VERSION=<exact-release>
```

then:

```bash
docker compose pull
docker compose up -d
docker compose --profile tools run --rm doctor
```

## TrueNAS Custom App

A new image digest behind `stable` can appear as TrueNAS' normal app update.

A container image cannot rewrite stored Custom App YAML or Paperless' mounts/environment. Deployment-contract changes therefore require updating the stored YAML and/or Paperless app configuration manually.

## Rollback

For an image-only release that did not migrate persistent data, redeploy the previous exact image tag.

For 0.2.0 → 0.1.x, also restore the matching 0.1.x deployment contract; do not leave a mixed OCR-service/OCR-worker configuration.

The app stores AppConfig and prompt configurations as JSON with version history and does not use its own database.
