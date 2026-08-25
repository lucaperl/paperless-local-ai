> [!NOTE]
> This project has been entirely vibe-coded. It works in my setup, but it has not been thoroughly reviewed or tested. Expect bugs and use it at your own discretion.

# paperless-local-ai

**Improved OCR with PaddleOCR and efficient local-LLM metadata automation for Paperless-ngx — designed for modest CPU-only hardware.**

`paperless-local-ai` uses **PaddleOCR instead of Tesseract** for scanned pages that need OCR and applies Paperless metadata with a local Ollama model. It integrates into Paperless' OCRmyPDF import path, so Paperless stays the document system of record.

Title, document type, date and sender/issuer are extracted in one structured LLM request. Content tags can use **Hybrid tagging**, which combines reviewed-document similarity with an LLM fallback, or **LLM direct**, where the model selects tags for every document. Sender names are resolved locally against existing Paperless correspondents. If the optional Paperless Suggestions integration is configured, plausible new names are exposed there for review; otherwise unmatched names remain for manual review. New correspondents are never auto-created.

## Highlights

- **Improved scan OCR with PaddleOCR** — PP-OCRv6 Medium is the quality-focused default, with Small and Tiny profiles when lower inference cost matters.
- **Hybrid tagging** — compares new documents with reviewed Paperless documents, reuses a tag only behind a strict similarity/agreement gate, and sends uncertain cases to the LLM with relevant reviewed examples and optional Tag Guidance.
- **LLM direct** — lets a sufficiently capable local model choose tags directly from the Paperless taxonomy.
- **Editable prompt composition** — System, Base classification and Tagging prompts are all editable. The Tagging prompt is sent only when the LLM actually has to choose tags.
- **One LLM request per document** — title, type, date and sender/issuer are produced together; tags are included in the same request only on an LLM tag route.
- **Optional Paperless-native correspondent review** — local resolution applies safe existing matches; the optional Suggestions integration can expose plausible new senders through Document Suggestions.
- **Designed for CPU-only systems** — OCR, Hybrid-history work and LLM inference are serialized; heavyweight OCR/history/model runtimes are released after use.
- **Control Center** — configure connections, workflow tags, OCR, prompts, model settings, tagging strategy, per-tag guidance, history health, Dry Run and configuration history from one UI.

## Why this architecture

`paperless-local-ai` is built around three priorities: **OCR quality, practical local inference on modest hardware, and predictable automation inside Paperless.**

**Better OCR before classification.** Metadata extraction can only be as reliable as the text it receives. PP-OCRv6 Medium is the quality-focused default; Small and Tiny trade recognition quality for lower inference cost. HPI/OpenVINO accelerates the selected profile on CPU.

**Semantic metadata stays with the LLM.** Title, document type, date and sender/issuer benefit directly from document understanding, so they are produced together by the configured Ollama model.

**Tags use an explicit Hybrid route by default.** Compact local models can understand what a document is about while still applying a personal filing taxonomy inconsistently. Hybrid tagging first compares the document with already reviewed Paperless documents. A tag is reused only when the closest match is sufficiently similar and nearby reviewed examples agree strongly enough. If that evidence is not strong enough, the LLM chooses the tags using the current Tag Guidance and relevant reviewed examples.

Paperless itself already contains an automatic classifier that learns from existing documents. The Hybrid route serves a different integration goal: it exposes an explicit evidence gate before reuse, can hand uncertain cases to the local LLM, and uses the same retrieved documents as examples for that fallback. It does **not** claim to be universally more accurate than Paperless' classifier. See [Tagging](docs/tagging.md#paperless-native-classifier-vs-hybrid-tagging) for the technical comparison.

**Sender extraction is followed by conservative local resolution.** The LLM returns the actual sender/issuer as free text. Normalized exact matches and deliberately strong unambiguous fuzzy matches can resolve to an existing Paperless correspondent. Other plausible names can be exposed through Document Suggestions when the optional bridge integration is configured; otherwise they remain unresolved for manual review.

**Resource-aware execution.** The persistent `core-service` runtime is one Rust process. PaddleOCR/OpenVINO, on-demand Hybrid-history work and Ollama inference share one resource lock. The scientific Hybrid-history stack runs only in a disposable Python subprocess; OCR sessions and interactive history lookups can be reused briefly, while heavyweight subprocesses and the Ollama model are released after use.

## Reference performance

Measured on an **Intel Core i3-8100 · 4 cores / 4 threads · 16 GB RAM · no GPU · qwen3.5:4b Q4_K_M · PP-OCRv6 Medium / HPI / OpenVINO**.

| Workload | Document size | Prompt size | Processing time | Peak RAM |
|---|---|---:|---:|---:|
| OCR · PP-OCRv6 Medium · 3000 px | per page | — | **~23 s/page** | **~4.3 GiB** |
| Metadata · qwen3.5:4b Q4_K_M | ~1–2 pages | ~1–4k tokens | **~40 s–2.5 min** | **~4.2 GiB** |
| Metadata · qwen3.5:4b Q4_K_M | ~3–4 pages | ~5–9k tokens | **~3–5.5 min** | **~4.2 GiB** |
| Metadata · qwen3.5:4b Q4_K_M | ~5–6 pages | ~9–12k tokens | **~5.5–7.5 min** | **~4.2 GiB** |

