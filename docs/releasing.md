# Releasing

This document is for maintainers.

## Versioning contract

`VERSION` contains the canonical software version without a leading `v`.

For a version `X.Y.Z`:

```text
VERSION file          = X.Y.Z
GitHub Release tag    = vX.Y.Z
GHCR exact image tag  = X.Y.Z
```

The publish workflow refuses a release whose GitHub tag does not match `VERSION`.

## What the release workflow does

A published GitHub Release:

1. runs compile/unit/regression tests;
2. validates both published and development Compose configurations;
3. builds linux/amd64 `core` and `ocr` images;
4. logs into GHCR using the repository `GITHUB_TOKEN` with `packages: write`;
5. pushes exact semver tags;
6. for a non-prerelease, also moves `stable` and `latest`;
7. generates a GitHub build-provenance attestation for each image digest.

Images:

```text
ghcr.io/lucaperl/paperless-local-ai-core:<tag>
ghcr.io/lucaperl/paperless-local-ai-ocr:<tag>
```

## First-release GHCR visibility step

GitHub Container Registry packages are private by default when first published, even when repository access permissions are linked. Public TrueNAS/Docker users need anonymous pulls, so after the **first** successful publication set both packages to **Public** in GitHub package settings:

```text
paperless-local-ai-core
paperless-local-ai-ocr
```

Do this once per package. Subsequent versions use the same package visibility.

The Dockerfiles/workflow include the OCI source label so each package is linked back to this repository.

## Release checklist

1. Update `VERSION`.
2. Update `CHANGELOG.md`.
3. Update compatibility docs only when a new environment was actually tested.
4. Run:

   ```bash
   python -m compileall -q src tests scripts
   pytest -q
   docker compose -f compose.yaml config
   docker compose -f compose.yaml -f compose.dev.yaml config
   ```

5. Regenerate/check `SOURCE-MANIFEST.json` if runtime source changed.
6. Search the repository for secrets, private document contents, private IPs and host-specific paths.
7. Review `THIRD_PARTY_LICENSES.md` whenever runtime dependencies or base images change.
8. If a Mermaid source file changed, push the release commit and wait for the `render-mermaid` workflow to commit the matching SVG; pull that generated commit before creating the release.
9. Confirm the final branch contains the intended release commit(s).
10. Publish GitHub Release `v<VERSION>`.
11. Wait for both publish jobs to succeed.
12. Confirm both GHCR packages are public and anonymously pullable.
13. Deploy the exact release images to a test/production-like instance.
14. Run `doctor` and one real document end-to-end.

If validation must happen **before** `stable` moves, publish a prerelease first. A normal non-prerelease moves `stable`/`latest` during the publish workflow.

## Prereleases

GitHub prereleases receive the exact semver tag but do **not** move `stable` or `latest`.

## TrueNAS release notes

Always state whether a release is:

- **image-only / normal update**: existing Custom App YAML remains valid; or
- **deployment-contract change**: service graph, mounts, ports, commands or required deployment variables changed and the Custom App YAML must be reviewed/updated.

A new image digest cannot rewrite stored TrueNAS Custom App YAML.
