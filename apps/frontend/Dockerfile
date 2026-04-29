# SentinelRAG frontend container.
# Multi-stage Next.js 15 build with standalone output (next.config.mjs has
# output: 'standalone'), so the runtime image only needs node + the
# .next/standalone directory + .next/static + public/.
#
# Build context: apps/frontend  (not the repo root — the frontend doesn't
# share node_modules with anything else).
# Example:
#   docker build -t sentinelrag-frontend:dev apps/frontend

# ---- Stage 1: deps ----
FROM node:20-bookworm-slim AS deps
WORKDIR /app

# package.json + lockfile first for cache-friendly layering.
COPY package.json package-lock.json ./
RUN npm ci --include=dev

# ---- Stage 2: builder ----
FROM node:20-bookworm-slim AS builder
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ---- Stage 3: runtime ----
FROM node:20-bookworm-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user matches the chart's podSecurityContext.runAsUser=10001.
RUN groupadd --gid 10001 app && \
    useradd  --uid 10001 --gid app --create-home --shell /bin/bash app

# Pull the standalone output (server.js + minimal node_modules) plus
# static assets and public/.
COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static
COPY --from=builder --chown=app:app /app/public ./public

USER app

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
