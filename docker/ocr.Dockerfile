FROM paddlepaddle/paddle:3.3.1

ARG APP_VERSION=dev
ARG SOURCE_URL=""

LABEL org.opencontainers.image.title="paperless-local-ai OCR" \
      org.opencontainers.image.description="Selective CPU-first PaddleOCR post-processing for Paperless-ngx" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

WORKDIR /app

COPY requirements/ocr.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY src/common/ /app/
COPY src/ocr/ /app/

CMD ["python", "/app/worker.py"]
