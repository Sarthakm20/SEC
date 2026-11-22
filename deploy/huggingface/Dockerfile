# Single-container demo for Hugging Face Spaces (Docker SDK, free CPU tier).
#   Next.js UI on :7860 (the port Spaces exposes)  ──/api/*──►  FastAPI on 127.0.0.1:8000
# Build context: the repository root (see deploy/huggingface/push_space.sh).
# The ingested data snapshot (SQLite + embedded Qdrant) is copied from deploy/huggingface/data/;
# model weights (~1.2 GB) download from the Hugging Face hub on first start.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV BACKEND_URL=http://127.0.0.1:8000 NEXT_OUTPUT=standalone NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 NEXT_TELEMETRY_DISABLED=1 \
    DATA_DIR=/app/data LLM_PROVIDER=offline RATE_LIMIT_PER_MINUTE=20 \
    CORS_ORIGINS='["http://localhost:7860"]'
RUN apt-get update && apt-get install -y --no-install-recommends libxml2 libxslt1.1 && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node

# Spaces run the container as uid 1000
RUN useradd --create-home --uid 1000 user
WORKDIR /app
COPY backend/requirements.lock.txt ./
RUN pip install --upgrade pip && pip install -r requirements.lock.txt
COPY backend/app ./app
COPY backend/evaluation ./evaluation
COPY --from=web /web/.next/standalone ./web
COPY --from=web /web/.next/static ./web/.next/static
COPY deploy/huggingface/data ./data
COPY deploy/huggingface/start.sh ./start.sh
RUN chmod +x start.sh && chown -R user:user /app
USER user

EXPOSE 7860
CMD ["./start.sh"]
