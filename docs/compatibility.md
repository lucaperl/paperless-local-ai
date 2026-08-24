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

The OCR integration uses OCRmyPDF's plugin API and is version-sensitive.

The included plugin is verified against OCRmyPDF **17.4.2**, specifically the native `OcrEngine.generate_ocr()` / `OcrElement` interface used by Paperless-ngx **3.0.5**.

A newer Paperless/OCRmyPDF release should be treated as unverified until the plugin contract is checked.

The new-correspondent suggestion bridge is also version-sensitive because it depends on Paperless' AI classification-suggestion request shape. Its tested target is Paperless-ngx **3.0.5**.

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
