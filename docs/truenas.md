# TrueNAS SCALE

`paperless-local-ai` runs as a TrueNAS **Custom App installed from Docker Compose YAML**. It uses the same public GHCR images as a normal Docker deployment.

Tested reference: **TrueNAS SCALE 25.10.4**.

## Before you start

You need working Paperless-ngx and Ollama services, a persistent dataset and a Paperless API token.

## 1. Create the app dataset

Example:

```text
/mnt/POOL/paperless-local-ai
```

Create a token file:

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

The template uses the public `stable` images, exposes the Control Center on port `30148` and the suggestion bridge on `30149`, and declares a TrueNAS portal named **Control Center** for direct access from the app details page.

The included CPU/RAM values are conservative container limits, not measured minimum requirements.

## 3. Install the Custom App

In TrueNAS:

1. open **Apps**;
2. choose the Custom App / **Install via YAML** option;
3. name the app `paperless-local-ai`;
4. paste the edited YAML;
5. install it.

## 4. Configure through the Control Center

Open the **Control Center** portal from the TrueNAS app details page, or browse to:

```text
http://<truenas-ip>:30148/
```

Configure and test the Paperless/Ollama connections, then review tags, OCR and runtime settings in the UI. Preview and test both LLM stages before production use, then follow [Paperless setup](paperless-setup.md).

The Control Center has no built-in authentication. Keep it on a trusted network or bind it to a specific trusted address.

## Updates

The supplied YAML follows the floating `stable` GHCR tag. With Docker image update checks enabled, TrueNAS can present its normal **Update** action when a new image digest is published.

Image-only updates keep the stored Custom App YAML unchanged. If release notes mention a Compose change, update that YAML as part of the release.

Existing installations created from an older template may still show a **Prompt UI** portal button even after the application itself has been updated. Edit the stored Custom App YAML once and change only the `x-portals` entry from `name: Prompt UI` to `name: Control Center`.

For fully pinned deployments, replace `stable` in both image names with an exact release such as `0.1.1`.
