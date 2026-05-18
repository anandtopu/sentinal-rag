// Retrieval-transport comparison scenario (R4.S6 — ADR-0031).
//
// Purpose: measure the p50/p95/p99 latency + RPS-at-SLO delta between
// `RETRIEVAL_TRANSPORT=in-process` and `RETRIEVAL_TRANSPORT=http`
// deployments of the API. The scenario is identical to baseline (steady
// 5 RPS for 10 minutes after a 2-minute ramp); the only thing that
// changes between runs is which deployment SENTINELRAG_BASE_URL points
// at.
//
// Run twice and diff the JSON outputs:
//
//   # First — point at the in-process deployment.
//   SENTINELRAG_BASE_URL=https://api-inprocess.dev.sentinelrag.example.com \
//   SENTINELRAG_AUTH_TOKEN=... SENTINELRAG_COLLECTION_IDS=... \
//   SENTINELRAG_TRANSPORT_LABEL=in-process \
//     k6 run --out json=in-process.json transport-compare.js
//
//   # Then — point at the http deployment.
//   SENTINELRAG_BASE_URL=https://api-http.dev.sentinelrag.example.com \
//   SENTINELRAG_AUTH_TOKEN=... SENTINELRAG_COLLECTION_IDS=... \
//   SENTINELRAG_TRANSPORT_LABEL=http \
//     k6 run --out json=http.json transport-compare.js
//
// The `transport` tag on every metric lets a downstream summarizer
// (operator runbook step) compute the delta without remembering which
// JSON came from which run.
//
// Per ADR-0029, the diffed numbers land in
// `docs/operations/retrieval-benchmark-report.md` via a follow-on
// summarizer step — never hand-edited.

import { executeQuery } from './lib/http.js';
import { SLO } from './lib/config.js';

const TRANSPORT_LABEL = __ENV.SENTINELRAG_TRANSPORT_LABEL || 'unknown';

export const options = {
  scenarios: {
    transport_compare: {
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1s',
      preAllocatedVUs: 20,
      maxVUs: 50,
      stages: [
        { target: 5, duration: '2m' },
        { target: 5, duration: '10m' },
        { target: 0, duration: '1m' },
      ],
    },
  },
  thresholds: {
    'http_req_failed{name:POST /query}': [`rate<${SLO.errorRate}`],
    'rag_query_errors':                 [`rate<${SLO.errorRate}`],
    'rag_query_latency_ms':             [
      `p(95)<${SLO.queryP95Ms}`,
      `p(99)<${SLO.queryP99Ms}`,
    ],
  },
  tags: {
    scenario: 'transport-compare',
    transport: TRANSPORT_LABEL,
  },
};

export function setup() {
  if (TRANSPORT_LABEL === 'unknown') {
    throw new Error(
      'SENTINELRAG_TRANSPORT_LABEL must be set to either "in-process" or "http" ' +
        'so the resulting metrics can be attributed to the right transport.',
    );
  }
  return { transport: TRANSPORT_LABEL };
}

export default function () {
  executeQuery();
}
