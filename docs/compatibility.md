# Compatibility

Compatibility claims are intentionally narrow: an environment is listed as tested only after integration testing.

## Tested reference environment

| Component | Tested reference |
|---|---|
| Paperless-ngx | **3.1.0** |
| OCRmyPDF inside Paperless | **17.7.1** |
| Deployment | Docker Compose v2 / TrueNAS Custom App |
| TrueNAS SCALE | **25.10.6** |
| Platform | **linux/amd64** |
| PaddlePaddle | **3.2.2** |
| PaddleOCR | **3.7.0** |
| PaddleX | **3.7.2** |
| OCR model | **PP-OCRv6 Medium** |
| CPU acceleration | **PaddleX HPI / OpenVINO** |
| Ollama reference | **0.32.11** |
| Ollama reference model | **qwen3.5:4b** |
| scikit-learn | **1.9.0** |

## Paperless / OCRmyPDF versions

The OCR integration uses OCRmyPDF's plugin API and is version-sensitive.

The end-to-end tested reference remains OCRmyPDF **17.7.1** with Paperless-ngx **3.1.0**. The native plugin contract has additionally been source-checked and regression-tested against OCRmyPDF **17.11.0**, the version locked by Paperless-ngx **3.2.0**. Both expose the same `OcrEngine.generate_ocr()` / `OcrElement` interface used by PLAI.

### OCRmyPDF 17.7.1 / 17.11.0 native fpdf2 DPI workaround

OCRmyPDF 17.7.1 and 17.11.0 can report a zero `PdfInfo` DPI to their native `generate_ocr()` / fpdf2 renderer for some hybrid or vector PDFs even though the raster sent to PaddleOCR has a valid DPI. PaddleOCR succeeds, but unpatched fpdf2 rendering then fails while converting pixel geometry to PDF points.

`src/ocr/ocrmypdf_plai.py` therefore installs an idempotent compatibility shim only for the explicitly supported **17.7.1** and **17.11.0** contracts through OCRmyPDF's official `initialize()` plugin hook. It does not modify installed OCRmyPDF files.

Renderer DPI is selected in this order:

1. DPI carried by the returned OCR `OcrElement`;
2. usable PDFInfo DPI;
3. OCRmyPDF `VECTOR_PAGE_DPI`.

The first choice is important because `filter_ocr_image()` may downsample the OCR-only raster and adjusts its DPI proportionally; using that value preserves the physical text-layer geometry.

**Removal/update condition:** do not broaden this workaround to another OCRmyPDF version just because the dependency version changed. First inspect the target native `generate_ocr()` / fpdf2 graft path, determine whether the zero-DPI case is fixed upstream, run the real-version GitHub compatibility matrix plus the unit regressions in `tests/test_ocr_plugin.py`, and run one real Paperless end-to-end hybrid-PDF reprocess with PaddleOCR. If a newer OCRmyPDF version handles the case itself, do not carry the shim forward to that version.

A newer Paperless/OCRmyPDF release should be treated as unverified until the plugin contract is checked.

The new-correspondent suggestion bridge is also version-sensitive because it depends on Paperless' AI classification-suggestion request shape. It supports the list-based taxonomy response contract used by Paperless-ngx **3.0.5** and the taxonomy-choice schema used by Paperless-ngx **3.1.x / 3.2.0**. Paperless-ngx 3.2.0 always wraps classification prompts with `Additional context from similar documents`, using a Tantivy fallback even without an embedding backend. The primary Rust bridge and retained Python compatibility bridge read Paperless' authenticated `X-Version` response header to select the known prompt shape: 3.0/3.1 keep the content unchanged, while the source-checked 3.2.0 contract requires exactly one generated context wrapper and strips it before review-record identity matching. Missing or repeated 3.2 wrapper markers fail closed so untrusted document/context text cannot choose the split point. Other Paperless version families remain unsupported until their prompt contract is checked. Response shape is still derived from each Ollama request schema instead of hardcoding a Paperless version.

The tested reference environment above remains the end-to-end claim for Paperless-ngx **3.1.0** and OCRmyPDF **17.7.1**. Paperless-ngx **3.2.0** / OCRmyPDF **17.11.0** is source-checked and covered by the repository regression/CI contracts, but should not replace the tested-reference row until the production hybrid-PDF and suggestion-bridge smoke tests have been completed.

Paperless 2.x is not a supported target for this OCR/plugin path.

## RAG chat compatibility boundary

The PLAI RAG backend uses the documented Paperless REST API v10 for document synchronization and does not read Paperless' internal LlamaIndex/vector-store database. The Paperless-side UI integration is deliberately fail-open and does not patch Paperless source files. Its primary navbar placement hook (`#chatDropdown`) is present in Paperless-ngx 3.1.2, 3.1.3 and 3.2.0 source; fallback placement avoids making that private DOM selector a hard runtime dependency. Paperless 3.2.0 retains API v10, the document detail routes used for source links/context detection, the cookie-prefix CSRF convention and `PAPERLESS_APPS` loading used by the integration. This is a source-level compatibility check, not an expanded end-to-end tested-version claim.

The native Paperless document-chat behavior described in [Architecture](architecture.md#native-paperless-ai-and-plai) was source-checked in Paperless-ngx **3.1.0, 3.1.1, 3.1.2, 3.1.3 and 3.2.0**. This source check does not expand the end-to-end tested reference beyond the table above.

RAG browser writes use Paperless session authentication and explicit CSRF protection. The first implementation is intentionally superuser-only until permission-aware retrieval is separately designed and tested.

## OCR models and languages

The tested reference runtime uses PaddleOCR with **PP-OCRv6 Medium** detection and recognition models. The Control Center also exposes matching **Small** and **Tiny** PP-OCRv6 profiles. Medium is the default and the reference profile for published CPU measurements.

PP-OCRv6 Tiny does not support Japanese; configuration validation rejects that combination.

OCR language is configured separately. The service accepts common aliases from Paperless/Tesseract and maps them to the configured PP-OCRv6 language code, but rejects an actual language mismatch.

## LLM models, tagging and prompts

Classification uses one installed Ollama model selected in the Control Center. Title, document type, date and sender/issuer use one structured request.

Content tags use either **Hybrid tagging** or **LLM direct**. Hybrid tagging uses local scikit-learn TF-IDF/nearest-neighbor retrieval over reviewed Paperless documents and is the recommended strategy for the `qwen3.5:4b` reference model. LLM direct is intended for models that can map document semantics to the user's taxonomy reliably enough without retrieved examples.

System, Base classification and Tagging prompts are editable. English and German presets are included for all three components, and Tag Guidance is configurable per Paperless content tag.

ARM64 is not claimed as supported.