Page count is only a rough indication of metadata cost. Runtime primarily follows the number of prompt tokens actually processed. Hybrid matches tend toward the lower end because tagging context is omitted, while fallback requests also include the tag taxonomy, guidance and retrieved examples. A 7-page fallback with ~14k prompt tokens took ~8.7 minutes.

The **Context window** sets the maximum available context and affects RAM usage. It does not mean every request processes the full configured context. A larger context window allows larger prompts, however, and large prompts can substantially increase CPU inference time.

## RAM usage and tuning

The main memory consumers are PaddleOCR during OCR and the Ollama model during metadata classification. Hybrid-history TF-IDF/scikit-learn state is loaded only in an on-demand subprocess and released again after use. Heavy OCR, history and LLM work is serialized through the shared resource lock.

| Workload | Configuration | Measured peak |
|---|---|---:|
| OCR | PP-OCRv6 Medium · 3000 px | **~4.3 GiB** |
| OCR | PP-OCRv6 Medium · 3200 px | **~4.9–5.1 GiB** |
| OCR | PP-OCRv6 Medium · 4000 px | **~6.5 GiB** |
| Metadata | qwen3.5:4b Q4_K_M · 4k context | **~3.6 GiB** |
| Metadata | qwen3.5:4b Q4_K_M · 8k context | **~3.8 GiB** |
| Metadata | qwen3.5:4b Q4_K_M · 16k context | **~4.2 GiB** |

If RAM is limited, lower **Maximum OCR image side** first for OCR pressure and reduce the **Context window** for LLM pressure. See [Configuration](docs/configuration.md#ram-usage-and-tuning).

## How it fits into Paperless

During import, Paperless/OCRmyPDF decides whether a page needs OCR. Native-text pages are not sent to PaddleOCR. Pages requiring OCR are sent through the included OCRmyPDF plugin to the local PaddleOCR service, which returns OCRmyPDF-native `OcrElement` geometry.

After a document is added, a Paperless **Document Added** workflow assigns the classification queue tag. The metadata worker chooses the tag route, performs one structured Ollama request, resolves the extracted sender locally and writes validated metadata back to the same Paperless document.

The configured review tag can have any name. It stays on the document until human review is complete; removing it makes the document eligible for trusted Hybrid history once queue/error tags are also gone. The recommended Paperless setup marks the chosen review tag as an **Inbox tag** so Paperless adds it automatically during import.

For an exclusive paperless-local-ai metadata workflow, set Paperless **Matching algorithm** to **None** for the content tags, document types, correspondents and technical workflow/review tags managed by paperless-local-ai. See [Paperless setup](docs/paperless-setup.md) for the exact setup.

<p align="center">
  <img src="images/paperless-flow.svg" alt="paperless-local-ai workflow" width="65%">
</p>

Paperless stays the system of record:

- the uploaded **original is preserved**;
- OCRmyPDF creates the searchable archive/PDF-A representation;
- Paperless stores OCR text and reviewed metadata;
- Hybrid tagging reads reviewed Paperless documents and writes new metadata back to Paperless.

## Tagging

Two strategies are available under **Control Center → Classification → Tagging**:

**Hybrid tagging — Recommended for small models**
Compares documents with reviewed examples and reuses a tag only when similarity and neighbor agreement are strong. Otherwise the LLM decides using Tag Guidance and relevant examples. [How Hybrid tagging works](docs/tagging.md#hybrid-tagging).

**LLM direct — For more capable models**
The configured model selects tags for every document. Reviewed examples are not used for tag routing or prompt examples.

The Control Center also shows reviewed-history health, **Retrospective history reuse**, **History depth by tag**, and advisory **Potential tag inconsistencies**. [Read the full tagging design](docs/tagging.md).

## Prompt composition

Classification uses three editable prompt fields:

1. **System prompt** — global model behavior and security framing.
2. **Base classification prompt** — title, document type, sender/issuer, date and document text.
3. **Tagging prompt** — tag-selection instructions and placeholders for the current taxonomy, Tag Guidance and retrieved examples.

The Tagging prompt is appended only when the active route requires an LLM tag decision. On a confident Hybrid match it is omitted entirely, and the structured output schema contains no `tags` field. **Preview prompts** shows the exact messages and schema that would be sent.

## Correspondents

The structured metadata request extracts the actual sender/issuer as free text. Local resolution applies a safe existing match or leaves the field empty when no reliable existing correspondent can be resolved. If the optional suggestion bridge is configured in Paperless, a plausible unmatched sender can additionally appear in **Paperless Document Suggestions** for review. Without that integration, existing-correspondent matching still works and unmatched senders are handled manually during review.

## Control Center

The Control Center configures:

- Paperless and Ollama connections;
- classification queue/error/review tags;
- OCR language, PaddleOCR model, maximum OCR image side, retry schedule and recovery state;
- metadata Dry Run and worker timing;
- model settings and all three classification prompt components;
- **Hybrid tagging / LLM direct**, History health and per-tag Tag Guidance.

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
