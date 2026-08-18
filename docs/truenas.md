# TrueNAS SCALE deployment

`paperless-local-ai` runs on TrueNAS as a **Custom App installed from Docker Compose YAML**. TrueNAS is only a deployment target: it uses the exact same GHCR images as a normal Docker installation.

The production-tested reference is **TrueNAS SCALE 25.10.4**.

## What you need before installing

- working Paperless-ngx and Ollama apps/services;
- a persistent dataset for `paperless-local-ai`;
- a Paperless API token;
- ports for Studio and the optional suggestion bridge;
- Paperless/Ollama addresses reachable from the Custom App containers.

## 1. Create one dataset

Example:

```text
/mnt/POOL/paperless-local-ai
```

The app will use:

```text
config/
core/
ocr/
coordination/
```

Do not place source code in this dataset. Source code lives in the GHCR images.

## 2. Store the Paperless token

Recommended approach: create a root-readable deployment environment file containing only the secret:

```text
/mnt/POOL/paperless-local-ai/paperless.env
```

Contents:

```text
PAPERLESS_TOKEN=your-token-here
```

Restrict it to root where practical (for example mode `600`).

If you prefer to manage the token directly in the Custom App YAML, you can replace the `env_file` entries in the template with an `environment: PAPERLESS_TOKEN: ...` value, but remember that the token will then be visible in the stored YAML/UI.

## 3. Edit the TrueNAS Compose template

Copy [`../deploy/truenas/compose.example.yaml`](../deploy/truenas/compose.example.yaml) into a text editor and replace every occurrence of:

```text
/mnt/YOUR_POOL/paperless-local-ai
```

with your real dataset path.

The template uses:

```text
ghcr.io/lucaperl/paperless-local-ai-core:stable
ghcr.io/lucaperl/paperless-local-ai-ocr:stable
```

and exposes:

```text
30148 -> Prompt Studio
30149 -> suggestion bridge
```

The template binds both ports to `0.0.0.0` so they are reachable on the TrueNAS LAN address. Prompt Studio has no authentication: only use this on a trusted network, or change the bind address to a specific trusted TrueNAS IP.

## 4. Install the Custom App

In TrueNAS:

1. open **Apps**;
2. open **Discover Apps**;
3. choose the Custom App / **Install via YAML** option;
4. name the app `paperless-local-ai`;
5. paste the edited YAML;
6. install it.

No private TrueNAS-specific image is required.

## 5. Configure runtime settings in Studio

Open:

```text
http://<truenas-ip>:30148/
```

Under **App-Einstellungen** configure:

```text
Paperless URL: http://<truenas-or-paperless-host>:<paperless-port>
Ollama URL:    http://<truenas-or-ollama-host>:<ollama-port>
```

Then configure tags/OCR/runtime settings and save.

Do not duplicate these values in the Custom App YAML. They are persistent AppConfig state and are hot-reloaded by the workers.

## 6. Prepare Paperless

Follow [paperless-setup.md](paperless-setup.md):

- create queue/error/review tags;
- create the import workflow;
- optionally configure Paperless 3.0.5 AI Suggestions to use the bridge.

For native review, Paperless must be able to reach:

```text
http://<truenas-ip>:30149
```

## 7. Resource defaults

The template matches the production-tested low-power deployment:

```text
ocr-worker:        2 CPU / 6 GiB RAM / 2 GiB shm
metadata-worker:   0.5 CPU / 512 MiB RAM
prompt-ui:          0.25 CPU / 256 MiB RAM
suggestion-bridge:  0.1 CPU / 128 MiB RAM
```

Adjust Docker-owned limits in the YAML if your system requires different values.

## 8. Normal updates — no shell script

Keep the two images on the floating non-prerelease tag:

```text
stable
```

In **Apps -> Settings**, leave **Check for docker image updates** enabled.

TrueNAS monitors images used by Custom Apps. When the upstream digest behind `stable` changes, TrueNAS can show its normal **Update** action for the Custom App. Apply the update from the TrueNAS UI.

You do **not** need a custom updater script for ordinary code/UI/worker releases.

### Exact-version alternative

If you prefer a fully pinned deployment, replace `stable` in both image names with a release such as:

```text
0.1.0
```

TrueNAS will then stay on that image tag until you edit the YAML or deliberately move to another version.

## 9. Important Custom App limitation

An image update changes container images; it does **not** rewrite the Custom App's stored Compose YAML.

If a future release changes any of these deployment contracts:

- service graph;
- commands;
- mounts;
- ports;
- required deployment environment;
- resource-related Compose fields;

review the release notes and update the YAML as part of that upgrade.

Code-only releases do not require that extra step.

## 10. First real document

After the app is healthy:

1. verify Studio connections;
2. verify Paperless technical tags/workflow;
3. import one normal document;
4. confirm OCR -> LLM -> review;
5. only then process larger batches.

## Reference files

- [`deploy/truenas/compose.example.yaml`](../deploy/truenas/compose.example.yaml)
- [Installation](installation.md)
- [Paperless setup](paperless-setup.md)
- [Updating](upgrading.md)
- [Troubleshooting](troubleshooting.md)
