# Build context: repo root
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Install shared package (required by worker)
COPY packages/shared/python /packages/shared/python
RUN pip install --no-cache-dir /packages/shared/python

# 2. Copy worker source
COPY apps/temporal-worker /app

# 3. Install worker deps + install the sentinelrag_worker package itself
RUN pip install --no-cache-dir \
    "temporalio>=1.8" \
    "pydantic>=2.9" \
    "pydantic-settings>=2.5" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "asyncpg>=0.30" \
    "httpx>=0.27" \
    "structlog>=24.4" \
    "tiktoken>=0.8" \
    "hatchling" \
    && pip install --no-cache-dir -e .

RUN adduser --disabled-password --gecos "" --uid 1001 appuser \
    && chown -R appuser /app
USER 1001

CMD ["python", "-m", "sentinelrag_worker.main"]
