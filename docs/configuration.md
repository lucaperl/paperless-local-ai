# Configuration

Most day-to-day configuration is managed in the **Control Center**.

## Test before production

The Control Center lets you validate changes before they affect normal metadata processing:

- test Paperless and Ollama connections with the current unsaved settings;
- preview the exact rendered prompt for a real Paperless document without calling the model;
- run real Ollama tests for **Classification** and **Correspondent fallback** without modifying the document;
- use **Dry Run** for automatic metadata processing without document-metadata or persistent-review writes.

Dry Run still allows the technical queue/error tags to be managed as part of the workflow.

## App settings

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
- Dry Run

These settings are stored in `APP_DATA_DIR/config/app-config.json` and hot-reloaded by the workers.

## Classification

Controls the main structured metadata request: prompt, model/request parameters, output limits, testing and version history.

The response covers title, document type, tags, date and an existing correspondent in one request.

## Correspondent fallback

Optional second stage used only when the main classifier cannot resolve a correspondent.

It has its own prompt, model settings, tests, history and production enable switch. New correspondents are never created automatically.

## Deployment-only settings

These remain outside the Control Center because Docker needs them before the app starts or because they are secrets:

- `PAPERLESS_TOKEN`
- image/version
- `APP_DATA_DIR`
- host bind addresses and ports
- container CPU/RAM/shared-memory limits

Changing deployment-owned values requires recreating or redeploying the affected containers.
