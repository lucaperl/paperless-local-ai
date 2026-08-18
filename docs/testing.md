# Testing

The repository includes behavior-focused tests for components that can run without a live Paperless/Ollama stack.

Release 0.1.0 validation:

```text
python -m compileall -q src tests scripts  PASS
pytest -q                                26 passed
unified Compose production cutover       PASS
real scanned-document OCR -> LLM          PASS
new correspondent native review bridge   PASS
runtime polling hot-reload                PASS
old/new OCR runtime A/B                   equivalent output/performance
```

## CI

Every push and pull request runs:

1. Python 3.12 compile check;
2. unit/regression tests;
3. Docker Compose configuration validation.

Publishing a GitHub Release additionally verifies that the release tag matches `VERSION`, reruns tests, builds both amd64 images, publishes them to GHCR and creates container build-provenance attestations.

## Integration test checklist

For a new Paperless version or a meaningful pipeline change:

1. Start the target Paperless release and an external Ollama instance.
2. Build/pull both project images.
3. Start Studio and configure App-Einstellungen.
4. Run `doctor`.
5. Import a native-text PDF: OCR should avoid unnecessary Paddle inference and hand off to LLM.
6. Import a scanned PDF: selected pages should use PaddleOCR and update Paperless `content`.
7. Verify main metadata classification writes allowed taxonomy only.
8. Verify correspondent fallback exact-existing match is auto-applied.
9. Verify a genuinely new correspondent appears only as a native Paperless suggestion.
10. Verify removing the review tag causes the persistent review record to be pruned.
11. Verify OCR and LLM jobs serialize on the same `ai.lock`.
12. Change a harmless App-Einstellung such as polling interval and verify workers adopt it without a restart.

## Review-record / bridge regression tests

The test suite covers atomic review-record persistence, prompt-content identity, legacy collision resolution, fail-closed ambiguity and parsing of the Paperless-ngx 3.0.5 native AI prompt shape.
