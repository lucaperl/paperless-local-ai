# Maintainer testing

This document is for maintainers and contributors. End users should use the Control Center tests and the deployment checks in the installation guides.

## CI

Every push and pull request runs:

1. Python 3.12 compile checks;
2. unit/regression tests;
3. Docker Compose configuration validation.

Publishing a GitHub Release additionally verifies that the release tag matches `VERSION`, reruns tests, builds both amd64 images, publishes them to GHCR and creates container build-provenance attestations.

## Local checks

```bash
python -m compileall -q src tests scripts
pytest -q
docker compose -f compose.yaml config
docker compose -f compose.yaml -f compose.dev.yaml config
```

## Integration test checklist

Use this checklist for a new Paperless version or a meaningful pipeline/runtime change:

1. Start the target Paperless release and an external Ollama instance.
2. Build/pull both project images.
3. Start the Control Center and configure App settings.
4. Run `doctor` for the normal Docker Compose deployment.
5. Import a native-text PDF: OCR should avoid unnecessary Paddle inference and hand off to LLM.
6. Import a scanned PDF: selected pages should use PaddleOCR and update Paperless `content`.
7. Verify main metadata classification writes only allowed taxonomy values.
8. Verify correspondent fallback exact-existing match is auto-applied.
9. Verify a genuinely new correspondent appears only as a native Paperless suggestion when the bridge integration is enabled.
10. Verify removing the review tag causes the persistent review record to be pruned.
11. Verify OCR and LLM jobs serialize on the same `ai.lock`.
12. Change a harmless App setting such as polling interval and verify workers adopt it without a restart.

## Review-record / bridge regression tests

The automated suite covers atomic review-record persistence, prompt-content identity, legacy collision resolution, fail-closed ambiguity and parsing of the currently supported Paperless native AI prompt shape.
