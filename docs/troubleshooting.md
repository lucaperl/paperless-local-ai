# Troubleshooting

Start with the checks for your deployment type, then use the symptom-specific sections below.

## Docker Compose: run the doctor

```bash
docker compose --profile tools run --rm doctor
```

It checks the saved App settings, Paperless reachability/token, required queue/review tags, Ollama reachability and configured model names.

## TrueNAS: check the Control Center first

The published TrueNAS template does not include the one-shot `doctor` service.

Use:

1. **App Settings → Connections → Test connections with current draft**;
2. the TrueNAS app/container logs for the failing service;
3. the symptom-specific checks below.

## Logs

Docker Compose:

```bash
docker compose logs --tail 200 ocr-worker
docker compose logs --tail 200 metadata-worker
docker compose logs --tail 200 prompt-ui
docker compose logs --tail 200 suggestion-bridge
```

On TrueNAS, use the app's container-log view for the corresponding service.

## Paperless or Ollama connection fails

The configured URLs are used from inside the containers.

Check that:

- you are not using `localhost` for a service running outside that container;
- the target host/port is reachable from the container network;
- Paperless/Ollama is listening on an address reachable from the app;
- firewalls or host rules do not block the connection.

For separate Compose projects, service names such as `paperless` or `ollama` only work when you explicitly place the services on a shared Docker network.

## OCR queue never moves

Check:

- the Paperless workflow or manual action adds the OCR queue tag configured under **App Settings → Pipeline & Tags**;
- the Paperless API token has document read/write permission;
- Paperless and Control Center tag names match exactly;
- OCR language/version/device under **App Settings → OCR** are valid;
- enough Docker RAM/shared memory is assigned.

On the first OCR job, model assets may still be downloading into the persistent OCR cache.

## LLM queue never moves

Check:

- **App Settings → Connections → Test connections with current draft** succeeds for Ollama;
- the model configured in Classification exists in Ollama;
- no OCR queue/error blocking tag remains on the document;
- the shared `ai.lock` is not held indefinitely by another worker/container.

## A document was processed but metadata did not change

Check whether **Dry Run** is enabled.

Dry Run suppresses metadata and persistent-review writes, but it still moves technical workflow tags and stores the processing result. OCR is separate and may still update Paperless' extracted `content`.

See [Configuration](configuration.md#dry-run).

## Existing content tags disappeared or changed

Normal metadata write-back replaces the document's eligible content tags with the tags returned by the classifier.

Technical workflow/review tags and tags configured as additionally excluded are preserved.

Use Dry Run and one test document before enabling automatic processing on an existing archive. See [Paperless setup](paperless-setup.md#what-metadata-is-written).

## App settings seem ignored

Shared runtime settings are loaded from `APP_DATA_DIR/config/app-config.json`. The OCR and metadata workers reload them during polling, and Ollama/Paperless URLs are resolved at request time. A container restart is normally unnecessary.

Docker-only values such as bind ports, volumes and CPU/RAM limits are different: changing those requires recreating/redeploying the affected container because Docker owns them.

## New correspondent does not appear in native Suggestions

Check:

- **Enable in production** is on under **Correspondent fallback → Settings**;
- fallback produced a genuinely new name, not an exact existing correspondent;
- the document still carries the configured review tag;
- Paperless AI settings point at the suggestion bridge and embeddings are disabled;
- Paperless can reach the bridge port;
- bridge `/health` is healthy.

The bridge deliberately returns no new suggestion when document matching is absent or ambiguous.

If you do not need new correspondents in Paperless' native Suggestions UI, the bridge integration is optional.
