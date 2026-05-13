FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY . .
RUN uv sync --package sentinelrag-retrieval-service --no-dev
EXPOSE 8020
CMD ["uv", "run", "--package", "sentinelrag-retrieval-service", "uvicorn", "sentinelrag_retrieval_service.main:app", "--host", "0.0.0.0", "--port", "8020"]
