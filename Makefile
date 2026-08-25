.PHONY: test compile rust compose-config dev-up dev-down doctor manifest

compile:
	python -m compileall -q src tests scripts

rust:
	cargo fmt --all -- --check
	cargo check --locked --workspace --all-targets
	cargo test --locked --workspace
	cargo clippy --locked --workspace --all-targets -- -D warnings

test: compile rust
	pytest -q

compose-config:
	docker compose -f compose.yaml config >/dev/null
	docker compose -f compose.yaml -f compose.dev.yaml config >/dev/null

dev-up:
	docker compose -f compose.yaml -f compose.dev.yaml up -d --build

dev-down:
	docker compose -f compose.yaml -f compose.dev.yaml down

doctor:
	docker compose --profile tools run --rm doctor

manifest:
	python scripts/source-manifest.py
