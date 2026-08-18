# paperless-local-ai

[![Tests](https://github.com/lucaperl/paperless-local-ai/actions/workflows/test.yml/badge.svg)](https://github.com/lucaperl/paperless-local-ai/actions/workflows/test.yml)

Selective OCR and local AI metadata automation for Paperless-ngx — built for small CPU-only homeservers.

`paperless-local-ai` uses **PaddleOCR** for scanned pages and a local **Ollama** model to classify title, document type, date, tags and correspondents. Normal runtime settings, prompts and tests are handled through the included **Prompt Studio** web UI.

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
Paperless review
```

Native PDF text is kept. Scan-like pages — even if they already contain an unreliable OCR text layer — are reprocessed with PaddleOCR.

The main classifier uses the existing Paperless taxonomy instead of inventing arbitrary values.

### Correspondents

The main classification pass only uses existing Paperless correspondents. If none can be resolved, an optional **second, correspondent-only LLM pass** runs:

```text
existing correspondent → apply automatically
new correspondent      → suggest for review in Paperless
```

New correspondents are never created automatically.

## Prompt Studio

The web UI controls the normal application workflow:

- Paperless and Ollama connections
- OCR settings
- queue and review tags
- classification prompt and model
- correspondent fallback prompt and model
- testing, history, polling and dry-run

## Why this project?

This project grew out of running local document AI on modest CPU-only hardware.

Two things became bottlenecks:

- **OCR quality:** on the documents that motivated this project, Tesseract OCR was often not clean enough as input for a small local LLM. Scan-like pages are therefore selectively reprocessed with PaddleOCR.
- **Inference time:** per-field LLM workflows such as the one used by `paperless-gpt` were too slow on the reference CPU because prompt processing was repeated several times per document.

`paperless-local-ai` combines title, document type, date, tags and existing correspondent classification into **one structured LLM request**. Only the unresolved-correspondent case can add a second, specialized request.

The scope is deliberately narrow: **better OCR and automatic metadata classification**. AI-heavy extras such as document chat, RAG or semantic search are left out because they add complexity and are a poor fit for the low-power hardware this project targets.

Paperless' native AI is a general suggestion feature; this project is instead designed as an automatic, queue-driven pipeline with selective OCR, constrained taxonomy values and predictable resource use.

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

More: [Configuration](docs/configuration.md) · [Troubleshooting](docs/troubleshooting.md) · [Architecture](docs/architecture.md)

## Security

Prompt Studio has no built-in authentication. Keep it on localhost or a trusted network.

## License

MIT. Third-party components retain their own licenses; see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
