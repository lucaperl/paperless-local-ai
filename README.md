> [!NOTE]
> This project has been entirely vibe-coded. It works well in my setup, but bugs may still exist, so use it at your own discretion. Feedback, bug reports, and pull requests are very welcome.

# paperless-local-ai

**Local OCR, metadata automation and document chat for Paperless-ngx, designed for modest CPU-only hardware and direct control over local AI.**

`paperless-local-ai` works alongside an existing Paperless-ngx installation. It improves scan OCR with PaddleOCR, classifies new documents with a local LLM, and adds persistent multi-turn document chat directly inside the Paperless interface.

The project assumes that CPU and memory are limited. Expensive OCR, embedding and LLM work runs one task at a time instead of competing for the same resources. The Control Center lets you choose and tune prompts, models, tagging behavior and document-chat settings.

It provides three main capabilities:

- **Better scan OCR:** PP-OCRv6 handles recognition for pages that Paperless/OCRmyPDF decides need OCR.
- **Automatic metadata:** a local LLM generates title, document type, date and correspondent, while tags use Hybrid or direct LLM classification. After human review, completed documents can help classify similar ones later.
- **Document chat:** persistent multi-turn conversations inside Paperless, with search across the current document, the full archive or selected tags, correspondents and document types.

Paperless remains the document system of record, and Ollama remains a separate service. `paperless-local-ai` manages the local AI workflows around them.

<p align="center">
  <a href="images/document-chat-all-documents.png">
    <img src="images/document-chat-all-documents.png" alt="paperless-local-ai document chat searching across all Paperless documents" width="80%">
  </a>
</p>

<p align="center">
  <sub>Document chat with synthetic demo documents and responses. Timing values shown in the demo UI are illustrative and are not benchmark results.</sub>
</p>

