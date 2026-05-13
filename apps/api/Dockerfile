FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*

COPY packages/ /packages/
RUN pip install --no-cache-dir /packages/shared/python 2>/dev/null || echo "shared package skipped"
RUN pip install --no-cache-dir /packages/sentinelrag-sdk/python 2>/dev/null || echo "sdk package skipped"

COPY apps/api/ /app/
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" sqlalchemy asyncpg psycopg2-binary alembic pydantic pydantic-settings httpx

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
