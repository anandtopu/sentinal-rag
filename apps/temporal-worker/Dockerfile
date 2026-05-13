FROM python:3.12-slim

WORKDIR /app

# Install shared package (requires Python >=3.12)
COPY packages/ packages/
RUN pip install --no-cache-dir packages/shared/python

# Copy worker app code
COPY apps/temporal-worker/ .

# Install worker-specific dependencies
RUN pip install --no-cache-dir \
    asyncpg \
    httpx \
    pydantic \
    pydantic-settings \
    temporalio

CMD ["python", "-m", "sentinelrag_worker.main"]
