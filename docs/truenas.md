# TrueNAS SCALE

`paperless-local-ai` runs as a TrueNAS **Custom App installed from Docker Compose YAML** and uses the same public GHCR images as a normal Docker deployment.

Tested reference: **TrueNAS SCALE 25.10.6**.

## Before you start

You need:

- working Paperless-ngx and Ollama services;
- an installed Ollama model (`qwen3.5:4b` is the default);
- a persistent TrueNAS dataset;
- a Paperless API token;
- a random OCR service token;
- the ability to add the OCRmyPDF plugin mount/environment to the Paperless app.

## 1. Create the app dataset and secrets

Create a persistent dataset, for example:

```text
/mnt/POOL/paperless-local-ai
```

Create:

```text
/mnt/POOL/paperless-local-ai/paperless.env
```

with:

```text
PAPERLESS_TOKEN=your-paperless-api-token
OCR_SERVICE_TOKEN=your-random-ocr-service-token
```

Generate the OCR token with a cryptographically random value, for example:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Restrict the file to root where practical, for example mode `600`.

## 2. Prepare the Custom App YAML

Copy [`deploy/truenas/compose.example.yaml`](../deploy/truenas/compose.example.yaml) and replace every occurrence of:

```text
/mnt/YOUR_POOL/paperless-local-ai
```

with your real dataset path.

The template uses the public `stable` images and exposes:

```text
30148  Control Center
30149  Suggestion bridge
30150  OCR service
```

Keep all three endpoints on a trusted LAN. The OCR service is token-authenticated but is not intended to be Internet-facing.

## 3. Install the Custom App

In TrueNAS:

1. open **Apps**;
2. choose the Custom App / install-from-YAML flow;
3. name the app `paperless-local-ai`;
4. paste the edited YAML;
5. install it.

The four long-running services are:

```text
ocr-service
metadata-worker
prompt-ui
suggestion-bridge
```

## 4. Configure the Control Center

Open the **Control Center** portal or:

```text
http://<truenas-ip>:30148/
```

The Control Center has no built-in authentication.

For Paperless and Ollama URLs, use addresses reachable from inside the app containers, normally the TrueNAS LAN address plus the published app ports.

Run **Test connections with current draft** before saving.

## 5. Integrate PaddleOCR into Paperless/OCRmyPDF

The OCR service writes:

```text
/mnt/POOL/paperless-local-ai/integration/ocrmypdf_plai.py
```

Mount the integration directory into the Paperless container read-only:

```text
Host path:
  /mnt/POOL/paperless-local-ai/integration

Container path:
  /opt/paperless-local-ai

Read-only:
  yes
```

Then add these environment values to Paperless:

```text
PLAI_OCR_URL=http://<truenas-ip>:30150
PLAI_OCR_TOKEN=<same value as OCR_SERVICE_TOKEN>
PLAI_OCR_TIMEOUT_SECONDS=1800
PAPERLESS_OCR_USER_ARGS={"plugins":["/opt/paperless-local-ai/ocrmypdf_plai.py"],"pdf_renderer":"fpdf2","optimize":0}
```

Redeploy/restart Paperless after changing its mounts/environment.

For scanned pages that need OCR, OCRmyPDF calls the plugin and PaddleOCR performs OCR inference instead of Tesseract.

The OCR language configured in Paperless must correspond to **App Settings → OCR** in the Control Center.

See [Paperless setup](paperless-setup.md) for details and the tested OCR contract.

## 6. Configure the Paperless metadata workflow

Create the required metadata/review tags and a **Document Added** workflow that assigns the `LLM` queue tag.

OCR does not use a separate PaddleOCR queue tag. It happens inside Paperless import before the metadata workflow.

## 7. Test one document

Use a scanned PDF you can verify.

Expected:

```text
Paperless import
→ OCRmyPDF calls local PaddleOCR / PP-OCRv6
→ searchable archive / extracted content
→ Document Added workflow adds LLM
→ metadata classification
→ Inbox
```

Verify the original, archive/searchable text and metadata before processing normal documents.

## Resources

The published OCR reference limits are:

```text
CPU:           4
RAM:           7 GiB
shared memory: 2 GiB
idle timeout:  5 s
HPI/OpenVINO:  enabled
CPU threads:   4
```

These are the tested reference settings, not minimum requirements.

On the reference Intel Core i3-8100, HPI/OpenVINO reduced warm PP-OCRv6 inference for a 300-DPI page from approximately **15.8 seconds to 10.7 seconds**. Complete live OCR of a cached page is typically around **15–25 seconds** depending on surrounding OCRmyPDF/PDF processing.

## Updates

The supplied YAML follows the floating `stable` GHCR tag. TrueNAS can present its normal image update when that digest changes.

A container image cannot rewrite stored Custom App YAML or Paperless' app configuration. If release notes mention a deployment-contract change, update the stored YAML/mounts/environment as part of that release.

For pinned deployments, replace `stable` in both image names with the exact release.

