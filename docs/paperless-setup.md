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

`TODO` is the default additional tag excluded from normal LLM content-tag candidates.

You may rename these values in the Control Center. Paperless and Control Center names must match exactly.

Set automatic matching to **None** for technical queue/error tags so Paperless does not assign them independently.

OCR does not require PaddleOCR queue or error tags.

## 3. Metadata import workflow

The tested default workflow is:

```text
Name:    LLM Queue
Trigger: Document added
Action:  add tag LLM
```

This queues every newly added document for metadata classification after Paperless has completed import/OCR.

If only selected documents should be classified, add Paperless workflow conditions instead of using an unconditional trigger.

The metadata handoff is:

```text
Document Added → LLM → metadata-worker → Inbox/review
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

Add these environment values to Paperless:

```text
PLAI_OCR_URL=http://<ocr-service-address>:30150
PLAI_OCR_TOKEN=<same secret as OCR_SERVICE_TOKEN>
PLAI_OCR_TIMEOUT_SECONDS=1800
PAPERLESS_OCR_USER_ARGS={"plugins":["/opt/paperless-local-ai/ocrmypdf_plai.py"],"pdf_renderer":"fpdf2","optimize":0}
```

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

The primary classifier is constrained to the current Paperless document types, existing correspondents and eligible content tags.

On successful normal metadata write-back:

- `title` is replaced by the model result;
- `document_type` is set to the selected existing value, or cleared if the model returns no value;
- `correspondent` is set to the selected existing value, or cleared if no correspondent is resolved;
- `created` changes only when the model returns a date;
- eligible content tags are replaced by the model's returned content tags;
- technical workflow/review tags and tags configured as additionally excluded are preserved.

Because content-tag assignment is replacement-based, use Dry Run and one test document before enabling metadata automation on an existing archive.

If the optional correspondent fallback finds an exact existing correspondent, it can be applied automatically. A genuinely new correspondent is exposed through **Paperless Suggestions** and is never auto-created.

## 6. Optional native new-correspondent review

Skip this section if you only want OCR, automatic metadata assignment and matching of existing correspondents.

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

The bridge is intentionally narrow and is not a replacement backend for Paperless chat/RAG or other general AI use.

Check [Compatibility](compatibility.md) before upgrading Paperless because this integration is version-sensitive.
