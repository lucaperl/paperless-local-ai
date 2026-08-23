# Compatibility

Compatibility claims are intentionally narrow: an environment is listed as tested only after integration testing.

## Tested reference environment

| Component | Tested reference |
|---|---|
| Paperless-ngx | **3.0.5** |
| OCRmyPDF inside Paperless | **17.4.2** |
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

The OCR integration uses OCRmyPDF's plugin API and is therefore version-sensitive.

The included plugin is verified against OCRmyPDF **17.4.2**, specifically the native `OcrEngine.generate_ocr()` / `OcrElement` interface used by Paperless-ngx **3.0.5**.

Do not assume a newer Paperless/OCRmyPDF release is compatible until the plugin contract has been checked.

The native new-correspondent suggestion bridge is also version-sensitive because it depends on Paperless' AI classification-suggestion request shape. Its tested target is likewise Paperless-ngx **3.0.5**.

Paperless 2.x is not a supported target for the current OCR/plugin path.

## OCR models and languages

The tested reference runtime uses PaddleOCR with **PP-OCRv6 Medium** detection and recognition models. The Control Center also exposes matching **Small** and **Tiny** PP-OCRv6 profiles. Medium remains the default and the reference profile used for the published CPU measurements.

PP-OCRv6 Tiny does not support Japanese; configuration validation rejects that combination.

OCR language is configured separately. The service accepts common aliases from Paperless/Tesseract and maps them to the configured PP-OCRv6 language code, but rejects an actual language mismatch.

## LLM models, tagging and prompts

Classification uses one installed Ollama model selected in the Control Center. Title, document type, date and sender/issuer use the same structured request. Tags use either the default **History-assisted** strategy or **LLM only**.

History-assisted tagging uses local scikit-learn TF-IDF/nearest-neighbor retrieval over finished reviewed Paperless documents. It is the recommended strategy for the `qwen3.5:4b` reference model; LLM-only remains available for larger or more capable models.

Classification includes English and German prompt presets, custom prompt text and optional per-tag LLM guidance.

ARM64 is not currently claimed as supported.
