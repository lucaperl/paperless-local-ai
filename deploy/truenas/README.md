# TrueNAS Custom App files

TrueNAS is a deployment target, not a separate application fork.

Use:

- [`compose.example.yaml`](compose.example.yaml): ready-to-edit four-service Custom App template using upstream GHCR images;
- [`../../docs/truenas.md`](../../docs/truenas.md): complete installation/update guide;
- [`../../docs/paperless-setup.md`](../../docs/paperless-setup.md): required Paperless OCRmyPDF/plugin integration.

Before pasting the YAML into TrueNAS:

1. replace `/mnt/YOUR_POOL/paperless-local-ai` with the real dataset path;
2. create `paperless.env` containing both `PAPERLESS_TOKEN` and `OCR_SERVICE_TOKEN`;
3. after the app starts, mount the generated `integration` directory into Paperless and configure the matching `PLAI_OCR_*` values.

The template uses the `stable` image tag. Pin an exact release if you prefer explicit/manual version changes.
