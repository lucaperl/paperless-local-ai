# Architecture

## Design goals

1. Keep Paperless-ngx stock and updateable.
2. Make expensive processing CPU-first and serialized for small homeservers.
3. OCR only pages that need it.
4. Keep metadata classification text-only.
5. Never auto-create a genuinely new correspondent.
6. Keep code in Git/images and user configuration in one persistent app directory.
7. Give every setting one obvious owner.

## Pipeline

```text
Paperless-ngx
   |
   | workflow: add OCR queue tag
   v
ocr-worker ------------------------------+
   |                                      |
   | native / OCR_PAGE / VERIFY           | shared exclusive ai.lock
   |                                      |
   +--> update content if justified       |
   +--> add LLM queue tag                 |
                                          |
metadata-worker --------------------------+
   |
   +--> main structured classification
   |      title / type / correspondent / tags / created
   |
   +--> if correspondent == "" and fallback enabled:
   |      second correspondent-only Ollama request
   |
   +--> existing exact name: apply
   +--> new name: persist review candidate
   v
Paperless metadata + human review

Paperless native AI-suggestions request
   -> suggestion-bridge
   -> uniquely match persistent review record
   -> fetch classic /suggestions/ from Paperless
   -> preserve classic suggestions
   -> append only a still-open new correspondent candidate
   -> return Ollama-compatible structured response
```

## Containers

The public app uses two images but four services:

- `paperless-local-ai-ocr`: PaddlePaddle + PaddleOCR + PyMuPDF + OCR worker.
- `paperless-local-ai-core`: small Python image reused for metadata worker, Studio and suggestion bridge.

Ollama is external by design.

## Configuration ownership

### Deployment configuration: `.env`

Only values that Docker must know before a process starts, plus secrets:

- `PAPERLESS_TOKEN`
- image prefix/version
- `APP_DATA_DIR`
- host bind addresses/ports
- CPU, RAM and shared-memory limits

### Shared runtime configuration: `/config/app-config.json`

Owned by **Studio -> App-Einstellungen**:

- Paperless URL
- Ollama URL
- OCR/LLM/review tag names
- extra taxonomy-excluded tags
- OCR language/version/device
- worker poll interval
- review cleanup interval
- dry-run

Workers reload this configuration while running. No container restart is required for these values.

### Stage-specific configuration

`prompt-config.json` and `correspondent-suggestion.json` intentionally remain separate because they are two independently testable/versioned LLM programs. Their model/request parameters live with their prompts in the same Studio section.

### Internal constants

Protocol/body/cache/safety constants that ordinary users should not tune are not exposed as fake settings. If a value has no supported operational use case, it stays code.

## Persistent state

```text
APP_DATA_DIR/
├── config/       shared app + stage configs/history
├── core/         results + correspondent review records
├── ocr/          Paddle cache/temp state
└── coordination/ shared ai.lock
```

## Failure behavior

- OCR processing error: OCR queue tag is removed and OCR error tag is set.
- LLM processing error: LLM queue tag is removed and LLM error tag is set.
- Bridge cannot uniquely map a Paperless request: no new correspondent suggestion is returned.
- New correspondent: never created automatically.

### Suggestion identity

The bridge uses review-record schema v4. Its primary identity is a SHA-256 signature of the normalized content that Paperless 3.0.5 feeds into the no-RAG AI classifier (`document.content[:4000]` before Paperless token-budget truncation). The old 96-word content signature remains only as a compatibility fallback for migrated v2/v3 records. If an old short-prefix collision occurs, the bridge compares the prompt-content signature against the current Paperless API content for each candidate; unresolved ambiguity fails closed.

Filename matching is deliberately not used for identity. Paperless 3.0.5 places the model's internal `Document.filename` (current storage path) in its AI prompt, while the normal REST serializer exposes `original_file_name` and a generated `archived_file_name`, not that internal `filename` value. Treating those fields as equivalent would be unsafe.
