# Control Center

The Control Center is the browser UI for connections, workflow tags, OCR, classification prompts/settings, tagging strategy, diagnostics, safe tests and configuration history.

## Where settings live

| Area | Purpose |
|---|---|
| **Overview** | connection/OCR/tagging status, pipeline and current key settings |
| **App Settings** | Paperless/Ollama connections, workflow/review tags, OCR, Dry Run and worker timing |
| **Classification → Test** | read-only prompt preview and read-only real model test against an existing Paperless document |
| **Classification → Tagging** | Hybrid/LLM-direct strategy, reviewed-history health and Tag Guidance |
| **Classification → Prompt** | editable System, Base classification and Tagging prompts |
| **Classification → Settings** | Ollama model, context/document limits and advanced model parameters |
| **History** tabs | separate saved versions for App settings and Classification settings |

The configured review tag can have any name. Paperless-side setup still matters: the review-tag lifecycle, matching algorithms, workflow and OCRmyPDF integration are documented in [Paperless setup](paperless-setup.md).

**Preview prompts** does not call Ollama. **Run model test** calls Ollama but does not modify the selected Paperless document or persist a correspondent suggestion. **Dry Run** is optional and controls automatic metadata write-back; it does not disable Paperless import/OCR.

Opening the Control Center reads cached History health plus a lightweight Paperless source signature; it does not load NumPy/SciPy/scikit-learn or rebuild the TF-IDF index. Hybrid preview/refresh can start the on-demand history helper, which is released after a short interactive idle period; a model test shuts it down before Ollama starts.

See [Configuration](configuration.md) for the full field-by-field behavior and reference performance/resource guidance.
