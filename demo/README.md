# Control Center demo

The public Control Center demo is a static, browser-only build of the same UI source that ships in `core-service`.

- All Paperless documents, taxonomy values, correspondents, History entries, OCR state and model results are synthetic fixtures.
- `/api/...` calls are intercepted in the browser by `demo/mock-api.js`; no Paperless, Ollama or OCR backend is contacted.
- The generated page sets `connect-src 'none'` so browser network requests from the demo are blocked.
- Configuration changes and restore actions use browser `localStorage` only and can be cleared with **Reset demo**.
- Prompt previews are rendered from the current editable prompt draft, synthetic document text and synthetic taxonomy.
- The correspondent matching tester runs entirely in the browser against the synthetic correspondent fixture and never sends entered names anywhere. A confident Hybrid demo route omits the Tagging prompt and `tags` schema field just like the production contract.

Build locally from the repository root:

```bash
python scripts/build_demo.py --output _site/demo
```

Open `_site/demo/index.html` in a browser.

The published demo is deployed by `.github/workflows/pages-demo.yml` to:

<https://lucaperl.github.io/paperless-local-ai/demo/>
