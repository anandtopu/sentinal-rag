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

# 1. Install build backend first
RUN pip install --no-cache-dir hatchling

# 2. Install shared package (sentinelrag-shared)
COPY packages/shared/python /packages/shared/python
RUN pip install --no-cache-dir /packages/shared/python

# 3. Install api package (sentinelrag-api) — worker depends on it
COPY apps/api /packages/api
RUN pip install --no-cache-dir --no-deps /packages/api

# 4. Copy worker source and install deps
COPY apps/temporal-worker /app
RUN pip install --no-cache-dir \
    "temporalio>=1.8" \
    "pydantic>=2.9" \
    "pydantic-settings>=2.5" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "asyncpg>=0.30" \
    "httpx>=0.27" \
    "structlog>=24.4" \
    "tiktoken>=0.8"

# 5. Install the worker package itself (registers sentinelrag_worker module)
RUN pip install --no-cache-dir --no-deps -e .

RUN adduser --disabled-password --gecos "" --uid 1001 appuser \
    && chown -R appuser /app
USER 1001

CMD ["python", "-m", "sentinelrag_worker.main"]
