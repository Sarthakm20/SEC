FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libxml2 libxslt1.1 && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt pyproject.toml ./
RUN pip install --upgrade pip && pip install -r requirements.lock.txt

COPY app ./app
COPY evaluation ./evaluation
COPY tests ./tests

RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser

# model weights are downloaded on first use into the data volume
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
