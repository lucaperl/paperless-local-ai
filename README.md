> [!NOTE]
> This project has been entirely vibe-coded. It works in my setup, but it has not been thoroughly reviewed or tested. Expect bugs and use it at your own discretion.

# paperless-local-ai

**Improved OCR with PaddleOCR and efficient local-LLM metadata automation for Paperless-ngx — designed for modest CPU-only hardware.**

`paperless-local-ai` uses **PaddleOCR instead of Tesseract** for scanned pages that need OCR and automatically writes Paperless metadata with a local Ollama model. It integrates into Paperless' existing OCRmyPDF import path, so Paperless remains the document system of record.

Normal metadata extraction is handled in **one structured LLM request per document**. Title, document type, date and sender/issuer are extracted together. Content tags use either **History-assisted tagging** (the default) or **LLM only**. The sender is resolved locally against existing Paperless correspondents; a genuinely new sender can be exposed through **Paperless Document Suggestions** without a second LLM request and is never auto-created.

## Highlights

- **Improved scan OCR with PaddleOCR** — PP-OCRv6 Medium is the quality-focused default, with Small and Tiny profiles selectable when lower inference cost matters; bounded automatic retries recover from transient OCR worker/service failures.
- **History-assisted tagging** — reviewed Paperless documents provide a high-confidence path for recurring document types; unfamiliar documents fall back to the LLM with relevant reviewed examples.
- **LLM-only tagging remains available** — useful for larger or more capable models that can map document semantics to a personal taxonomy reliably enough on their own.
- **One normal LLM request per document** — title, document type, date, sender/issuer and, when required, tags are produced together as structured JSON.
- **Paperless-native correspondent review** — the LLM extracts the actual sender once; local matching applies a safe existing match or exposes a new name through Document Suggestions.
- **Designed for CPU-only systems** — OCR and LLM inference are serialized to avoid simultaneous heavy CPU/RAM use.
- **Control Center** — configure connections, workflow tags, OCR, prompts, model settings, tagging strategy, per-tag guidance, history health, Dry Run and configuration history from one UI.

## Why this architecture

`paperless-local-ai` is designed around three priorities: **OCR quality, practical local inference on modest CPU-only hardware, and consistent automation inside Paperless.**

**Better OCR before the LLM.** Metadata classification can only be as reliable as the text it receives. The project therefore uses PaddleOCR with PP-OCRv6, defaulting to the quality-focused Medium profile. Small and Tiny can be selected when lower inference cost matters more than maximum recognition quality, while HPI/OpenVINO accelerates the selected profile on CPU.

**One LLM request, but not one model decision for everything.** Title, document type, date and sender extraction benefit from semantic understanding and are produced together in one structured request. Direct tag selection is different: it requires mapping that semantic understanding to a user's personal filing policy. In the reference archive, **4B-class local models were not consistently reliable enough to apply that personal taxonomy across recurring and semantically similar document types**. Relevant reviewed examples improved the result substantially, while additional prompt rules eventually produced diminishing gains and regressions.

The default therefore uses **History-assisted tagging**: only strong, internally supported matches against reviewed Paperless documents may reuse an established tag. Everything unfamiliar falls back to the configured LLM with relevant reviewed examples and optional per-tag guidance. This behavior is deliberately conservative. **LLM only** remains available for users running larger or more capable models.

See [Tagging](docs/tagging.md) for the decision logic, evaluation and limitations.

**Sender extraction is resolved locally.** The main LLM call returns the sender/issuer as free text. The application then performs conservative local matching against current Paperless correspondents. A safe match is applied; a plausible new name is sent to Paperless Suggestions for review. This avoids a second correspondent-only inference pass.

**Resource-aware execution.** PaddleOCR/OpenVINO and Ollama inference are serialized through a shared resource lock. OCR sessions are reused briefly across consecutive pages, and heavy model processes are released again when no longer needed.

## Reference performance

**Intel Core i3-8100 · 4 cores / 4 threads · 16 GB RAM · no GPU · qwen3.5:4b Q4_K_M · PP-OCRv6 Medium / HPI / OpenVINO**

| Component | Measured time |
|---|---:|
| First scanned page after OCR idle | **23.6 s** |
| Additional page in the same warm OCR session | **17.6 s/page** |
| Compact one-call metadata request | **~80 s/document** |
| History-assisted LLM fallback in the reference evaluation | **~174 s/document average** |

The LLM fallback is slower because relevant reviewed examples add prompt context. A high-confidence history tag does not need those examples. These measurements are reference points for one CPU-only system, not performance guarantees.

## RAM usage and tuning

