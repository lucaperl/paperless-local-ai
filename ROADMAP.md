# Roadmap

`paperless-local-ai` currently covers three local-AI workflows around Paperless: scan OCR, metadata automation and document chat/RAG. Future work should keep useful operation on modest CPU-only hardware as a primary design goal and avoid requiring multiple heavy AI workloads to run concurrently.

Near-term ideas:

- guided setup/check flow for first-time users;
- broader compatibility CI against additional Paperless 3.x releases;
- permission-aware document-chat retrieval beyond the current superuser-only UI path;
- validated ARM64 OCR image if Paddle support is practical;
- optional OpenAI-compatible text inference backend without changing the local/CPU-first scope;
- better RAG quality/performance diagnostics that do not add hidden LLM calls to the normal one-embed + one-chat path;
- richer metrics without adding another database/service.

Out of scope for now:

- bundling Paperless or Ollama;
- requiring a dedicated vector database;
- agent frameworks, autonomous tool loops or multi-stage LLM pipelines on the normal RAG path;
- automatic creation of new correspondents;
- cloud OCR/LLM dependencies by default;
- vision-LLM OCR as the primary OCR path;
- designs that require a GPU or assume multiple heavyweight models can stay resident concurrently.
