/**
 * Tests for the typed API client.
 *
 * These exercise the fetch wrapper against a mocked global.fetch so we cover:
 *   - Bearer token forwarding (auth pillar #1: every request authenticated).
 *   - Query-string serialization (skipping undefined).
 *   - Error envelope unwrapping (FastAPI errors → ApiError with code/details).
 *   - 204 → undefined and JSON parsing.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError, api } from '@/lib/api';

type FetchInput = Parameters<typeof fetch>[0];
type FetchInit = Parameters<typeof fetch>[1];

interface FetchCall {
  url: string;
  init: FetchInit;
}

const calls: FetchCall[] = [];

function mockFetch(response: {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
}) {
  return vi.fn(async (input: FetchInput, init?: FetchInit) => {
    calls.push({ url: typeof input === 'string' ? input : input.toString(), init });
    const body = response.body;
    const headers = new Headers({
      'content-type': 'application/json',
      ...(response.headers ?? {}),
    });
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status: response.status ?? 200,
      headers,
    });
  });
}

beforeEach(() => {
  calls.length = 0;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('api client', () => {
  it('attaches Authorization bearer when token is provided', async () => {
    globalThis.fetch = mockFetch({
      body: { id: 'u', email: 'x@y.z', tenant_id: 't' },
    }) as typeof fetch;
    await api.me('jwt-abc');
    const headers = (calls[0].init?.headers ?? {}) as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer jwt-abc');
  });

  it('serializes query params and skips undefined', async () => {
    globalThis.fetch = mockFetch({
      body: { items: [], total: 0, limit: 50, offset: 0 },
    }) as typeof fetch;
    await api.listCollections({ token: 't', limit: 10 });
    expect(calls[0].url).toContain('limit=10');
    expect(calls[0].url).toContain('offset=0');
  });

  it('unwraps the FastAPI error envelope into ApiError', async () => {
    globalThis.fetch = mockFetch({
      status: 403,
      body: {
        error: { code: 'forbidden', message: 'no perm', details: { perm: 'queries:execute' } },
      },
    }) as typeof fetch;

    await expect(
      api.executeQuery({ query: 'q', collection_ids: ['c'] }, 't'),
    ).rejects.toMatchObject({
      name: 'ApiError',
      status: 403,
      code: 'forbidden',
      message: 'no perm',
    });
  });

  it('falls back to raw status text on a non-JSON error body', async () => {
    globalThis.fetch = vi.fn(async () => {
      return new Response('not json at all', {
        status: 500,
        statusText: 'Internal Server Error',
        headers: { 'content-type': 'text/plain' },
      });
    }) as typeof fetch;

    const err = await api.me('t').catch((e: ApiError) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).message).toBe('Internal Server Error');
  });

  it('uploads a document via multipart/form-data with the right fields', async () => {
    globalThis.fetch = mockFetch({
      body: { document_id: 'd', status: 'pending', ingestion_job_id: 'j' },
    }) as typeof fetch;

    await api.uploadDocument({
      collection_id: 'col-1',
      file: new File(['hello'], 'x.txt', { type: 'text/plain' }),
      title: 'X',
      token: 't',
    });

    const init = calls[0].init;
    expect(init?.method).toBe('POST');
    expect(init?.body).toBeInstanceOf(FormData);
    const fd = init?.body as FormData;
    expect(fd.get('collection_id')).toBe('col-1');
    expect(fd.get('title')).toBe('X');
    expect(fd.get('file')).toBeInstanceOf(File);
  });
});
