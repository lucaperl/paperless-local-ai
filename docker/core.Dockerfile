FROM python:3.14-slim-bookworm

ARG APP_VERSION=dev
ARG SOURCE_URL=""

LABEL org.opencontainers.image.title="paperless-local-ai core" \
      org.opencontainers.image.description="Lightweight local metadata automation and native correspondent review for Paperless-ngx" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.source="${SOURCE_URL}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements/core.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY src/common/ /app/
COPY src/core/ /app/

CMD ["python", "/app/worker.py"]
