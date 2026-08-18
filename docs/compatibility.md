# Compatibility

Compatibility claims in this project are intentionally narrow. A feature is marked tested only after an integration test, not because it is expected to be similar.

## Paperless-ngx

| Version | Status | Notes |
|---|---|---|
| 3.0.5 | **tested** | full OCR -> metadata -> review flow, REST metadata writes, classic suggestion preservation and native new-correspondent bridge tested end-to-end |
| newer 3.x | unverified | OCR/REST portions may work, but native suggestion bridge compatibility is not assumed until tested |
| 2.x | unsupported | the 0.1.0 native AI suggestion integration target is Paperless 3.0.5 |

The OCR and metadata workers use normal Paperless APIs and are less tightly coupled to a Paperless release than the suggestion bridge. The bridge parses the Paperless 3.0.5 no-RAG AI request shape and intentionally has a narrower compatibility claim.

## Paperless REST API

The app uses token-authenticated REST requests for documents and taxonomy. Paperless server version changes should be treated independently from the native suggestion bridge contract; both need to be considered before expanding compatibility claims.

## Ollama

Ollama is external. The app uses Ollama's HTTP API for metadata inference and connection/model checks.

The shipped default stage model is:

```text
qwen3.5:4b
```

Another installed Ollama model can be selected separately for each LLM stage in Studio. Model quality/performance is not assumed equivalent.

## Language

Release 0.1.0 is production-tested with German documents:

```text
OCR language: de
Default prompts: German
Studio UI: German
```

PaddleOCR language is configurable and prompts are editable, but non-German end-to-end behavior is not yet listed as tested.

## CPU architecture

The published 0.1.0 OCR image is built/tested for:

```text
linux/amd64
```

ARM64 is not claimed in 0.1.0.

## Deployment platforms

- **Docker Compose v2**: canonical deployment definition.
- **TrueNAS SCALE 25.10.4 Custom App**: production-tested reference deployment.
- **Other Compose-capable platforms**: expected to be adaptable to the same images/service graph, but not individually certified by this project yet.

## Native suggestion bridge identity

The bridge is tested against the Paperless-ngx 3.0.5 no-RAG classification prompt. Review-record schema v4 signs normalized prompt content and uses the old short-prefix signature only as a compatibility fallback for migrated records. Ambiguity fails closed.

If a future Paperless version changes the AI prompt/request contract, that version must be integration-tested before the bridge is marked compatible.
