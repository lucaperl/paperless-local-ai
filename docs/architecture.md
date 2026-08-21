# Architecture

`paperless-local-ai` is intentionally narrow: replace Tesseract OCR inference with PaddleOCR inside Paperless' normal OCR pipeline, automatically write classified metadata back to Paperless with a small local model, and expose genuinely new correspondents through Paperless Suggestions instead of creating them automatically.


## Why this architecture

The architecture is built around OCR quality, practical local inference on modest CPU-only hardware, and reliable automation inside Paperless:

- **OCR quality before classification:** OCR text is the input to the metadata model. PP-OCRv6 Medium remains the quality-focused default, while Small and Tiny can reduce inference cost on more constrained systems. HPI/OpenVINO accelerates the selected profile on CPU. A vision-language pipeline would remove the separate OCR stage but requires substantially more inference capacity.
- **One normal LLM request per document:** title, document type, date, tags and an existing correspondent are returned together so the document context is not reprocessed independently for every metadata field. The reference deployment uses `qwen3.5:4b`.
- **Automatic but bounded metadata:** normal results are written back automatically, while document types, tags and existing correspondents remain constrained to the current Paperless taxonomy. New correspondent candidates go through Paperless Suggestions.
- **Bounded resource usage:** PaddleOCR/OpenVINO and Ollama inference are serialized, OCR sessions are reused briefly across pages, and heavy model processes are released again after processing.

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
        PaddleOCR
        PP-OCRv6 profile
        Medium / Small / Tiny
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
  new      → Paperless Suggestions
      ↓
Paperless metadata + Inbox/review
```

The original uploaded PDF remains Paperless' original. OCR happens while Paperless consumes the document; `paperless-local-ai` does not maintain a separate OCR queue.

## Services

One Compose project runs four long-lived services from two images:

| Service | Purpose |
|---|---|
| `ocr-service` | authenticated PaddleOCR service used by the OCRmyPDF plugin |
| `metadata-worker` | metadata classification and optional correspondent fallback |
| `prompt-ui` | Control Center: configuration, testing and history |
| `suggestion-bridge` | exposes new correspondent candidates through Paperless Suggestions |

The optional `doctor` profile uses the core image as a one-shot deployment check.

Paperless and Ollama remain external.

## OCRmyPDF integration

The OCR image writes `ocrmypdf_plai.py` into the persistent `/integration` mount at startup. Paperless mounts that same host directory read-only and loads the plugin through `PAPERLESS_OCR_USER_ARGS`.

The plugin is verified against OCRmyPDF **17.4.2** as bundled by Paperless-ngx **3.0.5**. It uses OCRmyPDF 17's native `generate_ocr()` interface:

1. OCRmyPDF decides whether the page needs OCR and rasterizes it;
2. the plugin streams that image to `ocr-service`;
3. PaddleOCR runs detection and recognition with the selected PP-OCRv6 profile;
4. the service returns line/word geometry and text;
5. the plugin returns an `OcrElement` tree plus plain text;
6. OCRmyPDF creates the searchable archive representation.

For pages handled by the plugin, PaddleOCR is the OCR inference engine instead of Tesseract.

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

The default deployment uses the PP-OCRv6 Medium profile, PaddleX HPI/OpenVINO, four CPU threads, a 7 GiB OCR limit and a five-second idle timeout. Small and Tiny profiles can be selected in the Control Center without changing the deployment.

## CPU-focused OCR runtime

The OCR path is tuned to keep PP-OCRv6 practical on CPU-only systems while making the quality/performance trade-off explicit. OCR quality matters here because the recognized text becomes the input to metadata classification.

The main runtime choices are:

- matching PP-OCRv6 **Medium**, **Small** or **Tiny** detection/recognition models, with Medium as the default;
- PaddleX HPI with OpenVINO on CPU;
- a persistent PaddleX/OpenVINO cache;
- four inference threads in the reference deployment;
- brief session reuse across pages of the same document;
- full Paddle subprocess teardown after the idle window.

Reference measurements on an Intel Core i3-8100 (4 cores / 4 threads, 16 GB RAM, no GPU) with the current PP-OCRv6 Medium / HPI / OpenVINO setup are **23.6 seconds** for the first scanned page after OCR idle and **17.6 seconds per additional page** in the same warm OCR session. With `qwen3.5:4b` Q4_K_M, metadata classification measured **80.1 seconds per document**; the optional Correspondent fallback measured **53.4 seconds** when needed. These values are reference measurements for that system, not performance guarantees.

## Shared OCR/LLM resource lock

OCR and metadata inference share one exclusive file lock below `coordination/ai.lock`.

That prevents Paddle/OpenVINO and Ollama from competing for the same CPU/RAM budget. The metadata worker holds the lock across the primary classification and optional correspondent fallback, then explicitly unloads configured Ollama models before releasing the transaction.

## One structured metadata request

The primary metadata stage returns all normal metadata in one structured request constrained by the current Paperless taxonomy:

- title;
- document type;
- content tags;
- date;
- an existing correspondent.

The document context is therefore processed once for normal classification rather than once per metadata field, avoiding repeated prompt evaluation on CPU-bound local inference.

## Separate correspondent fallback

The main request stays constrained to existing values. Only when it cannot resolve a correspondent does the optional second narrow prompt get permission to return a free-text correspondent name.

An exact existing match can be applied automatically. A genuinely new correspondent is exposed through Paperless Suggestions and is never auto-created.

When the fallback is needed, the configured model stays loaded across the primary and fallback requests and is explicitly unloaded afterward.

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

For Paperless-ngx 3.0.5, open correspondent review records are matched by a SHA-256 signature of the normalized document content used by Paperless' no-RAG AI classifier. Ambiguous matches fail closed.

Filename matching is deliberately not used because Paperless' internal model filename and normal REST filename fields are not equivalent.
