# Compatibility

Compatibility claims are intentionally narrow: a combination is listed as tested only after an integration test.

| Component | Tested / supported in 0.1.0 |
|---|---|
| Paperless-ngx | **3.0.5** |
| Deployment | Docker Compose v2 |
| TrueNAS SCALE | **25.10.4** Custom App |
| Platform | **linux/amd64** |
| OCR reference | PP-OCRv6 · German · CPU |
| Ollama reference model | **qwen3.5:4b** |
| Documents | German end-to-end workflow |

## Paperless versions

The OCR and metadata workers mostly use normal Paperless REST APIs and may work with newer releases.

The native new-correspondent suggestion bridge is more version-sensitive because it depends on Paperless' AI suggestion request shape. Do not assume a newer Paperless release is compatible until it has been tested.

Paperless 2.x is not a supported target for the 0.1.0 native suggestion integration.

## Other models and languages

Other installed Ollama models can be selected independently for the two LLM stages, but quality and performance are not assumed equivalent to the reference model.

OCR language and prompts are configurable. Non-German end-to-end behavior is not yet claimed as tested.

ARM64 is not claimed in 0.1.0.
