FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir hatchling uv

COPY packages /app/packages
COPY apps/api /app/apps/api
COPY apps/temporal-worker /app/apps/temporal-worker

RUN pip install --no-cache-dir /app/packages/shared/python
RUN if [ -d /app/packages/sentinelrag-sdk/python ]; then pip install --no-cache-dir /app/packages/sentinelrag-sdk/python; fi
RUN pip install --no-cache-dir /app/apps/api
RUN pip install --no-cache-dir -e /app/apps/temporal-worker

RUN useradd -m -u 10001 appuser
USER appuser

WORKDIR /app/apps/temporal-worker

CMD ["python", "-m", "sentinelrag_worker.main"]
