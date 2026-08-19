# Updating paperless-local-ai

The software and the instance state are deliberately separate:

```text
GitHub/GHCR images  = application software
APP_DATA_DIR         = settings, prompt history, caches and review state
```

An image update must not require copying source code into `APP_DATA_DIR`.

## Before any update

1. Read the GitHub release notes and `CHANGELOG.md`.
2. Check [Compatibility](compatibility.md), especially if Paperless itself was upgraded.
3. Back up at least `APP_DATA_DIR/config` and any open review state under `APP_DATA_DIR/core`.
4. Keep the previous image available until the new deployment passes a one-document smoke test.

## Docker Compose using `stable`

Pull and recreate from the newest non-prerelease images:

```bash
docker compose pull
docker compose up -d
docker compose --profile tools run --rm doctor
```

Then process one normal test document.

## Docker Compose pinned to an exact release

Set:

```text
APP_VERSION=<exact-release>
```

then run:

```bash
docker compose pull
docker compose up -d
docker compose --profile tools run --rm doctor
```

Pinning is useful when you want the deployment to stay reproducible until you explicitly approve the next release.

## TrueNAS Custom App using `stable`

With Docker image update checks enabled, a new digest behind `stable` can appear as the normal TrueNAS **Update** action.

Apply image-only updates from the TrueNAS UI. No custom shell updater is required.

A container image cannot rewrite the Compose YAML stored by TrueNAS. If release notes say the deployment contract changed — services, commands, mounts, ports, required environment or other Compose fields — update the stored YAML as part of the upgrade.

### Older portal label

Existing Custom Apps created from an older template may still show **Prompt UI** after an image update because `x-portals` is stored in the Custom App YAML.

If needed, change only:

```yaml
name: Prompt UI
```

to:

```yaml
name: Control Center
```

## Rollback

For an image-only release that did not migrate persistent data, redeploy the previous exact image tag:

```text
APP_VERSION=<previous-release>
```

If release notes describe a persistent-data migration, follow the release-specific rollback instructions instead of blindly downgrading.

The current 0.1.x line stores AppConfig and prompt configurations as JSON files with version history; the app does not use its own database.
