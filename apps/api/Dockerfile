# Build context: repo root

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/shared/python /packages/shared/python
COPY packages/sentinelrag-sdk/python /packages/sentinelrag-sdk/python

RUN pip install --no-cache-dir /packages/shared/python \
    && pip install --no-cache-dir /packages/sentinelrag-sdk/python 2>/dev/null || true

COPY apps/api /app

RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "asyncpg>=0.30" \
    "psycopg2-binary" \
    "alembic>=1.14" \
    "pydantic>=2.9" \
    "pydantic-settings>=2.5" \
    "httpx>=0.27" \
    "python-jose[cryptography]>=3.3"

RUN adduser --disabled-password --gecos "" --uid 1001 appuser \
    && chown -R appuser /app
USER 1001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
