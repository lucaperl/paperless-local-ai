FROM rust:1.98.0-bookworm AS healthcheck-builder

WORKDIR /src

RUN rustup target add x86_64-unknown-linux-musl

COPY rust/core/src/healthcheck_probe.rs rust/core/src/healthcheck_probe.rs
COPY rust/core/src/bin/plai-healthcheck.rs rust/core/src/bin/plai-healthcheck.rs

RUN rustc \
      --edition=2024 \
      --target x86_64-unknown-linux-musl \
      -C opt-level=s \
      -C strip=symbols \
      -C panic=abort \
      -C target-feature=+crt-static \
      -o /plai-healthcheck \
      rust/core/src/bin/plai-healthcheck.rs


FROM paddlepaddle/paddle:3.2.2

ARG APP_VERSION=dev
ARG SOURCE_URL=""

LABEL org.opencontainers.image.title="paperless-local-ai OCR" \
      org.opencontainers.image.description="PaddleOCR service for OCRmyPDF/Paperless-ngx integration" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PADDLE_PDX_CACHE_HOME=/ocr-data/.paddlex \
    PADDLE_PDX_CPU_NUM_THREADS=4 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

WORKDIR /app

COPY requirements/ocr.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

RUN paddlex --install paddle2onnx -y \
    && paddlex --install hpi-cpu -y

COPY src/common/ /app/
COPY src/ocr/ /app/
COPY --from=healthcheck-builder /plai-healthcheck /usr/local/bin/plai-healthcheck

CMD ["python", "/app/service.py"]
