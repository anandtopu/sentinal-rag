// Soak scenario — moderate steady load over a long window.
//
// Purpose: surface memory leaks, slow-growing connection pools, RDS auto-
// vacuum stalls, slow LLM-cache cardinality drift. Run weekly (manual or
// scheduled) against the dev environment.
//
// Scenario: 3 rps for 1 hour. Lower than baseline; the goal isn't peak
// throughput, it's stability over time.

import { executeQuery } from './lib/http.js';
import { SLO } from './lib/config.js';

export const options = {
  scenarios: {
    soak: {
      executor: 'constant-arrival-rate',
      rate: 3,
      timeUnit: '1s',
      duration: '1h',
      preAllocatedVUs: 15,
      maxVUs: 40,
    },
  },
  thresholds: {
    'http_req_failed{name:POST /query}': [`rate<${SLO.errorRate}`],
    'rag_query_errors':                 [`rate<${SLO.errorRate}`],
    // Slightly looser p99 than baseline — soak tolerates the occasional GC
    // pause / autovacuum-induced spike. Regressions show up as p99 climbing
    // monotonically over the hour, which the dashboard catches.
    'rag_query_latency_ms':             [
      `p(95)<${SLO.queryP95Ms}`,
      `p(99)<${SLO.queryP99Ms * 1.25}`,
    ],
  },
  tags: { scenario: 'soak' },
};

export default function () {
  executeQuery();
}
