// Shared configuration for SentinelRAG k6 scripts.
//
// All scripts read these from environment variables so the same script
// runs against local, dev, and (eventually) prod without edits. Defaults
// match the local docker-compose stack.

export const BASE_URL = __ENV.SENTINELRAG_BASE_URL || 'http://localhost:8000';
export const API_BASE = __ENV.SENTINELRAG_API_BASE || '/api/v1';
export const AUTH_TOKEN = __ENV.SENTINELRAG_AUTH_TOKEN || 'dev';
// Comma-separated list of collection UUIDs to query. The seed-demo-tenant
// task populates one collection on `make seed` — pass its ID here.
export const COLLECTION_IDS = (__ENV.SENTINELRAG_COLLECTION_IDS || '')
  .split(',')
  .map((s) => s.trim())
  .filter(Boolean);

export const url = (path) => `${BASE_URL}${API_BASE}${path}`;

export const headers = {
  'Content-Type': 'application/json',
  Authorization: `Bearer ${AUTH_TOKEN}`,
};

// SLO targets — these match the thresholds enforced by individual scripts.
// Tighten in values-prod.yaml-equivalent when prod baselines stabilize.
export const SLO = {
  // Sentinel target: p95 query latency under 4s including LLM generation.
  queryP95Ms: 4000,
  // Sentinel target: p99 under 8s. Tail catches slow re-rank or LLM cold-start.
  queryP99Ms: 8000,
  // Error rate ceiling — anything above this is a real regression.
  errorRate: 0.01,
};
