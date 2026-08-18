# Updating paperless-local-ai

The software and the instance state are deliberately separate:

```text
GitHub/GHCR images  = application software
APP_DATA_DIR         = your settings, prompt history, caches and review state
```

An image update must not require copying source code into `APP_DATA_DIR`.

## Before any update

1. Read the GitHub release notes and `CHANGELOG.md`.
2. Check [compatibility.md](compatibility.md), especially if Paperless itself was upgraded.
3. Back up at least `APP_DATA_DIR/config` and any open review state under `APP_DATA_DIR/core`.
4. Do not delete the old image until the new deployment has passed a one-document smoke test.

## Docker Compose using `stable`

Pull and recreate from the newest non-prerelease images:

```bash
docker compose pull
docker compose up -d
```

Then run:

```bash
docker compose --profile tools run --rm doctor
```

and process one normal test document.

## Docker Compose pinned to an exact release

Change:

```text
APP_VERSION=0.1.0
```

to the desired version, then:

```bash
docker compose pull
docker compose up -d
```

Pinning is recommended when you want every deployment to stay reproducible until you explicitly approve the next release.

## TrueNAS Custom App using `stable`

TrueNAS can monitor image updates for Custom Apps. With **Check for docker image updates** enabled, a new digest behind `stable` can appear as the normal TrueNAS **Update** action.

Apply it from the TrueNAS UI. No custom shell updater is required for an image-only release.

The current TrueNAS template declares the app portal as **Control Center**. Existing Custom Apps keep the `x-portals` metadata stored in their YAML, so an older installation may still show **Prompt UI** after an image update. In that case edit the stored YAML once and change only:

```yaml
name: Prompt UI
```

to:

```yaml
name: Control Center
```

## Compose-contract changes

A container image cannot change the Compose YAML already stored by Docker/TrueNAS.

If release notes say the deployment contract changed (services, commands, mounts, ports, required environment or other Compose fields), update the Compose definition as part of the upgrade instead of relying only on an image refresh.

The project treats such changes as operator-visible upgrade work and documents them explicitly.

## Rollback

If an update fails before it changes persistent data formats, redeploy the previous exact image tag, for example:

```text
APP_VERSION=0.1.0
```

If release notes describe a persistent-data migration, follow the release-specific rollback instructions instead of blindly downgrading.

For 0.1.x, AppConfig and prompt configs are JSON files with version history; the app does not use a database of its own.
