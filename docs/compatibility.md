# Compatibility

Compatibility claims are intentionally narrow: an environment is listed as tested only after integration testing.

Supported Paperless-ngx range for the current release: **3.1.0–3.3.0**.

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

The end-to-end tested reference remains OCRmyPDF **17.7.1** with Paperless-ngx **3.1.0**. The native plugin contract has additionally been source-checked and regression-tested against OCRmyPDF **17.11.0** and **17.12.1**. Paperless-ngx **3.2.0** uses 17.11.0, while **3.2.1** and **3.3.0** use 17.12.1. All three OCRmyPDF versions expose the same `OcrEngine.generate_ocr()` / `OcrElement` interface used by PLAI.

### OCRmyPDF 17.7.1 / 17.11.0 / 17.12.1 native fpdf2 DPI workaround

OCRmyPDF 17.7.1, 17.11.0 and 17.12.1 can report a zero `PdfInfo` DPI to their native `generate_ocr()` / fpdf2 renderer for some hybrid or vector PDFs even though the raster sent to PaddleOCR has a valid DPI. PaddleOCR succeeds, but unpatched fpdf2 rendering then fails while converting pixel geometry to PDF points.

`src/ocr/ocrmypdf_plai.py` therefore installs an idempotent compatibility shim through OCRmyPDF's official `initialize()` plugin hook only after a runtime contract check confirms the private fpdf2 surface used by the workaround. The check requires the expected `OcrGrafter` renderer method, `Fpdf2ParsedPage` fields and a usable `VECTOR_PAGE_DPI`. It does not modify installed OCRmyPDF files.

Renderer DPI is selected in this order:

1. DPI carried by the returned OCR `OcrElement`;
2. usable PDFInfo DPI;
3. OCRmyPDF `VECTOR_PAGE_DPI`.

The first choice is important because `filter_ocr_image()` may downsample the OCR-only raster and adjusts its DPI proportionally; using that value preserves the physical text-layer geometry.

**Removal/update condition:** each new Paperless/OCRmyPDF release still requires an upstream source review. Inspect the target native `generate_ocr()` / fpdf2 graft path, determine whether the zero-DPI case is fixed upstream, add the validated OCRmyPDF version to the GitHub compatibility matrix, run the unit regressions in `tests/test_ocr_plugin.py`, and run one real Paperless hybrid/vector-PDF reprocess with PaddleOCR. The runtime contract check prevents the shim from being applied silently if the private surface changes; it is not a substitute for release review. If a newer OCRmyPDF version handles the case itself, remove the workaround when that becomes the supported baseline.

A newer Paperless/OCRmyPDF release should be treated as unverified until its relevant source changes and runtime behavior are checked.

The new-correspondent suggestion bridge is also version-sensitive because it depends on Paperless' AI classification-suggestion request shape. Its response-shape handling covers the list-based taxonomy contract used by Paperless-ngx **3.0.5** and the schema shapes reviewed in Paperless-ngx **3.1.x / 3.2.x / 3.3.0**. Prompt-identity compatibility is intentionally narrower: Paperless **3.0.x / 3.1.x** are covered only for the normal no-native-embedding classification path, where Paperless does not append generated similar-document context. A Paperless 3.1.x installation configured with Paperless' own `llm_embedding_backend` can use the RAG-context prompt and is not part of the bridge compatibility claim. PLAI's separate RAG index does not use that Paperless backend and is unaffected by this boundary.

Paperless-ngx **3.2.x** and **3.3.0** wrap classification prompts with `Additional context from similar documents`, using a Tantivy fallback even without an embedding backend. Source review confirmed that Paperless 3.3.0 keeps the same classifier and prompt templates as 3.2.1. The primary Rust bridge and retained Python compatibility bridge therefore treat Paperless **3.x from minor version 2 onward** as one prompt-contract family instead of maintaining a per-release allowlist. They read Paperless' authenticated `X-Version` response header to select the contract: 3.0/3.1 expect no generated wrapper, while 3.2+ requires exactly one generated context wrapper and strips it before review-record identity matching. Missing or repeated wrapper markers still fail closed so untrusted document/context text cannot choose the split point. Paperless 4.x remains unsupported until its prompt contract is checked. Future Paperless 3.x releases still require the normal source review before the documented supported range is extended.

The tested reference environment above remains the end-to-end claim for Paperless-ngx **3.1.0** and OCRmyPDF **17.7.1**. Paperless-ngx **3.3.0** keeps OCRmyPDF **17.12.1**, and its relevant AI classification prompt files, API v10 behavior and UI integration hooks were source-reviewed against 3.2.1. This does not replace the full end-to-end tested-reference row.

Paperless 2.x is not a supported target for this OCR/plugin path.

## RAG chat compatibility boundary

The PLAI RAG backend uses the documented Paperless REST API v10 for document synchronization and does not read Paperless' internal LlamaIndex/vector-store database. The Paperless-side UI integration is deliberately fail-open and does not patch Paperless source files. Its primary navbar placement hook (`#chatDropdown`) is present in Paperless-ngx 3.1.2, 3.1.3, 3.2.0, 3.2.1 and 3.3.0 source; fallback placement avoids making that private DOM selector a hard runtime dependency. Paperless 3.3.0 retains API v10, the document detail routes used for source links/context detection, the cookie-prefix CSRF convention and `PAPERLESS_APPS` loading used by the integration. This is a source-level compatibility check, not an expanded end-to-end tested-version claim.

The native Paperless document-chat behavior described in [Architecture](architecture.md#native-paperless-ai-and-plai) was source-checked in Paperless-ngx **3.1.0, 3.1.1, 3.1.2, 3.1.3, 3.2.0, 3.2.1 and 3.3.0**. This source check does not expand the end-to-end tested reference beyond the table above.

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
