/**
 * Hand-written types mirroring `apps/api/app/schemas/*.py`.
 *
 * Phase 7+ will generate these from the OpenAPI spec; for v1 we keep them in
 * sync by hand. Only fields the UI reads are modeled — the API may return more.
 */

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// ---- Tenants / Users ----
export interface Tenant {
  id: string;
  slug: string;
  name: string;
  plan: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface User {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

// ---- Collections ----
export interface Collection {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  visibility: 'private' | 'tenant' | 'public';
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CollectionCreate {
  name: string;
  description?: string;
  visibility?: 'private' | 'tenant' | 'public';
  metadata?: Record<string, unknown>;
}

// ---- Documents / Ingestion ----
export interface DocumentRow {
  id: string;
  tenant_id: string;
  collection_id: string;
  title: string;
  source_type: string;
  source_uri: string | null;
  mime_type: string | null;
  sensitivity_level: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DocumentUploadResponse {
  document_id: string;
  status: string;
  ingestion_job_id: string;
}

export interface IngestionJob {
  id: string;
  tenant_id: string;
  collection_id: string;
  status: string;
  chunking_strategy: string;
  embedding_model: string;
  documents_total: number;
  documents_processed: number;
  chunks_created: number;
  error_message: string | null;
  workflow_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

// ---- Query ----
export interface RetrievalConfigIn {
  mode?: 'hybrid' | 'bm25' | 'vector';
  top_k_bm25?: number;
  top_k_vector?: number;
  top_k_hybrid?: number;
  top_k_rerank?: number;
  ef_search?: number;
}

export interface GenerationConfigIn {
  model?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface QueryOptionsIn {
  include_citations?: boolean;
  include_debug_trace?: boolean;
  abstain_if_unsupported?: boolean;
}

export interface QueryRequest {
  query: string;
  collection_ids: string[];
  retrieval?: RetrievalConfigIn;
  generation?: GenerationConfigIn;
  options?: QueryOptionsIn;
}

export interface CitationRead {
  citation_id: string;
  document_id: string;
  chunk_id: string;
  citation_index: number;
  page_number: number | null;
  section_title: string | null;
  quoted_text: string | null;
  relevance_score: number | null;
}

export interface QueryUsage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
}

export interface QueryResponse {
  query_session_id: string;
  answer: string;
  confidence_score: number | null;
  grounding_score: number | null;
  hallucination_risk_score: number | null;
  citations: CitationRead[];
  usage: QueryUsage;
}

export interface RetrievalResultRead {
  chunk_id: string;
  stage: string;
  rank: number;
  score: number;
  metadata: Record<string, unknown>;
}

export interface GeneratedAnswerSummary {
  model: string;
  prompt_version_id: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  grounding_score: number | null;
  hallucination_risk_score: number | null;
  confidence_score: number | null;
}

export interface QueryTraceResponse {
  query_session_id: string;
  query: string;
  status: string;
  latency_ms: number | null;
  created_at: string;
  retrieval_results: RetrievalResultRead[];
  generation: GeneratedAnswerSummary | null;
}

// ---- Prompts ----
export interface PromptTemplate {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  task_type: string;
  status: string;
  created_at: string;
}

export interface PromptVersion {
  id: string;
  prompt_template_id: string;
  version_number: number;
  system_prompt: string;
  user_prompt_template: string;
  parameters: Record<string, unknown>;
  model_config: Record<string, unknown>;
  is_default: boolean;
  created_at: string;
}

// ---- Evaluation ----
export interface EvaluationDataset {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  dataset_type: string;
  created_at: string;
}

export interface EvaluationCase {
  id: string;
  dataset_id: string;
  input_query: string;
  expected_answer: string | null;
  expected_citation_chunk_ids: string[];
  grading_rubric: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface EvaluationRun {
  id: string;
  dataset_id: string;
  name: string;
  status: string;
  workflow_id: string | null;
  prompt_version_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface EvaluationScoreSummary {
  context_relevance_avg: number | null;
  faithfulness_avg: number | null;
  answer_correctness_avg: number | null;
  citation_accuracy_avg: number | null;
  average_latency_ms: number | null;
  total_cost_usd: number | null;
  cases_total: number;
  cases_completed: number;
  cases_failed: number;
}

export interface EvaluationRunResults {
  evaluation_run_id: string;
  status: string;
  summary: EvaluationScoreSummary;
}

// ---- Errors ----
export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}
