# Configuration

Most day-to-day configuration is managed in **Prompt Studio**.

## App-Einstellungen

### Connections

- Paperless URL
- Ollama URL
- Paperless token presence check

The token itself remains a deployment secret and is never shown by the UI.

### Pipeline & tags

- OCR queue/error tags
- LLM queue/error tags
- human-review tag
- extra taxonomy-excluded tags

### OCR

- language
- PaddleOCR generation
- device

### Runtime

- poll interval
- review cleanup interval
- dry-run

These settings are stored in `APP_DATA_DIR/config/app-config.json` and hot-reloaded by the workers.

## Klassifizierung

Controls the main metadata request:

- prompt
- model and request parameters
- context/output limits
- prompt rendering and real model tests
- version history

The response covers title, document type, tags, date and an existing correspondent in one structured request.

## Korrespondent-Vorschlag

Optional second stage used only when the main classifier cannot resolve a correspondent.

It has its own prompt, model settings, tests, history and production enable switch. New correspondents are never created automatically.

## Deployment-only settings

These remain outside Prompt Studio because Docker needs them before the app starts or because they are secrets:

- `PAPERLESS_TOKEN`
- image/version
- `APP_DATA_DIR`
- host bind addresses and ports
- container CPU/RAM/shared-memory limits

Changing deployment-owned values requires recreating or redeploying the affected containers.
