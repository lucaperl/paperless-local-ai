# Paperless-ngx setup

`paperless-local-ai` needs five technical/review tags and one import workflow.

## API token

Create a Paperless API token under **My Profile** and provide it to the deployment as `PAPERLESS_TOKEN`.

The token's Paperless user must be allowed to read and update the documents and taxonomy the app should manage.

## Tags

Fresh-install defaults are:

| Tag | Purpose |
|---|---|
| `PaddleOCR` | OCR queue |
| `PaddleOCR Fehler` | OCR errors |
| `LLM` | metadata queue |
| `LLM Fehler` | metadata errors |
| `Inbox` | human review |

`TODO` is the default additional tag excluded from normal LLM content-tag candidates.

You may rename the tags in the Control Center. Paperless and Control Center names must match exactly.

Set automatic matching to **None** for the four queue/error tags so Paperless does not assign them independently.

## Import workflow

Create a workflow such as:

```text
Name:    PaddleOCR Queue
Trigger: Document added
Action:  add tag PaddleOCR
```

The app then owns the handoff:

```text
PaddleOCR → ocr-worker → LLM → metadata-worker → Inbox/review
```

On processing errors, the active queue tag is removed and the configured error tag is applied.

## Taxonomy behavior

The main classifier is constrained to the current Paperless document types, normal correspondents and content tags.

If the optional correspondent fallback finds an exact existing correspondent, it can be applied automatically. A genuinely new name is stored only as a review candidate and is never auto-created.

## Optional: native new-correspondent review

This integration is only needed if new correspondent candidates should appear in Paperless' native Suggestions UI.

Paperless must be able to reach the suggestion bridge. For the default host port:

```text
http://<bridge-host>:30149
```

For the tested Paperless-ngx 3.0.5 setup, configure **Application Configuration → AI** as follows:

```text
Enable AI features:        on
LLM backend:               ollama
LLM model:                 paperless-correspondent-bridge
LLM endpoint:              http://<bridge-host>:30149
Allow internal endpoints:  on   # when using a private/LAN address
LLM embedding backend:     none / empty
LLM embedding model:       empty
LLM embedding endpoint:    empty
LLM context size:          8192
LLM request timeout:       120
LLM output language:       empty
LLM API key:               empty
```

The bridge does not run another LLM. It preserves Paperless' classic suggestions and adds only a uniquely matched, still-open correspondent candidate.

The bridge is version-sensitive. Check [Compatibility](compatibility.md) before upgrading Paperless.
