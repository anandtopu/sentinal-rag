// HTTP wrappers for SentinelRAG k6 scripts.
//
// Centralizes URL construction, header injection, and tagged metric names
// so every script reports the same Trend metric (rag_query_latency) for
// dashboards / SLO charts.

import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

import { url, headers, COLLECTION_IDS } from './config.js';
import { pickQuery } from './queries.js';

export const queryLatency = new Trend('rag_query_latency_ms', true);
export const queryErrors = new Rate('rag_query_errors');
export const queryAbstain = new Counter('rag_query_abstain');

export function executeQuery() {
  if (COLLECTION_IDS.length === 0) {
    throw new Error(
      'SENTINELRAG_COLLECTION_IDS env is empty — pass at least one demo collection UUID.',
    );
  }

  const body = JSON.stringify({
    query: pickQuery(),
    collection_ids: COLLECTION_IDS,
    retrieval: {
      mode: 'hybrid',
      top_k_bm25: 20,
      top_k_vector: 20,
      top_k_hybrid: 30,
      top_k_rerank: 8,
    },
    generation: {
      model: 'ollama/llama3.1:8b',
      temperature: 0.1,
      max_tokens: 400,
    },
    options: {
      include_citations: true,
      include_debug_trace: false,
      abstain_if_unsupported: true,
    },
  });

  const res = http.post(url('/query'), body, {
    headers,
    tags: { name: 'POST /query' },
    timeout: '30s',
  });

  queryLatency.add(res.timings.duration);
  queryErrors.add(res.status >= 400 || res.status === 0);

  // Reasonable structural assertions; we do NOT assert on grounding score
  // (load tests should not flake on stochastic LLM output).
  const ok = check(res, {
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
    'has query_session_id': (r) => {
      try {
        const json = r.json();
        return typeof json.query_session_id === 'string';
      } catch {
        return false;
      }
    },
  });

  if (ok) {
    try {
      const json = res.json();
      if (json.answer === '' || json.answer === null) {
        queryAbstain.add(1);
      }
    } catch {
      // ignore parse errors — already counted as an error above.
    }
  }

  return res;
}
