> [!NOTE]
> This project has been entirely vibe-coded. It works well in my setup, but bugs may still exist, so use it at your own discretion. Feedback, bug reports, and pull requests are very welcome.

# paperless-local-ai

**Local AI for Paperless-ngx: better OCR, metadata automation and document chat — designed for modest CPU-only hardware.**

`paperless-local-ai` is a focused companion stack that adds a local-AI layer around an existing Paperless-ngx installation without replacing Paperless or bundling Ollama. It has three first-class capabilities:

- **scan OCR** with PaddleOCR / PP-OCRv6 through Paperless' OCRmyPDF import path;
- **structured metadata automation** for title, document type, date, correspondent and tags;
- **lightweight document chat** with a local SQLite RAG index and a chat panel inside Paperless.

The project is deliberately **CPU-first and resource-aware**. Heavy OCR, history, embedding and chat/model work share one AI slot instead of competing for RAM and CPU. Heavy helpers are started on demand and released again, Ollama models are explicitly unloaded after work, and RAG uses SQLite plus exact cosine retrieval instead of a separate vector database or agent framework. A GPU can make inference faster, but it is not required by the architecture.

Paperless remains the document system of record. The original document is preserved, OCR/searchable archives and metadata stay in Paperless, and the RAG index is a regenerable search cache rather than a second document store.

