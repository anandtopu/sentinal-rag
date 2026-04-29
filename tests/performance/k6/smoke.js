// Smoke scenario — minimal load, run in CI on every PR.
//
// 30 seconds at 0.5 rps (~15 requests). Just enough to prove the chart
// + cluster + LLM gateway are wired together. Thresholds are very loose;
// the point is fail-fast on a 500 or DNS error, not catch perf regressions.

import { executeQuery } from './lib/http.js';
import { SLO } from './lib/config.js';

export const options = {
  scenarios: {
    smoke: {
      executor: 'constant-arrival-rate',
      rate: 1,
      timeUnit: '2s',  // 0.5 rps
      duration: '30s',
      preAllocatedVUs: 2,
      maxVUs: 5,
    },
  },
  thresholds: {
    'http_req_failed{name:POST /query}': ['rate<0.05'],
    'rag_query_errors':                 ['rate<0.05'],
    'rag_query_latency_ms':             [`p(95)<${SLO.queryP99Ms * 2}`],
  },
  tags: { scenario: 'smoke' },
};

export default function () {
  executeQuery();
}
