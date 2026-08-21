# Maintainer testing

This document is for maintainers and contributors.

## CI

Every push and pull request runs:

1. Python 3.12 compile checks;
2. unit/regression tests;
3. Docker Compose configuration validation.

Publishing a GitHub Release also verifies that the release tag matches `VERSION`, reruns tests, builds both amd64 images, publishes them to GHCR and creates build-provenance attestations.

## Local checks

```bash
python -m compileall -q src tests scripts
pytest -q
docker compose -f compose.yaml config
docker compose -f compose.yaml -f compose.dev.yaml config
```

## OCR-specific regression contract

For the OCR service, verify:

- the image uses the intended PP-OCRv6 Medium detection/recognition models;
- HPI/OpenVINO uses the intended CPU thread count;
- repeated pages can reuse one short-lived Paddle session;
- after idle teardown, `/health.session_active=false` only when the shared `ai.lock` is actually free;
- a new cold session can start after teardown;
- OCR text/geometry stays stable across lifecycle tests;
- no unexpected model download occurs after a populated persistent cache.

## Paperless end-to-end checklist

Use this checklist for a new Paperless/OCRmyPDF version or meaningful pipeline change:

1. Start the target Paperless release and external Ollama.
2. Build/pull both project images.
3. Configure the Control Center.
4. Configure the Paperless OCRmyPDF plugin mount and `PLAI_OCR_*` values.
5. Run `doctor` where available.
6. Import a known two-page scanned PDF.
7. Confirm the Paperless consumption task succeeds.
8. Confirm the uploaded original remains byte-identical.
9. Confirm the archive has the expected page count, passes `qpdf --check`, contains searchable text and reports the expected PDF/A conformance.
10. Confirm OCR used PP-OCRv6/HPI/OpenVINO.
11. Confirm the Document Added workflow assigns the LLM queue tag.
12. Confirm metadata write-back produces allowed taxonomy values and ends in the review tag without the LLM error tag.
13. Observe Paddle and Ollama during the transaction and confirm they never overlap.
14. Confirm Ollama is explicitly unloaded and Paddle/`ai.lock` are idle at the end.
15. Remove only the known test document after all assertions pass.

## Review-record / bridge regression tests

The automated suite covers atomic review-record persistence, prompt-content identity, legacy collision resolution, fail-closed ambiguity and parsing of the currently supported Paperless native AI prompt shape.
