FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY . .
RUN uv sync --package sentinelrag-evaluation-service --no-dev
EXPOSE 8040
CMD ["uv", "run", "--package", "sentinelrag-evaluation-service", "uvicorn", "sentinelrag_evaluation_service.main:app", "--host", "0.0.0.0", "--port", "8040"]
