# Roadmap

Near-term ideas after the first external installations:

- system/status page in Prompt Studio (Paperless, Ollama, OCR, queue/tag readiness);
- guided setup/check flow for first-time users;
- compatibility CI against additional Paperless 3.x releases;
- configurable UI language / English UI;
- validated ARM64 OCR image if Paddle support is practical;
- optional OpenAI-compatible text inference backend without changing the CPU-first scope;
- richer metrics without adding a database.

Out of scope for now:

- bundled Ollama;
- RAG/document chat;
- automatic creation of new correspondents;
- cloud OCR/LLM dependencies by default;
- vision-LLM OCR as the primary path.
