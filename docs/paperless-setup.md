# Paperless-ngx setup

`paperless-local-ai` uses Paperless workflow tags as its processing queue. The default setup needs five queue/error/review tags and one import workflow.

## API token

Create a Paperless API token under **My Profile** and provide it to the deployment as `PAPERLESS_TOKEN`.

The token's Paperless user must be allowed to read and update the documents and taxonomy the app should manage.

## Tags

Fresh-install defaults are:

| Tag | Purpose |
|---|---|
| `PaddleOCR` | OCR queue |
| `PaddleOCR Error` | OCR errors |
| `LLM` | metadata queue |
| `LLM Error` | metadata errors |
| `Inbox` | human review |

`TODO` is the default additional tag excluded from normal LLM content-tag candidates.

You may rename these values in the Control Center. Paperless and Control Center names must match exactly.

Set automatic matching to **None** for the four queue/error tags so Paperless does not assign them independently.

## Import workflow

A simple default workflow is:

```text
Name:    PaddleOCR Queue
Trigger: Document added
Action:  add tag PaddleOCR
```

This example queues **every newly added document**. If you only want selected documents processed, add the appropriate Paperless workflow conditions instead of using an unconditional trigger.

The app then owns the handoff:

```text
PaddleOCR → ocr-worker → LLM → metadata-worker → Inbox/review
```

On processing errors, the active queue tag is removed and the configured error tag is applied.

### Existing documents

To test or process a document that is already in Paperless, manually add the configured OCR queue tag (`PaddleOCR` by default). The normal handoff continues from there.

You can use Paperless' normal bulk actions if you intentionally want to queue multiple existing documents, but test one document first.

## What metadata is written

The primary classifier is constrained to the current Paperless document types, existing correspondents and eligible content tags.

On a successful normal metadata write:

- `title` is replaced by the model result;
- `document_type` is set to the selected existing value, or cleared if the model returns no value;
- `correspondent` is set to the selected existing value, or cleared if no correspondent is resolved;
- `created` is changed only when the model returns a date;
- eligible content tags are replaced by the model's returned content tags;
- technical workflow/review tags and tags configured as additionally excluded are preserved.

Because content-tag assignment is replacement-based, use **Dry Run** and a test document before enabling the pipeline on an existing archive.

If the optional correspondent fallback finds an exact existing correspondent, it can be applied automatically. A genuinely new name is never auto-created.

## Optional: native new-correspondent review

Skip this entire section if you only want OCR, normal metadata assignment and matching of existing correspondents.

This integration is only needed when genuinely new correspondent candidates should appear in Paperless' native **Suggestions** UI.

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

The bridge does not run another LLM. For supported Paperless classification-suggestion requests, it preserves Paperless' classic suggestions and adds only a uniquely matched, still-open correspondent candidate.

This setting points Paperless' configured AI backend at the bridge. The bridge is intentionally narrow and is **not** a replacement backend for Paperless chat/RAG or other general AI use.

The bridge is version-sensitive. Check [Compatibility](compatibility.md) before upgrading Paperless.
