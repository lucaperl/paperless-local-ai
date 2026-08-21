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

## Paperless / OCRmyPDF versions

0.2.0 is more version-sensitive than 0.1.x because OCR integrates through OCRmyPDF's plugin API.

The included plugin is verified against OCRmyPDF **17.4.2**, specifically the native `OcrEngine.generate_ocr()` / `OcrElement` interface used by Paperless-ngx **3.0.5**.

Do not assume a newer Paperless/OCRmyPDF release is compatible until the plugin contract has been checked.

The native new-correspondent suggestion bridge is also version-sensitive because it depends on Paperless' AI classification-suggestion request shape. Its tested target is likewise Paperless-ngx **3.0.5**.

Paperless 2.x is not a supported target for the 0.2.0 OCR/plugin path.

## Models and languages

Classification and Correspondent fallback can use installed Ollama models selected independently in the Control Center.

OCR language is configured separately. The service accepts common aliases from Paperless/Tesseract and maps them to the configured PP-OCRv6 language code, but rejects an actual language mismatch.

Classification and Correspondent fallback include English and German prompt presets and support custom prompt text.

ARM64 is not currently claimed as supported.
