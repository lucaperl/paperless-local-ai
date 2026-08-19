> [!NOTE]
> This project has been entirely vibe-coded. It works in my setup, but it has not been thoroughly reviewed or tested. Expect bugs and use it at your own discretion.

# paperless-local-ai

[![Tests](https://github.com/lucaperl/paperless-local-ai/actions/workflows/test.yml/badge.svg)](https://github.com/lucaperl/paperless-local-ai/actions/workflows/test.yml)

**Improved OCR and automatic local-LLM metadata assignment for Paperless-ngx — built for modest CPU-only hardware.**

`paperless-local-ai` is for users who want better OCR for scanned documents and a small local LLM to automatically set **titles, document types, dates, tags and correspondents**, without running a full AI suite. It keeps the workload focused by limiting AI to these core tasks and handling the normal metadata classification in a single LLM request — useful on weaker hardware, or simply if that is all you need.

The model output is constrained to the configured Paperless taxonomy and applied directly to the document instead of only being shown as suggestions. If no existing correspondent can be matched, the optional correspondent fallback can propose a new one through Paperless' native suggestion/review flow instead of creating it automatically.

## How it works

```text
Paperless import
      ↓
PaddleOCR when needed
      ↓
Local LLM classification
      ↓
Title · Type · Date · Tags · Correspondent
      ↓
Apply metadata directly to Paperless
```

Native PDF text is kept, while scanned documents can be selectively reprocessed with PaddleOCR.

The main classifier handles title, document type, date, tags and an existing correspondent together in **one structured LLM request**.

### Correspondents

The main classification pass first tries to match an existing Paperless correspondent.

If it cannot resolve one, an optional second, correspondent-only LLM pass gets another chance to identify the sender:

```text
existing correspondent → apply automatically
new correspondent      → send to Paperless suggestion/review
```

New correspondents are only added after review in Paperless.

## Why this project?

This project started with running local document AI on modest CPU-only hardware.

Two things became bottlenecks:

- **OCR quality:** Tesseract output from scanned documents was often not clean enough as input for a small local LLM, so PaddleOCR is used where additional OCR is useful.
- **Inference time:** workflows that make a separate LLM request for every metadata field become slow on weak CPUs because the same document context has to be processed repeatedly.

`paperless-local-ai` therefore combines title, document type, date, tags and existing-correspondent classification into **one structured LLM request**. Only an unresolved correspondent can add a second, specialized request.

The scope is deliberately narrow: **OCR and automatic metadata assignment**. Document chat, RAG, semantic search and other AI-heavy features are intentionally left out.

## Control Center

The included Control Center is the web interface for configuring `paperless-local-ai`: Paperless and Ollama connections, pipeline tags, OCR and runtime settings, classification, and the correspondent fallback.

Prompts and model settings can be edited directly in the UI. Before using a change in production, you can preview the exact rendered prompt for an existing Paperless document or run a real Ollama test without modifying the document. The Control Center also shows the allowed Paperless values, structured model output and performance data.

Saved configurations are versioned and can be restored from the UI.

![paperless-local-ai Control Center](images/control-center-screenshot.png)

## Reference system

**Intel Core i3-8100 · 16 GB RAM · no GPU · qwen3.5:4b**

Real production examples:

| Task | Time |
|---|---:|
| Normal scanned document — OCR | ~112 s |
| Metadata classification | ~65 s |
| Optional correspondent fallback | ~39 s |

These are example document measurements, not performance guarantees.

## Requirements

Paperless-ngx · Ollama · Docker Compose or TrueNAS SCALE · linux/amd64

Tested with **Paperless-ngx 3.0.5**, **TrueNAS SCALE 25.10.4** and **qwen3.5:4b**. See [Compatibility](docs/compatibility.md) for the exact tested scope.

## Install

- [Docker Compose](docs/installation.md)
- [TrueNAS SCALE](docs/truenas.md)
- [Paperless setup](docs/paperless-setup.md)

More: [Control Center](docs/control-center.md) · [Configuration](docs/configuration.md) · [Troubleshooting](docs/troubleshooting.md) · [Architecture](docs/architecture.md)

## Security

The Control Center has no built-in authentication. Keep it on localhost or a trusted network.

## License

MIT. Third-party components retain their own licenses; see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