**[Try the Control Center live demo](https://lucaperl.github.io/paperless-local-ai/demo/)** - an interactive browser-only preview of the administration UI using synthetic Paperless, Ollama and OCR data.

## What it provides

### OCR

PP-OCRv6 handles recognition when Paperless/OCRmyPDF decides that a page needs OCR. Pages with usable native text stay on Paperless' normal text path instead of being sent through PaddleOCR unnecessarily.

**Medium** is the quality-focused default, with Small and Tiny profiles available when lower inference cost matters. The original/archive page is not resized; only the temporary image used for OCR is bounded.

See [Configuration](docs/configuration.md#ocr) and [Paperless setup](docs/paperless-setup.md#4-ocrmypdf-plugin-integration).

### Metadata automation

A Paperless **Document Added** workflow queues a document for local classification. Title, document type, date and sender/issuer are generated together in one structured model request; tags use that same request when the selected tagging strategy needs the LLM.

Two tagging strategies are available:

- **Hybrid tagging**, recommended for compact local models, can reuse a complete reviewed tag set when sufficiently similar reviewed documents agree strongly enough. If the evidence is uncertain, the LLM chooses the tags using Tag Guidance and relevant reviewed examples.
- **LLM direct** lets the configured model choose tags for every document from the current Paperless taxonomy.

Correspondents are resolved locally against existing Paperless values after the model extracts the sender. Plausible new names can optionally be shown through Paperless Document Suggestions, but `paperless-local-ai` never creates correspondents automatically.

See [Tagging](docs/tagging.md) and [Configuration](docs/configuration.md#classification).

### Document chat

The Paperless UI integration provides persistent multi-turn chats with scopes for the current document, all documents, tags, correspondents and document types. Answers include links back to the source documents, with current source metadata read directly from Paperless.

<table>
<tr>
<td width="50%" valign="top">
  <a href="images/document-chat-current-document.png">
    <img src="images/document-chat-current-document.png" alt="paperless-local-ai chat with the currently open Paperless document" width="100%">
  </a>
</td>
<td width="50%" valign="top">
  <a href="images/document-chat-tag-scope.png">
    <img src="images/document-chat-tag-scope.png" alt="paperless-local-ai document chat restricted to a Paperless tag" width="100%">
  </a>
</td>
</tr>
<tr>
<td valign="top">
  <strong>Current document</strong><br>
  Ask follow-up questions about the document currently being reviewed.
</td>
<td valign="top">
  <strong>Scoped retrieval</strong><br>
  Restrict retrieval to a tag, correspondent or document type.
</td>
</tr>
</table>

<p align="center">
  <sub>Synthetic demo documents and responses; displayed timings are not performance measurements.</sub>
</p>

The [Control Center](#control-center) provides the global settings for the chat model, prompts, generation, retrieval, embeddings and index behavior. Conversations and per-chat settings remain inside Paperless.

The index is a rebuildable SQLite cache, not a second document store. The first build starts only when requested. Rebuilds are prepared separately so the existing index remains usable until the replacement is ready, and interrupted rebuilds can be resumed instead of starting again.

On CPU-only systems, index embedding is split into small slices so waiting OCR or metadata work can run between them.

See [RAG chat](docs/rag-chat.md).

## Why paperless-local-ai?

Paperless-ngx already provides optional AI features and can use local Ollama. PLAI is built around two additional priorities: predictable resource use on CPU-only hardware and more control over how the local AI works.

Only one heavy PLAI task runs at a time. OCR, metadata generation, document chat and index embedding wait for each other instead of putting their peak CPU and memory load on the server at the same time.

Paperless lets you choose its AI backend and models and configure some basic limits. Its AI prompts and much of its document-chat retrieval behavior are not user-configurable. PLAI exposes these settings in the [Control Center](#control-center), including prompts, generation settings, tagging behavior, retrieval, embeddings and index management.

Document chat is a good example. A normal chat turn follows the same model path every time:

```text
question + recent conversation context
→ 1 local embedding request
→ find relevant passages in the local index
→ assemble the source context
→ 1 local chat-generation request
→ answer + links to the source documents
```

A normal chat turn does not add separate LLM calls for query rewriting, reranking, answer refinement, summarization or an agent loop. This keeps the amount of expensive model work predictable, which matters much more on a CPU-only server than on fast accelerator hardware.

PLAI also stores conversations server-side, so follow-up questions can use earlier turns instead of treating every question as a new conversation.

Metadata follows the same general approach: one structured model request covers the main metadata fields, while Hybrid tagging can reuse reviewed history for familiar documents and falls back to the LLM when the evidence is not strong enough.

`paperless-local-ai` does not replace every native Paperless AI feature. Paperless' similar-document UI remains separate, and Paperless native AI can suggest storage paths while PLAI metadata automation currently does not manage them.

See [Architecture](docs/architecture.md#native-paperless-ai-and-plai), [RAG chat](docs/rag-chat.md) and [Tagging](docs/tagging.md) for the technical details.

## Designed for modest hardware

The project is designed around CPU-only home-server hardware rather than treating it as a fallback configuration.

- Only one heavy PLAI task runs at a time, so OCR, Ollama inference and index embedding do not put their peak load on the machine simultaneously.
- Heavy helper processes are started when needed and released again afterward.
- Ollama models are unloaded after PLAI finishes using them.
- Full-index embedding runs in slices and gives other waiting work a chance to run between slices.
- RAG uses SQLite and local cosine retrieval instead of requiring a separate vector database or agent service.
- A GPU can make inference faster, but it is not required by the architecture.

The trade-off is intentional: PLAI favors predictable CPU and RAM use over running several AI tasks at the same time.

See [Architecture](docs/architecture.md) for the resource-management details.

## Reference performance

Measured on an **Intel Core i3-8100 · 4 cores / 4 threads · 16 GB RAM · no GPU · qwen3.5:4b Q4_K_M · PP-OCRv6 Medium / HPI / OpenVINO**.

| Workload | Input | Processing time | Peak RAM |
|---|---|---:|---:|
| OCR · PP-OCRv6 Medium · 3000 px | per page | **~23 s/page** | **~4.3 GiB** |
| Metadata · qwen3.5:4b | ~1–4k prompt tokens | **~40 s–2.5 min** | **~4.2 GiB** |
| Metadata · qwen3.5:4b | ~5–9k prompt tokens | **~3–5.5 min** | **~4.2 GiB** |
| Metadata · qwen3.5:4b | ~9–12k prompt tokens | **~5.5–7.5 min** | **~4.2 GiB** |

Page count is only a rough indicator for metadata. Runtime mainly follows the number of prompt tokens actually processed. A measured ~14k-token fallback took about 8.7 minutes on the same CPU.

These figures are reference measurements. See [Configuration](docs/configuration.md#reference-performance-and-resource-tuning) for RAM points and tuning guidance.

## How it fits into Paperless

**Import and automation path**

```text
Paperless import
→ OCRmyPDF
→ PaddleOCR when OCR is needed
→ searchable Paperless archive/content
→ Document Added workflow
→ local metadata classification/tagging
→ Paperless metadata
→ human review
```

**Interactive document-chat path**

```text
Paperless chat panel
→ current question + recent conversation context
→ one local query embedding
→ retrieve relevant passages from the PLAI index
→ current Paperless metadata for selected sources
→ one local chat generation
→ answer + Paperless source links
```

<p align="center">
  <img src="images/paperless-flow.svg" alt="paperless-local-ai import and metadata workflow" width="65%">
</p>

The uploaded PDF remains Paperless' original. PLAI stores its own configuration, configuration history and chat conversations plus rebuildable OCR, Hybrid-history and RAG working state.

## Control Center

The Control Center is where `paperless-local-ai` is configured and tested. It covers:

- Paperless and Ollama connections;
- OCR model, language, image limits and recovery behavior;
- metadata workflow, Dry Run and correspondent matching;
- classification models, editable prompts and safe prompt/model tests;
- Hybrid tagging, reviewed-history diagnostics and Tag Guidance;
- document-chat models, prompts and generation settings;
- retrieval behavior and diagnostics;
- embedding, chunking and index Sync/Rebuild/Pause/Resume;
- versioned configuration history.

<p align="center">
  <a href="images/control-center-screenshot.png">
    <img src="images/control-center-screenshot.png" alt="paperless-local-ai Control Center overview" width="80%">
  </a>
</p>

<p align="center">
  <strong><a href="https://lucaperl.github.io/paperless-local-ai/demo/">Open the interactive Control Center demo →</a></strong>
</p>

The actual document chat lives inside Paperless. See [Control Center](docs/control-center.md) and [Configuration](docs/configuration.md) for the available settings.

## Requirements

Paperless-ngx · Ollama · Docker Compose or TrueNAS SCALE · linux/amd64 · GPU not required

Tested reference: **Paperless-ngx 3.1.0 · OCRmyPDF 17.7.1 · TrueNAS SCALE 25.10.6 · Ollama 0.32.11**. See [Compatibility](docs/compatibility.md) for the exact tested scope.

## Install

Choose one deployment guide:

- [Docker Compose](docs/installation.md)
- [TrueNAS SCALE](docs/truenas.md)

Then complete the required [Paperless integration](docs/paperless-setup.md) and review [Configuration](docs/configuration.md).

Further reading: [RAG chat](docs/rag-chat.md) · [Tagging](docs/tagging.md) · [Architecture](docs/architecture.md) · [Control Center](docs/control-center.md) · [Troubleshooting](docs/troubleshooting.md) · [Compatibility](docs/compatibility.md)

## Security

The Control Center has no built-in authentication. Keep it on localhost or a trusted network.

The OCR endpoint is authenticated with a separate shared token. Do not expose it directly to the public Internet. The Paperless chat relay is same-origin, uses Paperless session authentication/CSRF protection, and does not expose the Paperless API token or internal relay secret to the browser.

See [SECURITY.md](SECURITY.md).

## License

MIT for this repository's source code. Third-party components retain their own licenses; see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
