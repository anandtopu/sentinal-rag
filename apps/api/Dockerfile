# SentinelRAG API service container.
# Multi-stage build using uv for fast dependency resolution.
#
# Build context: REPO ROOT (not apps/api). The compose / CI build commands set this.
# Example:
#   docker build -f apps/api/Dockerfile -t sentinelrag-api:dev .

# ---- Stage 1: builder ----
FROM ghcr.io/astral-sh/uv:0.5-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /workspace

# Copy workspace manifests first for cached dependency resolution.
COPY pyproject.toml uv.lock* ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/shared/python/pyproject.toml packages/shared/python/
COPY packages/sentinelrag-sdk/python/pyproject.toml packages/sentinelrag-sdk/python/

# Sync only the API package + its workspace deps (sentinelrag-shared).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --package sentinelrag-api || \
    uv sync --no-install-project --package sentinelrag-api

# Copy source code AFTER deps are resolved so a code-only change doesn't bust
# the dependency layer.
COPY packages/shared/python/sentinelrag_shared packages/shared/python/sentinelrag_shared
COPY apps/api/app apps/api/app

# Migrations live at the repo root and are needed at runtime (the Helm
# chart's pre-upgrade Job runs `alembic upgrade head` against this image).
COPY migrations migrations

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package sentinelrag-api || \
    uv sync --package sentinelrag-api

# ---- Stage 2: runtime ----
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Run as non-root.
RUN groupadd --gid 10001 app && \
    useradd  --uid 10001 --gid app --create-home --shell /bin/bash app

# Pull the resolved venv from the builder.
COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --from=builder --chown=app:app /workspace /workspace

WORKDIR /workspace/apps/api

USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health').read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
