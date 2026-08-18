## What changed

Describe the user-visible or maintenance change.

## Validation

- [ ] `python -m compileall -q src tests scripts`
- [ ] `pytest -q`
- [ ] Compose validation (when deployment files changed)
- [ ] Integration test (when OCR, Paperless AI bridge, service graph or persistent contracts changed)

## Compatibility / deployment impact

- [ ] No Paperless compatibility claim changed
- [ ] No Compose contract changed
- [ ] No persistent data migration required

If any box above is false, explain the required release-note/update guidance.

## Privacy

- [ ] No token, private document content, private OCR dump or real `.env` was included
