# Contributing

Thanks for considering a contribution.

Before changing code, read [`AGENTS.md`](AGENTS.md). It records behavior and architecture invariants that are easy to break accidentally.

## Scope

Keep changes focused on Paperless/OCRmyPDF-integrated PaddleOCR, local text-only metadata automation, configuration/operability and native human review. Do not casually turn the project into a bundled Paperless/Ollama distribution, RAG/chat system or cloud-dependent OCR service.

## Local checks

Create a Python environment and install development dependencies:

```bash
python -m pip install -r requirements/dev.txt
```

The Rust core uses the pinned Rust 1.98 toolchain from `rust-toolchain.toml`.

Then run:

```bash
cargo fmt --all -- --check
cargo check --locked --workspace --all-targets
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
python -m compileall -q src tests scripts
pytest -q
```

If Docker Compose is available:

```bash
cp .env.example .env
docker compose -f compose.yaml -f compose.dev.yaml config
```

For source-built integration testing:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
```

## Pull requests

A pull request should explain:

- the user-visible problem/change;
- why the chosen layer owns the change;
- tests performed;
- whether Paperless compatibility, Compose contracts or persistent data formats are affected.

Add regression coverage for bugs where practical.

## Privacy

Never commit or paste into issues/PRs:

- Paperless API tokens;
- real `.env` files;
- private document text/images/PDFs;
- OCR dumps from private documents;
- user-specific private IPs/host paths unless they are clearly fictional documentation examples.
