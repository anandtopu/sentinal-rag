// Spike scenario — sudden 10x burst against a steady baseline.
//
// Purpose: exercise the HPA + autoscaler path. We expect transient
// p99 latency degradation during scale-up; thresholds reflect that.
//
// Scenario:
//   warm-up  (1m)   : 0 → 3 rps
//   spike    (30s)  : ramp to 30 rps
//   hold     (2m)   : 30 rps
//   recover  (3m)   : back down to 3 rps
//   tail     (1m)   : 3 rps to confirm recovery

import { executeQuery } from './lib/http.js';
import { SLO } from './lib/config.js';

export const options = {
  scenarios: {
    spike: {
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1s',
      preAllocatedVUs: 30,
      maxVUs: 200,
      stages: [
        { target: 3,  duration: '1m'  },
        { target: 30, duration: '30s' },
        { target: 30, duration: '2m'  },
        { target: 3,  duration: '3m'  },
        { target: 3,  duration: '1m'  },
      ],
    },
  },
  thresholds: {
    'http_req_failed{name:POST /query}': [`rate<${SLO.errorRate * 5}`],
    'rag_query_errors':                 [`rate<${SLO.errorRate * 5}`],
    // Tail allowance during the spike + scale-up window. We accept up to
    // 2× the steady-state p99; if it doesn't come back down by the tail
    // segment, the autoscaler is failing.
    'rag_query_latency_ms':             [
      `p(95)<${SLO.queryP95Ms * 1.5}`,
      `p(99)<${SLO.queryP99Ms * 2}`,
    ],
  },
  tags: { scenario: 'spike' },
};

export default function () {
  executeQuery();
}
