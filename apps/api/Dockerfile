FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv hatchling

COPY packages/ /app/packages/
RUN pip install --no-cache-dir /app/packages/shared/python && echo "shared installed"
RUN pip install --no-cache-dir /app/packages/sentinelrag-sdk/python 2>/dev/null && echo "sdk installed" || echo "sdk not found"

COPY apps/api/ .

RUN uv pip install --system \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.32" \
    "pydantic[email]>=2.9" \
    "pydantic-settings>=2.5" \
    "sqlalchemy[asyncio]>=2.0.36" \
    "asyncpg>=0.30" \
    "psycopg[binary]>=3.2" \
    "alembic>=1.14" \
    "redis>=5.2" \
    "httpx>=0.27" \
    "python-multipart>=0.0.18" \
    "python-jose[cryptography]>=3.3" \
    "structlog>=24.4" \
    "temporalio>=1.8" \
    "pgvector>=0.3" \
    "email-validator>=2.0" \
    "tiktoken>=0.8" \
    "tenacity>=9.0"

# Verify alembic.ini is present at build time — fail fast if missing
RUN test -f alembic.ini || (echo "❌ alembic.ini not found! Contents:" && ls -la && exit 1)
RUN echo "✅ alembic.ini found at $(pwd)/alembic.ini"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
