// Baseline scenario — steady RPS at the design rate.
//
// Purpose: catch regressions in the happy-path. Run on every release tag
// (CI workflow `perf-baseline.yml`, gated by infra availability).
//
// Scenario:
//   ramp-up   (2m)  : 0 → 5 rps
//   steady    (10m) : 5 rps
//   ramp-down (1m)  : 5 → 0 rps
//
// Total budget: 13 minutes.

import { sleep } from 'k6';
import { executeQuery } from './lib/http.js';
import { SLO } from './lib/config.js';

export const options = {
  scenarios: {
    baseline: {
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
  tags: { scenario: 'baseline' },
};

export default function () {
  executeQuery();
  // No sleep — the arrival-rate executor controls pacing.
}
