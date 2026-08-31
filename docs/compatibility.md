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

The included plugin is verified against OCRmyPDF **17.7.1**, specifically the native `OcrEngine.generate_ocr()` / `OcrElement` interface used by Paperless-ngx **3.1.0**.

### OCRmyPDF 17.7.1 native fpdf2 DPI workaround

OCRmyPDF 17.7.1 can report a zero `PdfInfo` DPI to its native `generate_ocr()` / fpdf2 renderer for some hybrid or vector PDFs even though the raster sent to PaddleOCR has a valid DPI. PaddleOCR succeeds, but unpatched fpdf2 rendering then fails while converting pixel geometry to PDF points.

`src/ocr/ocrmypdf_plai.py` therefore installs a **17.7.1-only**, idempotent compatibility shim through OCRmyPDF's official `initialize()` plugin hook. It does not modify installed OCRmyPDF files.

Renderer DPI is selected in this order:

1. DPI carried by the returned OCR `OcrElement`;
2. usable PDFInfo DPI;
3. OCRmyPDF `VECTOR_PAGE_DPI`.

The first choice is important because `filter_ocr_image()` may downsample the OCR-only raster and adjusts its DPI proportionally; using that value preserves the physical text-layer geometry.

**Removal/update condition:** do not broaden this workaround to a newer OCRmyPDF version just because the dependency version changed. First inspect the newer native `generate_ocr()` / fpdf2 graft path, determine whether the zero-DPI case is fixed upstream, run the unit regressions in `tests/test_ocr_plugin.py`, and run one real Paperless end-to-end hybrid-PDF reprocess with PaddleOCR. If the newer OCRmyPDF version handles the case itself, leave the shim scoped to 17.7.1 and remove it only when 17.7.1 is no longer a supported/tested target.

A newer Paperless/OCRmyPDF release should be treated as unverified until the plugin contract is checked.

The new-correspondent suggestion bridge is also version-sensitive because it depends on Paperless' AI classification-suggestion request shape. It supports the list-based taxonomy response contract used by Paperless-ngx **3.0.5** and the nested `existing_ids` / `new_names` taxonomy-choice schema introduced by Paperless-ngx **3.1.0**. The bridge derives the response shape from each request schema instead of hardcoding a Paperless version.

The tested reference environment above is verified end to end with Paperless-ngx **3.1.0** and OCRmyPDF **17.7.1**, including the OCR plugin and Paperless AI Suggestions bridge. Other Paperless/OCRmyPDF combinations remain unverified until the relevant integration contracts are checked.

Paperless 2.x is not a supported target for this OCR/plugin path.

## OCR models and languages

The tested reference runtime uses PaddleOCR with **PP-OCRv6 Medium** detection and recognition models. The Control Center also exposes matching **Small** and **Tiny** PP-OCRv6 profiles. Medium is the default and the reference profile for published CPU measurements.

PP-OCRv6 Tiny does not support Japanese; configuration validation rejects that combination.

OCR language is configured separately. The service accepts common aliases from Paperless/Tesseract and maps them to the configured PP-OCRv6 language code, but rejects an actual language mismatch.

## LLM models, tagging and prompts

Classification uses one installed Ollama model selected in the Control Center. Title, document type, date and sender/issuer use one structured request.

Content tags use either **Hybrid tagging** or **LLM direct**. Hybrid tagging uses local scikit-learn TF-IDF/nearest-neighbor retrieval over reviewed Paperless documents and is the recommended strategy for the `qwen3.5:4b` reference model. LLM direct is intended for models that can map document semantics to the user's taxonomy reliably enough without retrieved examples.

System, Base classification and Tagging prompts are editable. English and German presets are included for all three components, and Tag Guidance is configurable per Paperless content tag.

ARM64 is not claimed as supported.
