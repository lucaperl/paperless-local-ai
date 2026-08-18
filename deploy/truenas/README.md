# TrueNAS Custom App files

TrueNAS is a deployment target, not a separate application fork.

Use:

- [`compose.example.yaml`](compose.example.yaml): ready-to-edit four-service Custom App template using upstream GHCR images;
- [`../../docs/truenas.md`](../../docs/truenas.md): complete installation/update guide.

Before pasting the YAML into TrueNAS, replace `/mnt/YOUR_POOL/paperless-local-ai` with the real dataset path and create the referenced `paperless.env` containing `PAPERLESS_TOKEN`.

The template deliberately uses the `stable` image tag so TrueNAS' normal Custom App image-update detection can be used for code-only releases. Pin an exact release tag if you prefer manual version changes.
