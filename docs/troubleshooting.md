# Troubleshooting

Start with the checks for your deployment type, then use the symptom-specific sections below.

## Docker Compose: run the doctor

```bash
docker compose --profile tools run --rm doctor
```

It checks saved app settings, Paperless/token access, required metadata/review tags, Ollama reachability and configured model names.

## TrueNAS: check the Control Center first

The published TrueNAS template does not include the one-shot `doctor` service.

Use:

1. **App Settings → Connections → Test connections with current draft**;
2. the TrueNAS app/container logs;
3. the checks below.

## Logs

Docker Compose:

```bash
docker compose logs --tail 200 ocr-service
docker compose logs --tail 200 metadata-worker
docker compose logs --tail 200 prompt-ui
docker compose logs --tail 200 suggestion-bridge
```

On TrueNAS, use the corresponding container-log view.

## Paperless or Ollama connection fails

Configured URLs are resolved from inside the app containers.

Check that:

- you are not using `localhost` for an external service;
- target host/port is reachable from the container network;
- Paperless/Ollama listens on a reachable address;
- firewall/host rules permit the connection.

Separate Compose projects do not automatically share service-name DNS.

## Paperless import does not use PaddleOCR

Check the Paperless-side integration first:

- `/opt/paperless-local-ai/ocrmypdf_plai.py` exists inside the Paperless container;
- `PAPERLESS_OCR_USER_ARGS` contains that plugin plus `pdf_renderer=fpdf2` and `optimize=0`;
- `PLAI_OCR_URL` is reachable from inside Paperless;
- `PLAI_OCR_TOKEN` exactly matches `OCR_SERVICE_TOKEN`;
- `ocr-service` `/health` is reachable;
- Paperless' OCR language corresponds to the language configured in the Control Center.

Native-text PDFs may legitimately avoid Paddle inference in Paperless/OCRmyPDF's automatic path. Use a real scanned/raster PDF for the first OCR test.

If the OCR service returns `ocr_language_mismatch`, align the two OCR language settings.

## First OCR request is much slower

A fresh OCR cache can need to download model assets and/or prepare HPI/OpenVINO inference artifacts.

The cache persists below:

```text
APP_DATA_DIR/ocr/
```

Subsequent cold-session starts should reuse those artifacts.

## OCR reports idle but metadata does not start

`/health.session_active=false` means the OCR service has released the global AI slot.

Check:

- the shared `coordination` directory is mounted into both OCR and metadata services;
- the `LLM` tag is on the document;
- the metadata worker is running;
- the configured model exists in Ollama.

## LLM queue never moves

Check:

- the Paperless **Document Added** workflow adds the configured LLM queue tag;
- Paperless and Control Center tag names match;
- the model configured in Classification exists in Ollama;
- the metadata worker can reach both Paperless and Ollama;
- `ai.lock` is not held by an active OCR session.

OCR has no queue/error tags to clear because it runs during Paperless import.

## A document was processed but metadata did not change

Check whether **Dry Run** is enabled.

Dry Run suppresses metadata/review writes but still stores processing results and manages metadata workflow tags.

OCR is part of Paperless import and is independent from metadata Dry Run.

## Existing content tags disappeared or changed

Normal metadata write-back replaces the document's eligible content tags with the tags returned by the classifier.

Technical workflow/review tags and additionally excluded tags are preserved.

Use Dry Run and one test document before enabling metadata automation on an existing archive.

## Ollama stays loaded after a document finishes

Normal metadata processing explicitly unloads every configured Ollama model after the primary/fallback transaction.

Check:

- metadata-worker logs for `[UNLOAD]` / `[UNLOAD-WARN]`;
- Ollama `/api/ps`;
- whether another client outside `paperless-local-ai` is actively using the same model.

The configured finite keep-alive is only a fail-safe if normal explicit unload cannot run.

## OCR process is killed or the host runs out of memory

High-resolution scan rasters can make PaddleOCR memory use rise sharply even when the source PDF itself is small.

Under **App Settings → OCR**, lower **Maximum OCR image side** before increasing the OCR container memory limit. The default is **3000 px**. Reference PP-OCRv6 Medium tests observed roughly **4.4–4.7 GiB** OCR-service peak at 3000 px, **4.9–5.1 GiB** at 3200 px and **6.5 GiB** at 4000 px. Actual memory use varies.

The limit affects only the temporary OCR raster. The Paperless original remains untouched and OCRmyPDF keeps the visible page geometry unchanged.

If the kernel reports a **global host OOM**, raising only the OCR container limit can make the host-wide pressure worse. Leave enough RAM for Paperless, the container host and other services.

Check `/health` for the active `max_side_pixels` value and OCR logs for the actual raster dimensions sent to PaddleOCR.

## OCR retries and final failures

Transient OCR failures are retried inside the Paperless/OCRmyPDF import while the consume task is still active. The default waits are 15 seconds, 1 minute, 5 minutes and 10 minutes. Change or disable the schedule under **App Settings → OCR**. The default schedule is kept below Paperless' 1800-second worker timeout with room for the OCR attempts; longer custom schedules may require a higher `PAPERLESS_WORKER_TIMEOUT`.

The **OCR recovery** card shows four normal states:

- **Ready** — no recovery action is needed;
- **OCR running** — an OCR attempt is active;
- **Waiting to retry** — a transient failure was detected and another bounded attempt is scheduled; **Retry now** skips only the remaining wait;
- **Needs attention** — the configured retries were exhausted or the failure was classified as deterministic.

Only transient failures are retried. Authentication/configuration errors, OCR language mismatches, malformed input and deterministic Paddle errors fail immediately.

Final failures remain visible in Paperless File Tasks and are also kept in the Control Center's bounded **Recent final failures** history. Paperless-ngx 3.0.5 does not expose a supported generic retry operation for an already failed initial consume task, so the Control Center deliberately does not pretend it can safely requeue that completed failure. Fix the cause, then submit the source again through Paperless. **Dismiss** only removes the Control Center history entry.

If repeated failures are memory-related, lower **Maximum OCR image side** before increasing the OCR container memory limit.

## App settings seem ignored

Runtime settings are loaded from `APP_DATA_DIR/config/app-config.json`.

Deployment-owned values such as ports, mounts, HPI enablement, CPU/RAM/shared-memory limits and Paperless-side plugin environment require recreating/redeploying the affected containers.

## New correspondent does not appear in native Suggestions

Check:

- **Enable in production** is on under Correspondent fallback;
- fallback produced a genuinely new name;
- the document still has the review tag;
- Paperless AI settings point at the suggestion bridge;
- embeddings are disabled for this narrow bridge integration;
- Paperless can reach the bridge;
- bridge `/health` is healthy.

The bridge deliberately fails closed on absent or ambiguous document matching.
