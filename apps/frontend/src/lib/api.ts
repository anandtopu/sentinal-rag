/**
 * Typed fetch client for the SentinelRAG API.
 *
 * Auth strategy:
 *   - Server-side (RSC, route handlers, getToken in NextAuth): pass an explicit
 *     bearer token via the optional `token` argument.
 *   - Client-side: tokens come from `useSession()` and are forwarded by the
 *     `useApiClient()` hook in `lib/use-api-client.ts`.
 *   - Local dev: NEXT_PUBLIC_DEV_TOKEN is read as a fallback. The backend's
 *     dev-token bypass is gated by ENVIRONMENT=local + AUTH_ALLOW_DEV_TOKEN.
 *
 * In dev, `next.config.mjs` rewrites `/api/*` → backend, so we hit relative
 * paths from the browser and avoid CORS.
 */

import type {
  Collection,
  CollectionCreate,
  DocumentRow,
  DocumentUploadResponse,
  EvaluationCase,
  EvaluationDataset,
  EvaluationRun,
  EvaluationRunResults,
  IngestionJob,
  Page,
  PromptTemplate,
  PromptVersion,
  QueryRequest,
  QueryResponse,
  QueryTraceResponse,
  Tenant,
  User,
} from './api-types';

const API_BASE: string =
  typeof window === 'undefined'
    ? (process.env.API_BASE_URL ??
      process.env.NEXT_PUBLIC_API_BASE_URL ??
      process.env.NEXT_PUBLIC_API_URL ??
      'http://localhost:8000/api/v1')
    : (process.env.NEXT_PUBLIC_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_URL ?? '/api');

const DEV_TOKEN: string | undefined = process.env.NEXT_PUBLIC_DEV_TOKEN;

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface RequestOpts {
  token?: string;
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
}

async function request<T>(method: string, path: string, opts: RequestOpts = {}): Promise<T> {
  const url = new URL(
    path.startsWith('http') ? path : `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`,
    typeof window === 'undefined' ? 'http://internal' : window.location.origin,
  );
  if (opts.query) {
    for (const [k, v] of Object.entries(opts.query)) {
      if (v !== undefined && v !== null && v !== '') {
        url.searchParams.set(k, String(v));
      }
    }
  }

  const headers: Record<string, string> = {};
  const token = opts.token ?? DEV_TOKEN;
  if (token) headers.Authorization = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (opts.formData) {
    body = opts.formData;
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }

  const res = await fetch(url.toString(), {
    method,
    headers,
    body,
    signal: opts.signal,
    cache: 'no-store',
  });

  if (!res.ok) {
    let code = 'http_error';
    let message = res.statusText;
    let details: unknown;
    try {
      const env = (await res.json()) as {
        error?: { code?: string; message?: string; details?: unknown };
      };
      if (env?.error) {
        code = env.error.code ?? code;
        message = env.error.message ?? message;
        details = env.error.details;
      }
    } catch {
      // non-JSON body, keep defaults
    }
    throw new ApiError(res.status, code, message, details);
  }

  if (res.status === 204) return undefined as T;
  const contentType = res.headers.get('content-type') ?? '';
  if (!contentType.includes('application/json')) {
    return (await res.text()) as unknown as T;
  }
  return (await res.json()) as T;
}

// -------- Resource methods --------

export const api = {
  // Tenants / users
  me: (token?: string) => request<User>('GET', '/users/me', { token }),
  myTenant: (token?: string) => request<Tenant>('GET', '/tenants/me', { token }),

  // Collections
  listCollections: (args: { limit?: number; offset?: number; token?: string } = {}) =>
    request<Page<Collection>>('GET', '/collections', {
      token: args.token,
      query: { limit: args.limit ?? 50, offset: args.offset ?? 0 },
    }),
  createCollection: (payload: CollectionCreate, token?: string) =>
    request<Collection>('POST', '/collections', { token, body: payload }),

  // Documents
  listDocuments: (
    collection_id: string,
    args: { limit?: number; offset?: number; token?: string } = {},
  ) =>
    request<Page<DocumentRow>>('GET', '/documents', {
      token: args.token,
      query: { collection_id, limit: args.limit ?? 50, offset: args.offset ?? 0 },
    }),
  uploadDocument: (args: {
    collection_id: string;
    file: File;
    title?: string;
    sensitivity_level?: string;
    metadata?: Record<string, unknown>;
    token?: string;
  }) => {
    const fd = new FormData();
    fd.append('collection_id', args.collection_id);
    fd.append('file', args.file);
    if (args.title) fd.append('title', args.title);
    if (args.sensitivity_level) fd.append('sensitivity_level', args.sensitivity_level);
    fd.append('metadata', JSON.stringify(args.metadata ?? {}));
    return request<DocumentUploadResponse>('POST', '/documents', {
      token: args.token,
      formData: fd,
    });
  },

  // Ingestion
  listIngestionJobs: (
    collection_id: string,
    args: { limit?: number; offset?: number; token?: string } = {},
  ) =>
    request<IngestionJob[]>('GET', '/ingestion/jobs', {
      token: args.token,
      query: { collection_id, limit: args.limit ?? 50, offset: args.offset ?? 0 },
    }),
  getIngestionJob: (job_id: string, token?: string) =>
    request<IngestionJob>('GET', `/ingestion/jobs/${job_id}`, { token }),

  // Query
  executeQuery: (payload: QueryRequest, token?: string) =>
    request<QueryResponse>('POST', '/query', { token, body: payload }),
  getTrace: (query_session_id: string, token?: string) =>
    request<QueryTraceResponse>('GET', `/query/${query_session_id}/trace`, { token }),

  // Prompts
  listPrompts: (token?: string) => request<PromptTemplate[]>('GET', '/prompts', { token }),
  listPromptVersions: (template_id: string, token?: string) =>
    request<PromptVersion[]>('GET', `/prompts/${template_id}/versions`, { token }),

  // Evaluation
  listEvalRuns: (token?: string) =>
    request<EvaluationRun[]>('GET', '/eval/runs', { token }).catch(() => [] as EvaluationRun[]),
  getEvalRun: (run_id: string, token?: string) =>
    request<EvaluationRunResults>('GET', `/eval/runs/${run_id}`, { token }),
  listEvalCases: (dataset_id: string, token?: string) =>
    request<EvaluationCase[]>('GET', `/eval/datasets/${dataset_id}/cases`, { token }),
  createEvalDataset: (payload: { name: string; description?: string }, token?: string) =>
    request<EvaluationDataset>('POST', '/eval/datasets', { token, body: payload }),
};

export type Api = typeof api;
