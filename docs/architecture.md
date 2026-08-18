# Architecture

`paperless-local-ai` is intentionally narrow: improve scan OCR, classify metadata with a small local model, and keep uncertain new correspondents behind human review.

## Pipeline

```text
Paperless workflow
      ↓
ocr-worker
  native text → keep
  scan/raster → PaddleOCR
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
Paperless metadata + review
```

The original PDF stored by Paperless is never replaced. The OCR worker updates Paperless' extracted content only when the page classification justifies it.

## Services

One Compose project runs four long-lived services from two images:

| Service | Purpose |
|---|---|
| `ocr-worker` | page analysis and PaddleOCR |
| `metadata-worker` | metadata classification and optional correspondent fallback |
| `prompt-ui` | configuration, prompt editing and testing |
| `suggestion-bridge` | Paperless native review adapter for new correspondent candidates |

Ollama remains external.

Heavy OCR and LLM work share one exclusive `ai.lock` so they do not compete for the same low-power CPU at the same time.

## Design rationale

### Why PaddleOCR?

Paperless/Tesseract remains useful for normal Paperless ingestion, but on the scans that motivated this project its text was often not clean enough as input for a small local LLM. Scan-like pages are therefore selectively reprocessed with PaddleOCR.

Native digital PDF text is kept because OCRing already-good text adds CPU cost and can reduce quality.

### Why one metadata request?

The reference system is an Intel Core i3-8100 without a GPU. Repeating prompt processing for title, tags, type, date and correspondent made per-field LLM workflows too slow in practice.

The main stage therefore returns all normal metadata in one structured request constrained by the current Paperless taxonomy.

### Why a separate correspondent fallback?

The main request should stay constrained to existing values. Only when it cannot resolve a correspondent does a second, narrow prompt get permission to return a free-text name.

An exact existing match can be applied. A genuinely new name becomes a review candidate and is never auto-created.

### Why not just use Paperless native AI?

Paperless native AI is a general suggestion feature. This project is built as an automatic queue-driven pipeline with selective OCR, constrained values and serialized resource-heavy work.

### Why no chat, RAG or semantic search?

They are useful features, but they are outside this project's goal. The target is reliable OCR plus automatic metadata classification on modest local hardware, without turning the app into a general document-AI platform.

## Configuration and state

Deployment owns secrets and Docker-level settings. Prompt Studio owns normal runtime settings and both LLM-stage configurations.

Persistent state lives below one `APP_DATA_DIR`:

```text
config/        app and prompt configuration/history
core/          result and open review records
ocr/           PaddleOCR cache/temp state
coordination/  shared ai.lock
```

## Suggestion bridge identity

For Paperless-ngx 3.0.5, open correspondent review records are matched primarily by a SHA-256 signature of the normalized document content used by Paperless' no-RAG AI classifier. Ambiguous matches fail closed.

The legacy short-prefix signature remains only for migrated older records. Filename matching is deliberately not used because Paperless' internal model filename and normal REST filename fields are not equivalent.
