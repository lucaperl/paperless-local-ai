# Control Center

The **paperless-local-ai Control Center** is the main web UI for normal operation. It combines runtime configuration, prompt/model settings, safe testing and version history in one place.

## Test before production

You can test the parts that can safely run interactively before enabling normal metadata writes:

- **Connections:** test Paperless and Ollama using the current unsaved settings.
- **Classification:** preview the exact rendered request or run a real Ollama test against an existing Paperless document. The test does not modify the document.
- **Correspondent fallback:** preview or run the second-stage model even while production use is disabled. Tests do not write metadata or persistent review suggestions.
- **Dry Run:** let the automatic metadata worker process queued documents without writing document metadata or persistent review records. Technical workflow tags can still change.

## App settings

Configure Paperless/Ollama URLs, workflow tags, OCR language/model generation/device, polling, review cleanup and Dry Run.

Saved runtime settings are hot-reloaded by the workers. The Paperless API token remains a deployment secret and is never shown by the UI.

## Classification

Edit the main structured metadata prompt and model/request parameters, inspect allowed Paperless taxonomy values, run tests and restore previous configuration versions.

## Correspondent fallback

Configure the optional second LLM stage used only when classification cannot resolve a correspondent. It can be tested while disabled and has its own history and production switch.

The Control Center interface is English. The default classification prompts remain German in the current tested workflow and can be edited in the UI.

The Control Center has no built-in authentication. Keep it on localhost or a trusted network.
