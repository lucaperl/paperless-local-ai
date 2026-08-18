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

The template uses the public `stable` images and exposes Prompt Studio on port `30148` and the suggestion bridge on `30149`.

The included CPU/RAM values are conservative container limits, not measured minimum requirements.

## 3. Install the Custom App

In TrueNAS:

1. open **Apps**;
2. choose the Custom App / **Install via YAML** option;
3. name the app `paperless-local-ai`;
4. paste the edited YAML;
5. install it.

## 4. Configure through Prompt Studio

Open:

```text
http://<truenas-ip>:30148/
```

Configure Paperless/Ollama connections, tags, OCR and runtime settings in the UI, then follow [Paperless setup](paperless-setup.md).

Prompt Studio has no built-in authentication. Keep it on a trusted network or bind it to a specific trusted address.

## Updates

The supplied YAML follows the floating `stable` GHCR tag. With Docker image update checks enabled, TrueNAS can present its normal **Update** action when a new image digest is published.

If release notes mention a Compose change, update the stored Custom App YAML as part of that release. Image updates alone cannot rewrite the YAML.

For fully pinned deployments, replace `stable` in both image names with an exact release such as `0.1.0`.