**[Try the live demo](https://lucaperl.github.io/paperless-local-ai/demo/)** — an interactive browser-only preview using synthetic Paperless, Ollama and OCR data.

## Highlights

- **Improved scan OCR with PaddleOCR** — PP-OCRv6 Medium is the quality-focused default, with Small and Tiny profiles when lower inference cost matters.
- **Structured local metadata automation** — title, document type, date and sender/issuer are extracted together; tags join the same LLM request only when the active tag route needs the model.
- **Hybrid tagging for compact models** — reviewed Paperless documents can provide a confidence-gated exact tag-set reuse path, with an LLM fallback when the archive does not provide enough evidence.
- **LLM direct tagging** — lets a sufficiently capable local model choose tags directly from the Paperless taxonomy.
- **Conservative correspondent handling** — existing names are resolved locally; plausible new names can be exposed through the optional Paperless Suggestions bridge, but correspondents are never auto-created.
- **Lightweight document chat** — persistent multi-chat RAG inside Paperless with document/tag/correspondent/type scopes, deterministic source links, live Paperless metadata, configurable prompt assembly and retrieval diagnostics.
- **One embed + one chat model call per normal RAG turn** — no query-rewrite LLM, reranker LLM, refine chain, summarizer or agent loop on the normal path.
- **Designed for modest CPU-only systems** — OCR, Hybrid-history work, metadata inference, RAG chat and index slices are serialized through one shared resource lock; heavyweight runtimes are released after use.
- **Control Center** — one UI for connections, OCR, workflow settings, classification prompts/tagging, model settings, RAG prompts/retrieval/index administration, diagnostics, safe tests and configuration history.

## Why this architecture

`paperless-local-ai` is built around four priorities: **useful local AI, strong OCR, predictable Paperless integration and practical operation on modest hardware.**

**Useful local AI on small servers.** The project favors bounded, inspectable pipelines over maximum throughput. Only one heavyweight AI workload runs at a time, model residency is kept short, scientific/history helpers are disposable, and the RAG path avoids a separate vector service. This makes the stack practical on CPU-only home servers where RAM and sustained inference time matter more than benchmark concurrency.

**Better OCR before downstream AI.** Metadata extraction and document retrieval can only be as reliable as the text they receive. PP-OCRv6 Medium is the quality-focused default; Small and Tiny trade recognition quality for lower inference cost. HPI/OpenVINO accelerates the selected profile on CPU.

**Structured automation instead of open-ended agents.** Metadata classification uses one structured request with constrained Paperless values where appropriate. Hybrid tagging can reuse a complete reviewed tag set only behind an explicit evidence gate; uncertain cases go to the LLM. Correspondent extraction is followed by conservative local resolution, and genuinely new correspondents are never auto-created.

**Document chat stays lightweight.** The RAG feature is a first-class project capability but remains deliberately bounded. It keeps a regenerable SQLite index, performs exact local cosine retrieval, and uses exactly one query embedding request plus one chat-generation request for a normal turn. Full index work is sliced so the shared AI slot is released between batches, and an existing active index remains usable while a replacement index is built.

**Paperless remains authoritative.** OCR integrates into Paperless/OCRmyPDF, metadata is written back to Paperless, chat source links point to Paperless documents, and live source metadata is read from Paperless at chat time. `paperless-local-ai` does not become a second document management system.

## Reference performance

Measured on an **Intel Core i3-8100 · 4 cores / 4 threads · 16 GB RAM · no GPU · qwen3.5:4b Q4_K_M · PP-OCRv6 Medium / HPI / OpenVINO**.

| Workload | Document size | Prompt size | Processing time | Peak RAM |
|---|---|---:|---:|---:|
| OCR · PP-OCRv6 Medium · 3000 px | per page | — | **~23 s/page** | **~4.3 GiB** |
| Metadata · qwen3.5:4b Q4_K_M | ~1–2 pages | ~1–4k tokens | **~40 s–2.5 min** | **~4.2 GiB** |
| Metadata · qwen3.5:4b Q4_K_M | ~3–4 pages | ~5–9k tokens | **~3–5.5 min** | **~4.2 GiB** |
| Metadata · qwen3.5:4b Q4_K_M | ~5–6 pages | ~9–12k tokens | **~5.5–7.5 min** | **~4.2 GiB** |

Page count is only a rough indication of metadata cost. Runtime primarily follows the number of prompt tokens actually processed. Hybrid matches tend toward the lower end because tagging context is omitted, while fallback requests also include the tag taxonomy, guidance and retrieved examples. A 7-page fallback with ~14k prompt tokens took ~8.7 minutes.

The **Context window** sets the maximum available context and affects RAM usage. It does not mean every request processes the full configured context. A larger context window allows larger prompts, however, and large prompts can substantially increase CPU inference time.

## RAM usage and tuning

The main memory consumers are PaddleOCR and whichever Ollama model is active for metadata, embedding or chat. Hybrid-history TF-IDF/scikit-learn state is loaded only in an on-demand subprocess and released again after use. Heavy OCR, history, metadata, RAG chat and index work is serialized through the shared resource lock; the normal RAG path does not keep the embedding and chat models resident together.

| Workload | Configuration | Measured peak |
|---|---|---:|
| OCR | PP-OCRv6 Medium · 3000 px | **~4.3 GiB** |
| OCR | PP-OCRv6 Medium · 3200 px | **~4.9–5.1 GiB** |
| OCR | PP-OCRv6 Medium · 4000 px | **~6.5 GiB** |
| Metadata | qwen3.5:4b Q4_K_M · 4k context | **~3.6 GiB** |
| Metadata | qwen3.5:4b Q4_K_M · 8k context | **~3.8 GiB** |
| Metadata | qwen3.5:4b Q4_K_M · 16k context | **~4.2 GiB** |

If RAM is limited, lower **Maximum OCR image side** first for OCR pressure and reduce the **Context window** for LLM pressure. See [Configuration](docs/configuration.md#ram-usage-and-tuning).

## How it fits into Paperless

There are two complementary paths.

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
→ one local query embedding
→ exact retrieval from the PLAI SQLite index
→ live Paperless metadata for selected sources
→ one local chat generation
→ answer + Paperless source links
```

The uploaded PDF stays Paperless' original. The RAG index contains only regenerable chunks/embeddings and minimal index metadata; Paperless content remains authoritative. Changing non-structural chat/retrieval settings does not rebuild the index. Structural embedding changes are saved separately from the active index signature and take effect only after an explicit atomic rebuild.

<p align="center">
  <img src="images/paperless-flow.svg" alt="paperless-local-ai import and metadata workflow" width="65%">
</p>

The diagram above shows the import/metadata path. Document chat is a separate read/query path over the same Paperless archive.

## Tagging

Two strategies are available under **Control Center → Classification → Tagging**:

**Hybrid tagging — Recommended for small models**
Compares documents with reviewed examples and reuses a complete known leaf-tag set only when similarity and neighbor agreement are strong. Otherwise the LLM decides using Tag Guidance and relevant examples. [How Hybrid tagging works](docs/tagging.md#hybrid-tagging).

**LLM direct — For more capable models**
The configured model selects tags for every document. Reviewed examples are not used for tag routing or prompt examples.

The Control Center also shows reviewed-history health, **Retrospective history reuse**, **History depth by tag**, and advisory **Potential tag inconsistencies**. [Read the full tagging design](docs/tagging.md).

## Prompt composition

Classification uses three editable prompt fields:

1. **System prompt** — global model behavior and security framing.
2. **Base classification prompt** — title, document type, sender/issuer, date and document text.
3. **Tagging prompt** — tag-selection instructions and placeholders for the current taxonomy, Tag Guidance and retrieved examples.

The Tagging prompt is appended only when the active route requires an LLM tag decision. On a confident Hybrid match it is omitted entirely, and the structured output schema contains no `tags` field. **Preview prompts** shows the exact messages and schema that would be sent.

## Correspondents

The structured metadata request extracts the actual sender/issuer as free text. Local resolution first checks for a unique normalized exact match. Otherwise it compares the extracted name with current Paperless correspondents and applies a fuzzy match only when **both** the configured minimum similarity and minimum winner margin pass. Defaults are **91% similarity** and **4 percentage points winner margin**. The similarity default is intentionally slightly more permissive than the previous hard-coded 93% threshold, while the ambiguity margin stays unchanged. The controls and a read-only live tester are under **App Settings → Matching**.

The winner margin is the difference between the best and second-best similarity scores. It prevents a high score from being treated as safe when two existing correspondents are almost equally plausible. Plausible unmatched names can appear in **Paperless Document Suggestions** when the optional suggestion bridge is configured; new correspondents are never auto-created.

### Correspondent matching examples

All names below are synthetic. Scores are calculated with the same name-similarity metric used by the matcher.

| Case | Extracted sender | Best existing match | Second-best | Decision with 91% / 4 pp |
|---|---|---:|---:|---|
| Clear match | `Musterwerke Energi GmbH` | `Musterwerke Energie GmbH` · **97.87%** | `Musterwerke Netz GmbH` · 86.36% | **Match** · winner margin 11.51 pp |
| Clear winner, below similarity threshold | `Musterwerke Versorgung` | `Musterwerke Versorgung GmbH` · **89.80%** | `Musterwerke Netz GmbH` · 65.12% | **No match** · similarity is below 91% |
| High similarity, but ambiguous | `Beispielwerke Main GmbH` | `Beispielwerke Mainz GmbH` · **97.87%** | `Beispielwerke Mainau GmbH` · 95.83% | **No match** · winner margin is only 2.04 pp |

Lowering **Minimum similarity** accepts more name variation. Lowering **Minimum winner margin** accepts closer races between candidates. Raising either value makes automatic matching more conservative. Both controls support their full `0-100` range, and there is no hidden minimum-name-length gate: every plausible non-exact sender is scored. Unique normalized exact matches do not use the fuzzy thresholds.

## Control Center

The Control Center configures both automation and document-chat administration:

- Paperless and Ollama connections;
- classification queue/error/review tags;
- correspondent matching thresholds and the read-only matching tester;
- OCR language, PaddleOCR profile, image-size limit and retry/recovery behavior;
- metadata Dry Run and worker timing;
- classification model settings plus System/Base/Tagging prompts;
- Hybrid tagging / LLM direct, History health and per-tag guidance;
- global document-chat defaults, System/source/answer prompt assembly, retrieval behavior and diagnostics;
- embedding model/templates, chunking, batch/slice settings, sync interval and index Sync/Rebuild/Pause state.

The actual document chat lives inside Paperless. The Control Center owns global/admin settings; per-chat overrides stay with each server-side conversation. Saved app/classification configurations are versioned and can be restored.

## Document chat

When the Paperless UI integration is enabled, `paperless-local-ai` injects its own multi-turn document chat into Paperless without patching Paperless source files. The feature is opt-in at deployment/UI level, but document chat is part of the supported project scope rather than an external add-on.

Chats persist server-side and support scopes for the current document, all documents, tags, correspondents and document types. Per-chat controls include model/Thinking/context/generation settings plus retrieval overrides. Source links are deterministic Paperless links, and retrieved sources can include live Paperless metadata such as title, created date, correspondent and document type.

The normal heavy-work path is fixed at **one Ollama `/api/embed` request and one Ollama `/api/chat` request**. Retrieval is exact cosine search against a local SQLite index; there is no LlamaIndex refine chain, reranker LLM, query-rewrite LLM or agent loop. Index rebuilds are explicit and sliced so OCR/metadata can use the same resource-constrained machine between embedding slices.

See [RAG chat](docs/rag-chat.md) for prompt variables, retrieval/index controls, lifecycle behavior and the current defaults.

## Requirements

Paperless-ngx · Ollama · Docker Compose or TrueNAS SCALE · linux/amd64 · GPU not required

Tested reference: **Paperless-ngx 3.1.0 · OCRmyPDF 17.7.1 · TrueNAS SCALE 25.10.6 · Ollama 0.32.11**. See [Compatibility](docs/compatibility.md) for the exact tested scope.

## Install

Choose one deployment guide:

- [Docker Compose](docs/installation.md)
- [TrueNAS SCALE](docs/truenas.md)

Then complete the required [Paperless integration](docs/paperless-setup.md) and review [Configuration](docs/configuration.md).

More: [RAG chat](docs/rag-chat.md) · [Tagging](docs/tagging.md) · [Troubleshooting](docs/troubleshooting.md) · [Compatibility](docs/compatibility.md) · [Architecture](docs/architecture.md)

## Security

The Control Center has no built-in authentication. Keep it on localhost or a trusted network.

The OCR endpoint is authenticated with a separate shared token. Do not expose it directly to the public Internet.

## License

MIT for this repository's source code. Third-party components retain their own licenses; see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
