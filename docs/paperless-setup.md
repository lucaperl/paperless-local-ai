# Paperless-ngx setup

This document describes the Paperless-side configuration expected by `paperless-local-ai` 0.1.0.

The native new-correspondent bridge is verified specifically with **Paperless-ngx 3.0.5**.

## 1. API token

`paperless-local-ai` uses Paperless' normal REST API with token authentication.

In Paperless open **My Profile** and create/regenerate an API token. Put the value only in the deployment `.env`/secret environment as `PAPERLESS_TOKEN`.

Use a token belonging to a Paperless user that may read/update the documents and taxonomy this app should manage.

## 2. Required technical tags

Fresh-install defaults from **Studio -> App-Einstellungen -> Pipeline & Tags** are:

```text
PaddleOCR
PaddleOCR Fehler
LLM
LLM Fehler
Inbox
```

`TODO` is the default additional tag excluded from normal LLM content-tag candidates.

You may rename all technical tags. The names configured in Paperless and Studio must match exactly.

Set the matching algorithm of the four queue/error tags to **None** so Paperless' automatic matching does not assign them independently:

```text
PaddleOCR
PaddleOCR Fehler
LLM
LLM Fehler
```

The review tag (`Inbox` by default) can follow your normal Paperless review workflow.

## 3. Import workflow

Create a Paperless workflow that queues newly added documents for the OCR stage.

Example:

```text
Name:    PaddleOCR Queue
Trigger: Document added
Action:  add tag PaddleOCR
```

If you renamed the OCR queue tag in Studio, use that name instead.

The runtime then owns the technical handoff:

```text
Paperless workflow
  -> OCR queue tag
  -> ocr-worker
  -> LLM queue tag
  -> metadata-worker
  -> human review tag remains
```

On a real OCR error the OCR queue tag is removed and the configured OCR error tag is set. The LLM worker follows the equivalent behavior for its queue/error tags.

## 4. Taxonomy behavior

The main classification stage does not invent arbitrary document types, normal correspondents or content tags. Allowed values are loaded from the current Paperless taxonomy for each job.

The separate correspondent fallback is the only stage that can return a free-text correspondent name:

- exact normalized match to an existing Paperless correspondent -> apply it;
- genuinely new name -> save a review candidate;
- never automatically create a new correspondent.

## 5. Optional native new-correspondent review

This feature is **not required** for selective OCR or normal metadata classification.

Enable it only if a new correspondent candidate should appear in Paperless' native Suggestions UI.

### What the bridge replaces

Paperless 3.0.5 is configured to use `suggestion-bridge` as its Ollama-compatible AI suggestion backend. The bridge itself performs **no LLM inference**. It preserves classic Paperless suggestions and adds only a uniquely matched, still-open correspondent review candidate.

Because this occupies Paperless' AI-suggestions backend, it does not proxy or chain to a second Paperless LLM backend.

### Network requirement

Paperless must be able to reach the bridge URL. If Paperless runs in a container, a bridge bound only to host `127.0.0.1` is normally **not** reachable from that Paperless container. Bind the bridge to a trusted host/LAN address and do not expose it publicly.

### Tested Paperless 3.0.5 AI settings

In **Application Configuration -> AI**, configure the equivalent of:

```text
Enable AI features:        on
LLM backend:               ollama
LLM model:                 paperless-correspondent-bridge
LLM endpoint:              http://<bridge-host>:30149
Allow internal endpoints:  on   (required when the bridge is on a private/LAN address)
LLM embedding backend:     none / empty
LLM embedding model:       empty
LLM embedding endpoint:    empty
LLM context size:          8192
LLM request timeout:       120
LLM output language:       empty
LLM API key:               empty
```

Do not enable an embedding backend for this bridge integration; the tested request identity is the Paperless 3.0.5 no-RAG suggestion shape.

### Health check

The bridge exposes:

```text
GET /health
```

For a default host port:

```text
http://<bridge-host>:30149/health
```

A healthy bridge still returns no new correspondent if request identity is missing/ambiguous or the review record is no longer open. That fail-closed behavior is intentional.

## 6. Paperless version changes

The OCR and metadata workers mostly use normal REST API behavior. The native suggestion bridge is more tightly coupled to Paperless' AI prompt/request contract.

Before upgrading Paperless beyond a version marked tested in [compatibility.md](compatibility.md), either disable the native bridge integration or validate it against the new Paperless release first.
