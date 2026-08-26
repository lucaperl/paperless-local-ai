# Paperless-ngx setup

OCR integrates directly into Paperless' OCRmyPDF import path. The only tag queue owned by `paperless-local-ai` is the metadata queue.

## 1. API token

Create a Paperless API token under **My Profile** and provide it to the app as `PAPERLESS_TOKEN`.

The token's Paperless user must be allowed to read/update the documents and taxonomy the app should manage.

## 2. Metadata/review tags

Fresh-install defaults are:

| Tag | Purpose |
|---|---|
| `LLM` | metadata queue |
| `LLM Error` | metadata-processing errors |
| `Inbox` | human review |

`TODO` is the default additional tag excluded from LLM content-tag candidates.

You may rename these values in the Control Center. In particular, the review tag does **not** have to be named `Inbox`; Paperless and Control Center names only need to match exactly.

### Review-tag lifecycle

The configured review tag must stay on a document until human review is complete. The recommended setup is to mark the chosen review tag as an **Inbox tag** in Paperless. Paperless then adds it automatically to every newly consumed document. After checking the generated metadata, remove the review tag. Only documents that no longer carry the review, classification queue or classification error tag are eligible as trusted Hybrid history.

If you do not want to use Paperless' Inbox-tag behavior, explicitly add the configured review tag in the Document Added workflow instead.

### Paperless matching algorithms

For an exclusive paperless-local-ai metadata workflow, set **Matching algorithm → None** for every Paperless object whose automatic assignment is owned by paperless-local-ai:

- content tags that paperless-local-ai may assign;
- document types;
- correspondents;
- the classification queue, classification error and configured review tags;
- additional technical/excluded tags such as `TODO`.

This prevents Paperless' own rule-based or `Automatic` matching from independently assigning the same metadata before paperless-local-ai writes its result. Storage paths are not managed by paperless-local-ai and do not need to be changed for this reason.

OCR does not require PaddleOCR queue or error tags.

## 3. Metadata import workflow

The tested default workflow is:

```text
Name:    LLM Queue
Trigger: Document added
Action:  add tag LLM
```

This queues every newly added document for metadata classification after Paperless has completed import/OCR. With the recommended setup, Paperless has already added the configured review tag because that tag is marked as an **Inbox tag**. If you do not use the Inbox-tag option, add a second workflow action that assigns your configured review tag.

If only selected documents should be classified, add Paperless workflow conditions instead of using an unconditional trigger.

The metadata handoff is:

```text
Document Added → LLM → core-service metadata worker → Inbox/review
```

On metadata-processing errors, the LLM queue tag is removed and the configured LLM error tag is applied.

### Existing documents

Adding the `LLM` tag to an existing Paperless document queues **metadata classification only**. It does not rerun OCR.

Re-OCR of existing documents is a Paperless/OCRmyPDF operation and should be treated separately from the normal import workflow.

## 4. OCRmyPDF plugin integration

The `ocr-service` writes the current plugin to its persistent `/integration` mount.

Paperless must mount the same host directory read-only, for example:

```yaml
volumes:
  - /path/to/paperless-local-ai/data/integration:/opt/paperless-local-ai:ro
```

For the optional Paperless UI shortcut, `core-service` must also mount the same integration directory:

```yaml
volumes:
  - /path/to/paperless-local-ai/data/integration:/integration
```

New installations using the current Compose examples already include this mount. Existing installations that predate this feature must add it manually because an image update does not rewrite the stored Compose or TrueNAS Custom App configuration. OCR itself continues to use the existing integration mount regardless of whether the UI shortcut is enabled.

Add these environment values to Paperless:

```text
PLAI_OCR_URL=http://<ocr-service-address>:30150
PLAI_OCR_TOKEN=<same secret as OCR_SERVICE_TOKEN>
PLAI_OCR_TIMEOUT_SECONDS=1800
PAPERLESS_OCR_USER_ARGS={"plugins":["/opt/paperless-local-ai/ocrmypdf_plai.py"],"pdf_renderer":"fpdf2","optimize":0}
```

