// Query corpus for load tests.
//
// Mix of short / medium / long queries; some hit the citation path (specific
// terms) and some don't (generic terms). Pulled randomly per VU iteration.

export const QUERIES = [
  'How do I configure RBAC for a multi-tenant deployment?',
  'What is the difference between RLS and application-level access control?',
  'Show me how to roll back a failed migration.',
  'Explain hybrid retrieval and how reciprocal rank fusion works.',
  'What metrics should I watch when the cluster is under load?',
  'How does the audit dual-write protect against tampering?',
  'Where are LLM costs tracked and how do tenant budgets enforce limits?',
  'How do I debug a Temporal workflow that is stuck pending?',
  'What is pgvector HNSW and when should I tune ef_search?',
  'How do I add a new evaluation dataset?',
  'What environment variables does the API service require?',
  'How do I test cross-tenant isolation?',
  'What is the chunking strategy for long documents?',
  'Where does the application persist the prompt version used per query?',
  'How do I rotate Keycloak client secrets?',
];

// Pick a query deterministically per VU iteration so a slow query doesn't
// always fall on the same VU.
export function pickQuery() {
  return QUERIES[Math.floor(Math.random() * QUERIES.length)];
}
