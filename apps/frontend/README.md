# SentinelRAG Frontend

Next.js 15 (App Router) dashboard for the SentinelRAG API.

## Layout

```
src/
  app/                  # Routes (one folder per page)
    api/auth/[...nextauth]/route.ts   # NextAuth.js handler (Keycloak | dev creds)
    dashboard/, collections/, documents/, query-playground/,
    evaluations/, prompts/, audit/, usage/, settings/
    layout.tsx, providers.tsx, globals.css
  components/
    ui/                 # Hand-rolled shadcn-style primitives (Button, Card, ...)
    layout/             # Sidebar, Topbar, PageHeader, StatusBadge
    query/              # QueryForm + TraceViewer (the headline demo surface)
  lib/
    api.ts              # Typed fetch client; throws ApiError on non-2xx
    api-types.ts        # Hand-mirrored Pydantic schemas
    auth.ts             # NextAuth.js v5 config (Keycloak prod, Credentials dev)
    use-api-client.ts   # Hook binding the client to the session token
    utils.ts            # cn(), formatDateTime(), formatNumber(), formatCurrency()

tests/unit/api.test.ts  # Vitest covering bearer auth, query params, error envelope, multipart
```

## Auth

Two paths, one client:

- **Production / cloud**: NextAuth issues a session backed by a Keycloak OIDC
  flow. The session callback persists `account.access_token` so server-side
  code can forward it to FastAPI (which validates against the same Keycloak
  JWKS).
- **Local dev**: set `AUTH_DEV_BYPASS=true` to expose a `Credentials`
  provider that mints a session using `NEXT_PUBLIC_DEV_TOKEN`. Both halves
  must be aligned with the backend's `AUTH_ALLOW_DEV_TOKEN` /
  `ENVIRONMENT=local` gate (see AGENTS.md "Local dev: skipping Keycloak").

If the user is anonymous (no session) and `NEXT_PUBLIC_DEV_TOKEN` is set,
the API client falls back to that token for friction-free local smoke tests.

## API client

`lib/api.ts` is a thin typed wrapper around `fetch` that:

- Reads `NEXT_PUBLIC_API_BASE_URL` server-side and uses `/api` (proxied via
  `next.config.mjs` `rewrites()`) in the browser.
- Forwards an explicit `Bearer` token (from session or dev fallback).
- Unwraps the FastAPI error envelope into a typed `ApiError` with `status`,
  `code`, `message`, `details`.
- Returns typed responses pinned to `lib/api-types.ts`.

`useApiClient()` proxies every method to inject the session token, so React
components don't pass it manually.

## Headline surface

`/query-playground` is the demo:

1. Pick collections (RBAC-aware — backend filters at retrieval time).
2. Pose a question.
3. See the generated answer with cited chunks.
4. Expand the trace to inspect every retrieval stage (BM25 → vector → hybrid
   merge → rerank), latency, token counts, cost, and grounding score.

## Scripts

```bash
cd apps/frontend
npm install
npm run dev          # http://localhost:3000 (proxies /api → :8000/api/v1)
npm run build
npm run typecheck
npm run lint
npm test             # vitest
npm run test:e2e     # playwright (e2e suite is a stub today)
```

## Environment

Copy `.env.example` to `.env.local`; the defaults work against `make up` +
`make seed`.
