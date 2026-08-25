FROM rust:1.98.0-bookworm AS rust-builder

WORKDIR /src

COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY rust/core/ rust/core/
COPY src/core/prompt_ui.py src/core/prompt_ui.py

RUN cargo build --locked --release -p plai-core --bin plai-core --bin plai-healthcheck

FROM python:3.14-slim-bookworm

ARG APP_VERSION=dev
ARG SOURCE_URL=""

LABEL org.opencontainers.image.title="paperless-local-ai core" \
      org.opencontainers.image.description="Lightweight Rust metadata automation and native correspondent review for Paperless-ngx" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV APP_VERSION="${APP_VERSION}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements/core.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# The persistent runtime is Rust. Python remains only for the disposable
# scikit-learn History helper, the one-shot doctor command and compatibility
# standalone entry points. None of these keeps Python resident in normal use.
COPY src/common/ /app/
COPY src/core/ /app/
COPY --from=rust-builder /src/target/release/plai-core /usr/local/bin/plai-core
COPY --from=rust-builder /src/target/release/plai-healthcheck /usr/local/bin/plai-healthcheck

# Compatibility for stored 0.3.4 TrueNAS/Compose commands. execv replaces the
# short-lived Python shim with the Rust process, so Python does not stay resident.
RUN printf '%s\n' \
      'import os' \
      'os.execv("/usr/local/bin/plai-core", ["/usr/local/bin/plai-core"])' \
      > /app/core_service.py

CMD ["/usr/local/bin/plai-core"]
