> [!NOTE]
> This project has been entirely vibe-coded. It works in my setup, but it has not been thoroughly reviewed or tested. Expect bugs and use it at your own discretion.

# paperless-local-ai

**Improved OCR and automatic local-LLM metadata assignment for Paperless-ngx — built for modest CPU-only hardware.**

`paperless-local-ai` adds two focused capabilities to Paperless-ngx:

- **PaddleOCR inside Paperless' normal OCRmyPDF import path**, producing searchable archive PDFs while Paperless keeps the original document;
- **automatic local-LLM metadata classification** for title, document type, date, tags and correspondent.

The normal metadata classification uses one structured LLM request. If that request cannot match an existing correspondent, an optional second sender-identification stage can match an existing correspondent or propose a genuinely new one through Paperless' native suggestion/review flow.

## How it fits into Paperless

During import, Paperless/OCRmyPDF decides whether a page needs OCR. When OCR is needed, the included OCRmyPDF plugin streams the rasterized page to the local `ocr-service`, which runs PP-OCRv6 and returns OCRmyPDF's native `OcrElement` tree.

After the document has been added, a normal Paperless **Document Added** workflow assigns the `LLM` queue tag. The metadata worker then classifies the completed Paperless document.

<p align="center">
  <img src="images/paperless-flow.svg" alt="paperless-local-ai workflow" width="65%">
</p>

Paperless remains the document system of record throughout:

- the uploaded **original is preserved**;
- OCRmyPDF creates the searchable archive/PDF-A representation;
- Paperless stores the extracted OCR text;
- `paperless-local-ai` writes metadata back to the same Paperless document.

Native-text PDFs stay on Paperless/OCRmyPDF's normal text path. There is no separate OCR queue tag in `paperless-local-ai` 0.2.0.

### Correspondents

The primary classification first tries to match one of the correspondents already present in Paperless.

If it returns no correspondent and the optional fallback is enabled, a **separate sender-identification LLM stage** runs with its own prompt and model settings.

- Existing correspondent → applied automatically.
- Genuinely new sender → proposed through Paperless' native suggestion/review flow.
- No reliable sender → correspondent remains empty.

New correspondents are never auto-created.

## Why this project?

The project started with local document AI on modest CPU-only hardware.

Two bottlenecks mattered most:

- **OCR quality:** PaddleOCR produced cleaner scan text than the Tesseract results that motivated the project.
- **Inference time:** one structured metadata request is substantially cheaper than repeating the full document context once per metadata field.

The scope stays deliberately narrow: **OCR and automatic metadata assignment**. Document chat, RAG and semantic search are intentionally outside the project.

## OCR runtime

The OCR service uses:

- PaddlePaddle `3.2.2`;
- PaddleOCR `3.7.0`;
- PaddleX `3.7.2`;
- **PP-OCRv6 Medium** detection and recognition models;
- PaddleX HPI with an OpenVINO CPU backend;
- a persistent PaddleX/OpenVINO cache;
- a short warm session, then full Paddle process teardown;
- the same exclusive `ai.lock` used by the metadata worker.

The default deployment is tuned for **4 CPU threads, 7 GiB RAM and a 5-second OCR idle timeout**. Those are reference limits, not universal minimums.

On the reference i3-8100 system, a cached 300-DPI page is typically around 15 seconds. First-time HPI/OpenVINO engine preparation can take substantially longer.

## Control Center

The Control Center configures normal app behavior:

- Paperless and Ollama connections;
- LLM queue/error/review tags;
- OCR language/version/device;
- polling and Dry Run;
- Classification prompt/model settings;
- optional Correspondent fallback.

Prompts and model settings can be previewed and tested against an existing Paperless document without modifying that document. Saved configurations are versioned and can be restored.

![paperless-local-ai Control Center](images/control-center-screenshot.png)

## Reference system

**Intel Core i3-8100 · 16 GB RAM · no GPU · qwen3.5:4b**

The 0.2.0 integration path was validated end-to-end with a two-page scanned PDF: Paperless API upload → OCRmyPDF → PP-OCRv6/OpenVINO → searchable PDF/A-2b → LLM metadata write-back → Inbox, while preserving the original byte-for-byte and preventing Paddle/Ollama overlap.

## Requirements

Paperless-ngx · Ollama · Docker Compose or TrueNAS SCALE · linux/amd64

Tested reference: **Paperless-ngx 3.0.5**, **OCRmyPDF 17.4.2**, **TrueNAS SCALE 25.10.6** and **qwen3.5:4b**. See [Compatibility](docs/compatibility.md) for the exact scope.

## Install

Choose one deployment guide:

- [Docker Compose](docs/installation.md)
- [TrueNAS SCALE](docs/truenas.md)

Then complete the required [Paperless integration](docs/paperless-setup.md) and review [Configuration](docs/configuration.md).

More: [Troubleshooting](docs/troubleshooting.md) · [Updating](docs/upgrading.md) · [Compatibility](docs/compatibility.md) · [Architecture](docs/architecture.md)

## Security

The Control Center has no built-in authentication. Keep it on localhost or a trusted network.

The OCR endpoint is authenticated with a separate shared token. Do not expose it directly to the public Internet.

## License

MIT for this repository's source code. Third-party components retain their own licenses; see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
