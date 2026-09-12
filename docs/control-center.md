# Control Center

The Control Center is the administration UI for `paperless-local-ai`: connections, OCR, metadata automation, tagging/history, document-chat defaults, RAG/index settings, diagnostics, safe tests and configuration history.

The actual document chat stays inside Paperless. The Control Center configures how PLAI processes documents and how the chat/index should behave.

## Where settings live

| Area | Purpose |
|---|---|
| **Overview** | connection/OCR/tagging status, pipeline and current key settings |
| **App Settings** | Paperless/Ollama connections, workflow/review tags, correspondent matching + read-only tester, OCR, Dry Run and worker timing |
| **Classification → Test** | prompt preview and read-only real model test against an existing Paperless document |
| **Classification → Tagging** | Hybrid/LLM-direct strategy, reviewed-history health and Tag Guidance |
| **Classification → Prompt** | editable System, Base classification and Tagging prompts |
| **Classification → Settings** | classification Ollama model, context/document limits and advanced model parameters |
| **Document Chat → Chat & prompts** | chat model, Thinking/context/generation settings, conversation-history depth, RAG System prompt, retrieved-source template and final answer prompt template |
| **Document Chat → Retrieval** | retrieval-history behavior, previous-user-turn window, similarity/document caps, adjacent chunks, context budget and diagnostics defaults |
| **Document Chat → Embedding & index** | embedding model/templates, dimensions/context/truncation, chunking, batch/slice size and sync interval |
| **Document Chat → Index status** | Sync, Rebuild, Pause/Resume and active/rebuild-required state |
| **History** tabs | saved versions for App settings and Classification settings |

The configured review tag can have any name. Paperless-side setup still matters: the review-tag lifecycle, matching algorithms, workflow, OCRmyPDF plugin and optional same-origin UI integration are documented in [Paperless setup](paperless-setup.md).

## CPU-first behavior

Only one heavy PLAI workload runs at a time. OCR, Hybrid-history work, metadata inference, document chat and index embedding wait for the same shared AI resource.

If chat is waiting because another heavy task is running, the UI shows what it is waiting for rather than starting another model workload in parallel.

Increasing embedding batch size, context size, output limits or OCR image size can raise RAM use or processing time. The defaults favor predictable CPU-only operation rather than running several AI workloads concurrently.

## Safe testing

**Test correspondent matching** compares a typed sender name with current Paperless correspondents using the unsaved Matching thresholds. It does not call Ollama or change Paperless.

**Preview prompts** does not call Ollama. **Run model test** calls Ollama but does not modify the selected Paperless document or persist a correspondent suggestion. **Dry Run** controls automatic metadata write-back; it does not disable Paperless import/OCR.

RAG prompt previews are synthetic and do not query the private archive. Retrieval diagnostics are generated from a real chat turn only when enabled and do not add an extra model call.

Opening the Control Center reads cached History health plus a lightweight Paperless source signature; it does not keep NumPy/SciPy/scikit-learn resident. Hybrid preview/refresh can start the on-demand history helper, which is released again before Ollama work.

See [Configuration](configuration.md) for field behavior, [RAG chat](rag-chat.md) for the document-chat pipeline, and [Troubleshooting](troubleshooting.md) for runtime symptoms.