The main memory consumers are PaddleOCR during OCR and the Ollama model during metadata classification. They are serialized, so their heavy peaks normally do not overlap.

Measured on the reference setup:

| Workload | Configuration | Measured peak |
|---|---|---:|
| OCR | PP-OCRv6 Medium · 3000 px | **~4.4–4.7 GiB** |
| OCR | PP-OCRv6 Medium · 3200 px | **~4.9–5.1 GiB** |
| OCR | PP-OCRv6 Medium · 4000 px | **~6.5 GiB** |
| Metadata | qwen3.5:4b Q4_K_M · 4k context | **~3.6 GiB** |
| Metadata | qwen3.5:4b Q4_K_M · 8k context | **~3.8 GiB** |
| Metadata | qwen3.5:4b Q4_K_M · 16k context | **~4.2 GiB** |

If RAM is limited, lower **Maximum OCR image dimension** first for OCR pressure and reduce the **Context window** for LLM pressure. See [Configuration](docs/configuration.md#ram-usage-and-tuning).

## How it fits into Paperless

During import, Paperless/OCRmyPDF decides whether a page needs OCR. Native-text pages stay on Paperless' normal text path. When OCR is required, the included OCRmyPDF plugin sends the rasterized page to the local `ocr-service`, where PaddleOCR runs PP-OCRv6 and returns OCRmyPDF's native `OcrElement` tree.

After the document has been added, a normal Paperless **Document Added** workflow assigns the classification queue tag. The metadata worker then routes tagging, performs one structured Ollama request, resolves the extracted sender locally and writes the validated metadata back to Paperless.

<p align="center">
  <img src="images/paperless-flow.svg" alt="paperless-local-ai workflow" width="65%">
</p>

Paperless remains the document system of record throughout:

- the uploaded **original is preserved**;
- OCRmyPDF creates the searchable archive/PDF-A representation;
- Paperless stores the extracted OCR text and reviewed metadata;
- `paperless-local-ai` reads reviewed Paperless documents for History-assisted tagging and writes new metadata back to the same document.

## Tagging

Two strategies are available in **Control Center → Classification → Tagging**:

- **History-assisted (Recommended for small models):** reviewed documents are searched for a high-confidence historical match. A strong match reuses the established tag; otherwise the LLM decides using current tag guidance plus relevant reviewed examples.
- **LLM only (For more capable models):** the configured model decides tags directly for every document. History is not used for routing or examples.

The Control Center also shows History health, per-tag coverage, a retrospective reuse estimate and **Potential tag inconsistencies** — groups of similar reviewed documents that currently use different tag assignments. These are review hints only and are never changed automatically.

[Read the full tagging design and evaluation](docs/tagging.md).

## Correspondents

The primary structured request extracts the actual sender or issuer as free text. The application then:

- applies a normalized exact or deliberately conservative strong match to an existing Paperless correspondent;
- exposes a plausible new sender through **Paperless Document Suggestions**;
- leaves the correspondent empty when no reliable sender was extracted.

New correspondents are never auto-created. There is no separate correspondent-only LLM stage.

## Control Center

The Control Center configures normal app behavior:

- Paperless and Ollama connections;
- classification queue/error/review tags;
- OCR language, PaddleOCR model, temporary OCR image limit, retry schedule and recovery status;
- metadata Dry run and worker timing;
- classification prompts and model settings;
- **Tagging strategy**, History health and per-tag LLM guidance.

Prompts and model settings can be previewed and tested against an existing Paperless document without modifying that document. Saved configurations are versioned and can be restored.


## Requirements

Paperless-ngx · Ollama · Docker Compose or TrueNAS SCALE · linux/amd64

Tested reference: **Paperless-ngx 3.0.5 · OCRmyPDF 17.4.2 · TrueNAS SCALE 25.10.6 · Ollama 0.32.11**. See [Compatibility](docs/compatibility.md) for the exact tested scope.

## Install

Choose one deployment guide:

- [Docker Compose](docs/installation.md)
- [TrueNAS SCALE](docs/truenas.md)

Then complete the required [Paperless integration](docs/paperless-setup.md) and review [Configuration](docs/configuration.md).

More: [Tagging](docs/tagging.md) · [Troubleshooting](docs/troubleshooting.md) · [Compatibility](docs/compatibility.md) · [Architecture](docs/architecture.md)

## Security

The Control Center has no built-in authentication. Keep it on localhost or a trusted network.

The OCR endpoint is authenticated with a separate shared token. Do not expose it directly to the public Internet.

## License

MIT for this repository's source code. Third-party components retain their own licenses; see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
