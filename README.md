> [!NOTE]
> This project has been entirely vibe-coded. It works in my setup, but it has not been thoroughly reviewed or tested. Expect bugs and use it at your own discretion.

# paperless-local-ai

**Improved OCR with PaddleOCR and efficient local-LLM metadata automation for Paperless-ngx — designed for modest CPU-only hardware.**

`paperless-local-ai` uses **PaddleOCR instead of Tesseract** for scanned pages that need OCR and automatically assigns title, document type, date, tags and correspondent with a local Ollama model. It integrates into Paperless' existing OCRmyPDF import path, so Paperless remains the document system of record.

Normal metadata classification is handled in **one structured LLM request per document**. An optional second, narrowly scoped correspondent request runs only when the main classification cannot resolve an existing sender.

Reference system: **Intel Core i3-8100 · 4 cores / 4 threads · 16 GB RAM · no GPU · qwen3.5:4b**

## Highlights

- **Improved scan OCR with PaddleOCR** — PP-OCRv6 Medium handles OCR inference for scanned pages instead of Tesseract.
- **One LLM request for normal metadata** — title, document type, date, tags and an existing correspondent are returned together instead of processing the full document separately for every field.
- **CPU-optimized OCR** — PaddleX HPI and OpenVINO accelerate PP-OCRv6 on CPU, with a persistent inference cache and bounded thread usage.
- **Resource-aware execution** — PaddleOCR and Ollama inference are serialized so they do not compete for the same CPU and RAM budget.
- **Paperless-native integration** — OCR runs inside the normal OCRmyPDF import path, searchable archive/PDF-A generation stays with Paperless, and the uploaded original is preserved.
- **Focused correspondent fallback** — a second LLM request is used only when the main request cannot match an existing correspondent; genuinely new senders stay behind human review.
- **Control Center** — configure connections, workflow tags, OCR settings, prompts, model parameters, Dry Run and configuration history from one UI.

## How it fits into Paperless

During import, Paperless/OCRmyPDF decides whether a page needs OCR. Native-text pages stay on Paperless' normal text path. When OCR is required, the included OCRmyPDF plugin sends the rasterized page to the local `ocr-service`, where PaddleOCR runs PP-OCRv6 and returns OCRmyPDF's native `OcrElement` tree.

Tesseract is not used for OCR inference on pages handled by the plugin.

After the document has been added, a normal Paperless **Document Added** workflow assigns the `LLM` queue tag. The metadata worker then classifies the completed Paperless document.

<p align="center">
  <img src="images/paperless-flow.svg" alt="paperless-local-ai workflow" width="65%">
</p>

Paperless remains the document system of record throughout:

- the uploaded **original is preserved**;
- OCRmyPDF creates the searchable archive/PDF-A representation;
- Paperless stores the extracted OCR text;
- `paperless-local-ai` writes metadata back to the same Paperless document.

OCR runs during Paperless import; no separate OCR queue tag is required.

## PaddleOCR and CPU performance

The OCR service uses:

- PaddlePaddle `3.2.2`;
- PaddleOCR `3.7.0`;
- PaddleX `3.7.2`;
- **PP-OCRv6 Medium** detection and recognition models;
- PaddleX HPI with an OpenVINO CPU backend;
- a persistent PaddleX/OpenVINO cache;
- a short warm session so multi-page documents do not initialize Paddle for every page;
- the same exclusive AI resource lock used by the metadata worker.

The default deployment is tuned for **4 CPU threads, 7 GiB RAM and a 5-second OCR idle timeout**. These are reference settings, not universal minimums.

On the reference i3-8100 system, warm PP-OCRv6 inference for a 300-DPI page measured:

| Runtime | Approx. inference time |
|---|---:|
| Standard Paddle runtime | **15.8 s** |
| HPI / OpenVINO | **10.7 s** |

That is roughly a **32% reduction in warm OCR inference time**. Complete live OCR for a cached page is typically around **15–25 seconds**, depending on surrounding OCRmyPDF/PDF processing.

The first run on a fresh HPI/OpenVINO cache can take substantially longer while optimized inference artifacts are prepared. After the configured idle window, the Paddle subprocess is torn down so its memory is returned to the system.

## Metadata automation

The main classifier processes the document once and returns a structured result containing:

- title;
- document type;
- date;
- content tags;
- an existing correspondent.

This avoids sending the full document through the LLM again for each metadata field.

If the main request cannot match an existing correspondent and the optional fallback is enabled, a **separate correspondent-only request** runs with its own prompt and model settings. The configured model stays loaded across the main request and fallback when both are needed, then is explicitly unloaded.

### Correspondents

The primary classification is constrained to correspondents already present in Paperless.

The optional fallback can then:

- apply an exact existing correspondent automatically;
- propose a genuinely new sender through Paperless' native suggestion/review flow;
- leave the correspondent empty when no reliable sender can be determined.

New correspondents are never auto-created.

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

## Reference system and compatibility

**Intel Core i3-8100 · 16 GB RAM · no GPU · qwen3.5:4b**

The integration path has been validated end-to-end with a two-page scanned PDF: Paperless API upload → OCRmyPDF → PaddleOCR / PP-OCRv6 / OpenVINO → searchable PDF/A-2b → LLM metadata write-back → Inbox, while preserving the original byte-for-byte and preventing Paddle/Ollama overlap.

Tested reference: **Paperless-ngx 3.0.5**, **OCRmyPDF 17.4.2**, **TrueNAS SCALE 25.10.6** and **qwen3.5:4b**. See [Compatibility](docs/compatibility.md) for the exact scope.

## Requirements

Paperless-ngx · Ollama · Docker Compose or TrueNAS SCALE · linux/amd64

## Install

Choose one deployment guide:

- [Docker Compose](docs/installation.md)
- [TrueNAS SCALE](docs/truenas.md)

Then complete the required [Paperless integration](docs/paperless-setup.md) and review [Configuration](docs/configuration.md).

More: [Troubleshooting](docs/troubleshooting.md) · [Compatibility](docs/compatibility.md) · [Architecture](docs/architecture.md)

## Security

The Control Center has no built-in authentication. Keep it on localhost or a trusted network.

The OCR endpoint is authenticated with a separate shared token. Do not expose it directly to the public Internet.

## License

MIT for this repository's source code. Third-party components retain their own licenses; see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
