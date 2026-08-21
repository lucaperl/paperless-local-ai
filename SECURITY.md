# Security policy

## Supported release line

Security fixes are targeted at the latest stable release.

## Reporting a vulnerability

Do **not** post Paperless tokens, OCR service tokens, private document contents, unredacted OCR output or other secrets in a public issue.

If GitHub private vulnerability reporting is enabled for this repository, use **Security → Report a vulnerability**. Otherwise open a minimal public issue containing no sensitive exploit details/secrets and ask the maintainer for a private reporting channel.

## Deployment security assumptions

- The Control Center has no built-in authentication and should be bound only to localhost or a trusted LAN.
- The suggestion bridge is an internal compatibility endpoint and should be reachable by Paperless, not exposed to the public Internet.
- The OCR service requires `OCR_SERVICE_TOKEN`, but it is still intended for private/LAN use only.
- `PAPERLESS_TOKEN` and `OCR_SERVICE_TOKEN` belong in deployment secret/environment configuration, never in AppConfig/history or Git.
- The project has no built-in telemetry/cloud inference endpoint. Document text is sent to the operator-configured Ollama endpoint, which may itself be local or remote.
- Keep Paperless, Ollama, Docker/TrueNAS and the host OS patched independently; they are separate projects from `paperless-local-ai`.

## Dependency licensing

Security support and software licensing are separate concerns. See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for the current runtime dependency notice.
