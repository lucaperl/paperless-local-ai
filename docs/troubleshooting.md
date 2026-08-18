# Troubleshooting

## Run the doctor

```bash
docker compose --profile tools run --rm doctor
```

It checks the saved App settings, Paperless reachability/token, required queue/review tags, Ollama reachability and currently configured model names.

## Logs

```bash
docker compose logs --tail 200 ocr-worker
docker compose logs --tail 200 metadata-worker
docker compose logs --tail 200 prompt-ui
docker compose logs --tail 200 suggestion-bridge
```

## OCR queue never moves

Check:

- Paperless workflow adds the OCR queue tag configured under **App settings -> Pipeline & Tags**;
- Paperless API token has document read/write permission;
- OCR language/version/device under **App settings -> OCR** are valid for the installed PaddleOCR version;
- enough Docker RAM/shared memory is assigned in `.env`.

## LLM queue never moves

Check:

- **App settings -> Connections -> Test connections with current draft** succeeds for Ollama;
- the model configured in the relevant LLM stage exists in Ollama;
- no configured OCR queue/error blocking tag remains;
- the shared `ai.lock` is not held indefinitely by another worker/container.

## App settings seem ignored

Shared runtime settings are loaded from `APP_DATA_DIR/config/app-config.json`. The OCR and metadata workers reload them during polling, and Ollama/Paperless URLs are resolved at request time. A container restart is normally unnecessary.

Docker-only values such as bind ports, volumes and CPU/RAM limits are different: changing those in `.env` requires recreating/redeploying the affected container because Docker owns them.

## New correspondent does not appear in native Suggestions

Check:

- **Enable in production** is on under **Correspondent fallback -> Settings**;
- fallback produced a genuinely new name, not an exact existing correspondent;
- document still carries the configured review tag;
- Paperless AI settings point at the suggestion bridge and embeddings are disabled;
- Paperless can reach the bridge port;
- bridge `/health` is healthy.

The bridge deliberately returns no new suggestion when document matching is absent or ambiguous.
