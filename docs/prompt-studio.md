# Prompt Studio

Prompt Studio is the web UI for normal `paperless-local-ai` operation. It keeps runtime settings, prompt configuration and testing in one place.

## App-Einstellungen

Configure Paperless/Ollama connections, workflow tags, OCR settings, polling, review cleanup and dry-run.

Saved values are hot-reloaded by the workers. The Paperless API token is intentionally not editable here; it remains a deployment secret.

## Klassifizierung

Edit and test the main structured metadata prompt and its model/request parameters. A model test does not write metadata back to Paperless.

## Korrespondent-Vorschlag

Configure the optional correspondent-only fallback. It runs only when the main classifier cannot resolve a correspondent and must be explicitly enabled for production use.

Each section keeps its own version history so prompt/model changes can be restored safely.

See [Configuration](configuration.md) for setting ownership and [Paperless setup](paperless-setup.md) for the required Paperless-side workflow.
