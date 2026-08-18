# Configuration ownership

`paperless-local-ai` intentionally has **three** configuration owners. A setting should exist in only one of them.

## 1. Deployment: `.env`

Use `.env` only for values Docker needs before the application starts, plus secrets:

```text
PAPERLESS_TOKEN
IMAGE_PREFIX
APP_VERSION
APP_DATA_DIR
PROMPT_UI_BIND / PROMPT_UI_PORT
SUGGESTION_BRIDGE_BIND / SUGGESTION_BRIDGE_PORT
container CPU/RAM/shared-memory limits
```

Changing Docker-owned values requires recreating/redeploying the affected container.

The Paperless API token stays here because it is a secret. The Studio never returns its value.

## 2. Shared application runtime: App-Einstellungen

Stored together in:

```text
APP_DATA_DIR/config/app-config.json
```

This owns:

```text
Paperless URL
Ollama URL
OCR queue/error tag
LLM queue/error tag
review tag
extra taxonomy-excluded tags
OCR language/version/device
poll interval
review cleanup interval
dry-run
```

Workers reload these settings while running.

## 3. LLM-stage configuration

The two LLM stages are deliberately independent programs and therefore keep separate versioned configs:

```text
Klassifizierung
  prompt + model/request parameters

Korrespondent-Vorschlag
  prompt + model/request parameters + enabled switch
```

This is intentional: restoring an old prompt must restore the model/context/output parameters that belonged to that prompt, without rolling back unrelated OCR or connection settings.

## Not configurable on purpose

Some implementation values are constants because exposing them would add unsupported tuning without a real operator use case. Examples include bridge request-body limit, taxonomy cache TTL and the review-signature word count.

If a value becomes operationally useful later, it should be promoted into the single appropriate owner instead of being added as another ad-hoc environment variable.
