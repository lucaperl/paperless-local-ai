# TrueNAS SCALE

`paperless-local-ai` runs as a TrueNAS **Custom App installed from Docker Compose YAML**. It uses the same public GHCR images as a normal Docker deployment.

Tested reference: **TrueNAS SCALE 25.10.4**.

## Before you start

You need:

- working Paperless-ngx and Ollama services;
- an Ollama model installed (`qwen3.5:4b` is the default);
- a persistent TrueNAS dataset;
- a Paperless API token.

Fresh installations use English OCR and English prompt defaults. OCR language and the two prompt stages can be changed independently in the Control Center.

## 1. Create the Paperless token and app dataset

In Paperless, create an API token under **My Profile**. The token's user must be allowed to read and update the documents and taxonomy the app should manage.

Create a persistent dataset, for example:

```text
/mnt/POOL/paperless-local-ai
```

Inside it, create:

```text
/mnt/POOL/paperless-local-ai/paperless.env
```

with:

```text
PAPERLESS_TOKEN=your-token-here
```

Restrict the file to root where practical, for example mode `600`.

## 2. Prepare the YAML

Copy [`deploy/truenas/compose.example.yaml`](../deploy/truenas/compose.example.yaml) and replace every occurrence of:

```text
/mnt/YOUR_POOL/paperless-local-ai
```

with your dataset path.

The template uses the public `stable` images, exposes the Control Center on port `30148` and the suggestion bridge on `30149`, and declares a TrueNAS portal named **Control Center**.

The included CPU/RAM values are conservative container limits, not measured minimum requirements.

## 3. Install the Custom App

In TrueNAS:

1. open **Apps**;
2. choose the Custom App / **Install via YAML** option;
3. name the app `paperless-local-ai`;
4. paste the edited YAML;
5. install it.

All four long-running services start together. Until the required Paperless tags exist, the workers may log missing-tag errors; no document is queued until the queue tag is present.

## 4. Configure the Control Center

Open the **Control Center** portal from the TrueNAS app details page, or browse to:

```text
http://<truenas-ip>:30148/
```

The Control Center has no built-in authentication. Keep it on a trusted network.

### Choose reachable Paperless and Ollama URLs

Do not use `localhost` for Paperless or Ollama. Inside the app container, `localhost` means that container itself.

Typical TrueNAS setups use the TrueNAS host's LAN address plus each app's published port, for example:

```text
http://<truenas-ip>:<paperless-port>
http://<truenas-ip>:<ollama-port>
```

If Paperless or Ollama runs on another host, use that host's LAN address instead.

Under **App Settings → Connections**, enter both URLs and run **Test connections with current draft** before saving. Then review pipeline tags, OCR settings, runtime settings, Classification and Correspondent fallback.

## 5. Configure Paperless

Follow [Paperless setup](paperless-setup.md) to create the required tags and import workflow.

The tag names in Paperless must exactly match the names saved in the Control Center.

## 6. Test one document

First use the Control Center's Classification and Correspondent fallback Preview/Test actions. Those interactive tests do not modify the selected document.

For the first automatic pipeline test, use one document you can verify:

- add the configured OCR queue tag manually to an existing document; or
- import a new document after the Paperless workflow is enabled.

If you enable **Dry Run**, read the exact behavior in [Configuration](configuration.md): metadata writes are suppressed, but workflow tags still move and OCR may still update Paperless' extracted content.

## Updates

The supplied YAML follows the floating `stable` GHCR tag. With Docker image update checks enabled, TrueNAS can present its normal **Update** action when a new image digest is published.

Image-only updates keep the stored Custom App YAML unchanged. If release notes mention a Compose-contract change, update that YAML as part of the release.

For pinned deployments, replace `stable` in both image names with the exact release you want to run.

See [Updating paperless-local-ai](upgrading.md) for update and rollback details.
