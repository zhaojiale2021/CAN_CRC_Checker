FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CRC_CHECKER_DATA_DIR=/data
WORKDIR /app

# The committed frontend build is bundled by the Python package; Node is not
# needed to build or run the container image.
COPY . .
RUN python -m pip install --no-cache-dir '.[web]'

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/limits', timeout=3)" || exit 1

CMD ["uvicorn", "webapp.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
