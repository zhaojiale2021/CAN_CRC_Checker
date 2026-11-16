# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src

# Build a wheel from the checkout. The committed frontend dist is bundled into
# the wheel, so Node is not needed in the image.
COPY . .
RUN python -m pip install --upgrade pip \
    && python -m pip wheel --wheel-dir /wheels ".[web,mf4]"


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CRC_CHECKER_DATA_DIR=/data \
    CRC_CHECKER_PROJECTS_DIR=/app/examples

ARG GIT_COMMIT=""
ENV CRC_GIT_COMMIT=${GIT_COMMIT}

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels \
        "crc-checker[web,mf4]" \
    && rm -rf /wheels

# Demo project (synthetic data only) so the catalog is not empty.
COPY --from=builder /src/examples /app/examples

# Run as a non-root user; /data is the writable runtime store.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; req = urllib.request.Request('http://127.0.0.1:8000/api/limits', headers={'X-API-Token': os.environ.get('CRC_WEB_API_TOKEN', '')}); urllib.request.urlopen(req, timeout=3)" || exit 1

CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