For the optional **paperless-local-ai** shortcut in the Paperless Settings header, the same read-only mount also exposes a tiny Django integration package. Add these Paperless environment values once:

```text
PYTHONPATH=/opt/paperless-local-ai
PAPERLESS_APPS=paperless_local_ai_ui.apps.PaperlessLocalAiUiConfig
```

If `PAPERLESS_APPS` already contains another Django app, append this app to the existing comma-separated value instead of replacing it. The integration is inert by default. After Paperless has restarted with these values, enable or disable the shortcut with one click under **Control Center → App Settings → Connections → Paperless shortcut**; no further Paperless restart is needed. The button is shown only where Paperless itself exposes the admin Settings header and opens the configured Control Center URL in a new tab.

The URL must be reachable from **inside the Paperless container**.

The plugin is verified against OCRmyPDF **17.4.2** in Paperless-ngx **3.0.5**.

For pages that OCRmyPDF sends to the plugin, PaddleOCR handles OCR inference instead of Tesseract. Native-text pages can stay on Paperless/OCRmyPDF's normal text path without unnecessary OCR.

### OCR language

Paperless passes its requested OCR language to the plugin. `ocr-service` checks that it matches the OCR language saved in the Control Center.

Common aliases are normalized, including:

```text
deu / ger → de
eng       → en
ita       → it
fra / fre → fr
spa       → es
por       → pt
nld / dut → nl
```

If the two configurations disagree, the OCR request fails closed with `ocr_language_mismatch`.

### OCRmyPDF behavior

The tested setup keeps Paperless in its normal automatic OCR flow and uses OCRmyPDF for archive generation. Scan/raster pages that OCRmyPDF sends to the OCR engine are handled by PaddleOCR with the PP-OCRv6 profile selected in the Control Center; Medium is the default.

The validated OCRmyPDF renderer contract is:

```text
pdf_renderer=fpdf2
optimize=0
```

The resulting Paperless archive is searchable PDF/A-2b while the uploaded original remains unchanged.

## 5. What metadata is written

Document types and LLM-selected content tags are constrained to current Paperless values. Sender/issuer output is free text and is resolved locally against existing correspondents after classification.

On successful metadata write-back:

- `title` is replaced by the model result;
- `document_type` is set to the selected existing value, or cleared if the model returns no value;
- `correspondent` is set to the selected existing value, or cleared if no correspondent is resolved;
- `created` changes only when the model returns a date;
- eligible content tags are replaced by the model's returned content tags;
- technical workflow/review tags and tags configured as additionally excluded are preserved.

Because content-tag assignment is replacement-based, use Dry Run and one test document before enabling metadata automation on an existing archive.

The main classification request extracts the actual sender/issuer as free text. `paperless-local-ai` resolves safe existing matches locally. A genuinely new correspondent is exposed through **Paperless Suggestions** and is never auto-created; there is no separate correspondent-only LLM stage.

## 6. Optional Paperless Suggestions integration for new correspondents

Skip this section if you only need OCR, metadata assignment and matching against correspondents that already exist in Paperless. Without the bridge, those functions continue to work. When the classifier extracts a plausible sender that cannot be safely matched to an existing correspondent, paperless-local-ai leaves the document's correspondent empty; its unmatched sender candidate is not surfaced in Paperless Document Suggestions and must be handled manually during review.

Paperless exposes Document Suggestions through its AI backend configuration. The bridge implements only the narrow classification-suggestion interface needed here: it does **not** run an LLM and does not provide chat/RAG. Configuring Paperless to use this bridge is therefore optional even though the bridge endpoint is included in `core-service`.

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

The primary classification request has already extracted the sender. For supported Paperless classification-suggestion requests, the bridge preserves Paperless' classic suggestions and adds only a uniquely matched, still-open new-correspondent candidate.

Do not point general Paperless AI/chat workloads at the bridge. It is intentionally limited to this Suggestions compatibility path.

Check [Compatibility](compatibility.md) before upgrading Paperless because this integration is version-sensitive.
