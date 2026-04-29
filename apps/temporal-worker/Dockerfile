# SentinelRAG Temporal worker container.
# Multi-stage build using uv for fast dependency resolution.
#
# Build context: REPO ROOT (not apps/temporal-worker).
# Example:
#   docker build -f apps/temporal-worker/Dockerfile -t sentinelrag-temporal-worker:dev .

# ---- Stage 1: builder ----
FROM ghcr.io/astral-sh/uv:0.5-python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /workspace

# Workspace manifests first for cache-friendly layering.
COPY pyproject.toml uv.lock* ./
COPY apps/temporal-worker/pyproject.toml apps/temporal-worker/
COPY packages/shared/python/pyproject.toml packages/shared/python/

# Sync only the worker package and its workspace deps.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --package sentinelrag-temporal-worker || \
    uv sync --no-install-project --package sentinelrag-temporal-worker

# Source code.
COPY packages/shared/python/sentinelrag_shared packages/shared/python/sentinelrag_shared
COPY apps/temporal-worker/sentinelrag_worker apps/temporal-worker/sentinelrag_worker

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --package sentinelrag-temporal-worker || \
    uv sync --package sentinelrag-temporal-worker

# ---- Stage 2: runtime ----
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root user matches the chart's podSecurityContext.runAsUser=10001.
RUN groupadd --gid 10001 app && \
    useradd  --uid 10001 --gid app --create-home --shell /bin/bash app

COPY --from=builder --chown=app:app /opt/venv /opt/venv
COPY --from=builder --chown=app:app /workspace /workspace

WORKDIR /workspace/apps/temporal-worker

USER app

# No exposed port — the worker only initiates outbound connections to the
# Temporal frontend. Liveness is handled by the K8s Deployment's restart
# policy + Temporal's own session keep-alive.

CMD ["python", "-m", "sentinelrag_worker.main"]
