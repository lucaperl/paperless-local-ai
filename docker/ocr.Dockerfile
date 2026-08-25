FROM paddlepaddle/paddle:3.3.1

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

CMD ["python", "/app/service.py"]
