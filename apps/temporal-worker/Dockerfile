FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY . .

RUN uv sync --package sentinelrag-temporal-worker --no-dev --frozen

CMD ["uv", "run", "--package", "sentinelrag-temporal-worker", "python", "-m", "sentinelrag_worker.main"]
