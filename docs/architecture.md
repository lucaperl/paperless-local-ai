# Architecture

`paperless-local-ai` is intentionally narrow: use PaddleOCR inside Paperless' normal OCR pipeline, classify metadata with a small local model, and keep uncertain new correspondents behind human review.

## Pipeline

```text
Paperless import
      ↓
Paperless parser / OCRmyPDF
      ↓
OCR needed for a page?
  no  → keep normal Paperless text path
  yes → OCRmyPDF rasterizes page
          ↓
        OCRmyPDF plugin
          ↓ authenticated HTTP
        ocr-service
        PP-OCRv6 Medium
        HPI / OpenVINO
          ↓
        native OcrElement tree
          ↓
OCRmyPDF searchable archive / PDF-A
Paperless extracted content
      ↓
Paperless Document Added workflow
      ↓
LLM queue tag
      ↓
metadata-worker
  one structured LLM request
  title · type · tags · date · existing correspondent
      ↓
  no correspondent?
      ↓
optional correspondent-only request
  existing → apply
  new      → review candidate
      ↓
Paperless metadata + Inbox/review
```

The original uploaded PDF remains Paperless' original. OCR happens while Paperless consumes the document; `paperless-local-ai` does not maintain a second OCR queue.

## Services

One Compose project runs four long-lived services from two images:

| Service | Purpose |
|---|---|
| `ocr-service` | authenticated PP-OCRv6 service used by the OCRmyPDF plugin |
| `metadata-worker` | metadata classification and optional correspondent fallback |
| `prompt-ui` | Control Center: configuration, testing and history |
| `suggestion-bridge` | Paperless native review adapter for new correspondent candidates |

The optional `doctor` profile uses the core image as a one-shot deployment check.

Paperless and Ollama remain external.

## OCRmyPDF integration

The OCR image writes `ocrmypdf_plai.py` into the persistent `/integration` mount at startup. Paperless mounts that same host directory read-only and loads the plugin through `PAPERLESS_OCR_USER_ARGS`.

The plugin is verified against OCRmyPDF **17.4.2** as bundled by Paperless-ngx **3.0.5**. It uses OCRmyPDF 17's native `generate_ocr()` interface:

1. OCRmyPDF rasterizes the page;
2. the plugin streams that image to `ocr-service`;
3. the service returns line/word geometry and text;
4. the plugin returns an `OcrElement` tree plus plain text;
5. OCRmyPDF creates the searchable archive representation.

No hOCR/XML conversion is used.

## OCR service lifecycle

The OCR service keeps the heavyweight Paddle worker in a spawned subprocess.

When the first OCR request arrives:

1. the service acquires the shared global `ai.lock`;
2. the Paddle subprocess starts and initializes PP-OCRv6;
3. additional pages arriving within the idle window reuse the session;
4. after the idle timeout, the subprocess is stopped;
5. only after cleanup is complete is `ai.lock` released.

`/health.session_active` follows ownership of the global AI slot, not merely process liveness. A reported idle state therefore means the OCR service has actually released the shared lock.

The default deployment uses PP-OCRv6 Medium, PaddleX HPI/OpenVINO, four CPU threads, a 7 GiB OCR limit and a five-second idle timeout.

## Shared OCR/LLM resource lock

OCR and metadata inference share one exclusive file lock below `coordination/ai.lock`.

That prevents Paddle/OpenVINO and Ollama from competing for the same CPU/RAM budget. The metadata worker holds the lock across the primary classification and optional correspondent fallback, then explicitly unloads configured Ollama models before releasing the transaction.

## Why one metadata request?

The reference system is an Intel Core i3-8100 without a GPU. Repeating prompt processing for title, tags, type, date and correspondent made per-field LLM workflows unnecessarily slow.

The main stage therefore returns all normal metadata in one structured request constrained by the current Paperless taxonomy.

## Why a separate correspondent fallback?

The main request stays constrained to existing values. Only when it cannot resolve a correspondent does a second narrow prompt get permission to return a free-text sender name.

An exact existing match can be applied. A genuinely new name becomes a review candidate and is never auto-created.

## Configuration and state

Deployment owns secrets and Docker-level settings. The Control Center owns normal runtime settings and both LLM-stage configurations.

Persistent state lives below one `APP_DATA_DIR`:

```text
config/        app and prompt configuration/history
core/          result and open review records
ocr/           PaddleX/OpenVINO cache and OCR runtime state
coordination/  shared ai.lock
integration/   generated OCRmyPDF plugin consumed by Paperless
```

## Suggestion bridge identity

For Paperless-ngx 3.0.5, open correspondent review records are matched primarily by a SHA-256 signature of the normalized document content used by Paperless' no-RAG AI classifier. Ambiguous matches fail closed.

The legacy short-prefix signature remains only for migrated older records. Filename matching is deliberately not used because Paperless' internal model filename and normal REST filename fields are not equivalent.
