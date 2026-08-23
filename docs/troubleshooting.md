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

## Classification queue never moves

Check:

- the Paperless **Document Added** workflow adds the configured classification queue tag;
- Paperless and Control Center tag names match;
- the model configured in Classification exists in Ollama;
- the metadata worker can reach both Paperless and Ollama;
- `ai.lock` is not held by an active OCR session.

OCR has no queue/error tags to clear because it runs during Paperless import.

## A document was processed but metadata did not change

Check whether **Dry run** is enabled.

Dry run suppresses metadata/review writes but still stores processing results and manages metadata workflow tags.

OCR is part of Paperless import and is independent from metadata Dry run.

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

High-resolution pages can make PaddleOCR use several GiB of RAM even when the source PDF itself is small.

Measured with PP-OCRv6 Medium on the reference setup:

| Maximum OCR image dimension | OCR-service peak |
|---|---:|
| 3000 px | ~4.4–4.7 GiB |
| 3200 px | ~4.9–5.1 GiB |
| 4000 px | ~6.5 GiB |

If OCR is killed or the host reports an OOM:

1. Lower **App Settings → OCR → Maximum OCR image dimension** first.
2. If needed, try **PP-OCRv6 Small** or **Tiny**. Their exact RAM savings have not been benchmarked, but they have lower inference cost than Medium.
3. Check other host workloads. Paperless, Ollama, the OS/cache and unrelated services also need memory.
4. Raise `OCR_MEMORY_LIMIT` only when the host genuinely has spare RAM. It is a safety ceiling, not a RAM-reduction setting.

The image limit affects only the temporary image sent to PaddleOCR. The original Paperless document is unchanged.

If the kernel reports a **global host OOM**, increasing only the OCR container limit can make the host-wide problem worse.

## OCR retries and failures

Temporary OCR errors are retried automatically. The default waits are 15 seconds, 1 minute, 5 minutes and 10 minutes.

The **OCR recovery** card shows:

- **Ready** — OCR is available and no action is needed;
- **OCR running** — a page is currently being processed;
- **Waiting to retry** — the same page will be retried automatically after a temporary problem; **Retry now** skips only the remaining wait;
- **Needs attention** — OCR did not recover automatically and the underlying problem needs to be fixed.

Raw exception text is available under **Technical details**. Common memory-related errors also point back to **Maximum OCR image dimension** as the first setting to reduce.

Errors that are unlikely to resolve on their own, such as invalid authentication, an OCR-language mismatch, invalid configuration or malformed input, are not retried.

If all attempts fail, the failed task remains visible in Paperless File Tasks and the Control Center keeps a bounded **Recent OCR failures** list. Paperless-ngx 3.0.5 does not provide a supported generic retry action for an already failed initial consume task. Fix the cause, then submit the source again through Paperless. **Dismiss** only hides the Control Center notice; it does not retry, modify or delete the document.

With one Paperless task worker, later imports wait behind a document that is currently in retry backoff. The failed Paddle process has already stopped during the wait, so its heavy OCR memory is released.

For longer custom retry schedules, remember that Paperless' worker timeout is 1800 seconds by default.

## App settings seem ignored

Runtime settings are loaded from `APP_DATA_DIR/config/app-config.json`.

Deployment-owned values such as ports, mounts, HPI enablement, CPU/RAM/shared-memory limits and Paperless-side plugin environment require recreating/redeploying the affected containers.

## History-assisted tagging does not reuse history

A historical tag is reused only when the strict confidence gate passes. Check:

- the document used as history has left the configured review tag and is not still in the classification queue/error state;
- at least two reviewed neighbors support the same winning tag;
- the nearest reviewed document has exactly one leaf content tag;
- nearest similarity is at least 0.60 and weighted winner share is at least 0.50;
- **Classification → Tagging → History health** is not reporting a refresh error.

Use **Refresh history** after correcting historical tags if you want an immediate rebuild. A fallback to the LLM is expected when the archive does not provide a sufficiently strong and internally consistent historical match.

## New correspondent does not appear in native Suggestions

Check:

- the Classification result extracted a plausible new sender rather than resolving an existing correspondent or leaving it empty;
- the document still has the review tag;
- Paperless AI settings point at the suggestion bridge;
- embeddings are disabled for this narrow bridge integration;
- Paperless can reach the bridge;
- bridge `/health` is healthy.

The bridge deliberately fails closed on absent or ambiguous document matching. There is no separate correspondent-only model call in v0.3.0.
