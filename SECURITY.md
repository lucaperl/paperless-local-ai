# Security policy

## Supported release line

Security fixes are currently targeted at the latest `0.1.x` release while the project is in its first public release line.

## Reporting a vulnerability

Do **not** post Paperless tokens, private document contents, unredacted OCR output or other secrets in a public issue.

If GitHub private vulnerability reporting is enabled for this repository, use **Security -> Report a vulnerability**. Otherwise open a minimal public issue that contains no sensitive exploit details/secrets and asks the maintainer for a private reporting channel.

## Deployment security assumptions

- Prompt Studio has no authentication in 0.1.0 and should be bound only to localhost or a trusted LAN.
- The suggestion bridge is an internal compatibility endpoint and should be reachable by Paperless, not exposed to the public Internet.
- `PAPERLESS_TOKEN` belongs in deployment secret/environment configuration, never in AppConfig/history or Git.
- The project has no built-in telemetry/cloud inference endpoint. Document text is sent to the operator-configured Ollama endpoint, which may itself be local or remote.
- Keep Paperless, Ollama, Docker/TrueNAS and the host OS patched independently; they are separate projects from `paperless-local-ai`.

## Dependency licensing

Security support and software licensing are separate concerns. See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for important third-party license information, including PyMuPDF in the OCR image.
