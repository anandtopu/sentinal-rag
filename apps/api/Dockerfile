FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*

COPY packages/ /packages/
RUN pip install --no-cache-dir /packages/shared/python 2>/dev/null || echo "shared package skipped"
RUN pip install --no-cache-dir /packages/sentinelrag-sdk/python 2>/dev/null || echo "sdk package skipped"

COPY apps/api/ /app/

# Canonical hand-written migration chain (repo-root migrations/, 0001→NNNN).
# The Helm pre-upgrade Job runs `cd /workspace && alembic -c migrations/alembic.ini
# upgrade head`, so the chain must live at /workspace/migrations in the image
# (BACKLOG B11). This is the single source of truth — there is no apps/api copy.
COPY migrations/ /workspace/migrations/

# Runtime uses asyncpg; alembic's env.py resolves the sync URL to the psycopg
# (psycopg3) dialect, so psycopg[binary] must be present for the migration Job.
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" sqlalchemy asyncpg "psycopg[binary]" alembic pydantic pydantic-settings httpx

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
