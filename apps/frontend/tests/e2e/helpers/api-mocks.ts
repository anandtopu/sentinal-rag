import type { Page, Route } from '@playwright/test';

const now = '2026-05-01T16:00:00.000Z';

export const ids = {
  collection: '11111111-1111-4111-8111-111111111111',
  collectionPrivate: '22222222-2222-4222-8222-222222222222',
  document: '33333333-3333-4333-8333-333333333333',
  job: '44444444-4444-4444-8444-444444444444',
  querySession: '55555555-5555-4555-8555-555555555555',
  citation: '66666666-6666-4666-8666-666666666666',
  chunk: '77777777-7777-4777-8777-777777777777',
  promptTemplate: '88888888-8888-4888-8888-888888888888',
  promptVersion: '99999999-9999-4999-8999-999999999999',
  evalRun: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  dataset: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
};

type Json = Record<string, unknown> | unknown[];

interface MockState {
  collections: Json[];
  documents: Json[];
  jobs: Json[];
  postedQuery: unknown | null;
}

function json(route: Route, body: Json, status = 200) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

function pageEnvelope(items: Json[]) {
  return { items, total: items.length, limit: 200, offset: 0 };
}

function collection(id: string, name: string, visibility: string, description: string | null) {
  return {
    id,
    tenant_id: '00000000-0000-0000-0000-000000000001',
    name,
    description,
    visibility,
    metadata: {},
    created_at: now,
    updated_at: now,
  };
}

export async function installApiMocks(page: Page): Promise<MockState> {
  const state: MockState = {
    collections: [
      collection(ids.collection, 'Seed Runbooks', 'tenant', 'Deployment and DR procedures'),
      collection(ids.collectionPrivate, 'Security Notes', 'private', 'Restricted review notes'),
    ],
    documents: [
      {
        id: ids.document,
        tenant_id: '00000000-0000-0000-0000-000000000001',
        collection_id: ids.collection,
        title: 'aws-runbook.md',
        source_type: 'upload',
        source_uri: null,
        mime_type: 'text/markdown',
        sensitivity_level: 'internal',
        status: 'ready',
        metadata: {},
        created_at: now,
        updated_at: now,
      },
    ],
    jobs: [
      {
        id: ids.job,
        tenant_id: '00000000-0000-0000-0000-000000000001',
        collection_id: ids.collection,
        status: 'completed',
        chunking_strategy: 'semantic',
        embedding_model: 'ollama/nomic-embed-text',
        documents_total: 1,
        documents_processed: 1,
        chunks_created: 12,
        error_message: null,
        workflow_id: 'ingestion-demo',
        started_at: now,
        completed_at: now,
        created_at: now,
      },
    ],
    postedQuery: null,
  };

  await page.route('**/api/auth/session', (route) => json(route, {}));
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, '/api');

    if (path === '/api/health') return json(route, { status: 'ok' });

    if (path === '/api/tenants/me') {
      return json(route, {
        id: '00000000-0000-4000-8000-000000000001',
        slug: 'acme',
        name: 'Acme Research',
        plan: 'enterprise',
        status: 'active',
        metadata: {},
        created_at: now,
        updated_at: now,
      });
    }
    if (path === '/api/users/me') {
      return json(route, {
        id: '00000000-0000-4000-8000-000000000002',
        tenant_id: '00000000-0000-4000-8000-000000000001',
        email: 'demo.admin@acme.test',
        full_name: 'Demo Admin',
        status: 'active',
        created_at: now,
        updated_at: now,
      });
    }

    if (path === '/api/collections' && request.method() === 'GET') {
      return json(route, pageEnvelope(state.collections));
    }
    if (path === '/api/collections' && request.method() === 'POST') {
      const payload = request.postDataJSON() as {
        name: string;
        visibility?: string;
        description?: string;
      };
      const created = collection(
        'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
        payload.name,
        payload.visibility ?? 'tenant',
        payload.description ?? null,
      );
      state.collections = [created, ...state.collections];
      return json(route, created, 201);
    }

    if (path === '/api/documents' && request.method() === 'GET') {
      return json(route, pageEnvelope(state.documents));
    }
    if (path === '/api/documents' && request.method() === 'POST') {
      const uploaded = {
        id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
        tenant_id: '00000000-0000-0000-0000-000000000001',
        collection_id: ids.collection,
        title: 'regression.md',
        source_type: 'upload',
        source_uri: null,
        mime_type: 'text/markdown',
        sensitivity_level: 'internal',
        status: 'processing',
        metadata: {},
        created_at: now,
        updated_at: now,
      };
      state.documents = [uploaded, ...state.documents];
      state.jobs = [
        { ...state.jobs[0], id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', status: 'queued' },
      ];
      return json(route, {
        document_id: uploaded.id,
        status: 'queued',
        ingestion_job_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      });
    }

    if (path === '/api/ingestion/jobs') return json(route, state.jobs);

    if (path === '/api/query' && request.method() === 'POST') {
      state.postedQuery = request.postDataJSON();
      return json(route, {
        query_session_id: ids.querySession,
        answer: 'The AWS runbook requires Terraform apply before ArgoCD sync. [1]',
        confidence_score: 0.92,
        grounding_score: 0.95,
        hallucination_risk_score: 0.05,
        citations: [
          {
            citation_id: ids.citation,
            document_id: ids.document,
            chunk_id: ids.chunk,
            citation_index: 1,
            page_number: 3,
            section_title: 'Deployment',
            quoted_text: 'Run terraform apply, then sync the ArgoCD Application.',
            relevance_score: 0.98,
          },
        ],
        usage: { input_tokens: 1024, output_tokens: 96, cost_usd: 0, latency_ms: 842 },
      });
    }

    if (path === `/api/query/${ids.querySession}/trace/stream`) {
      const trace = queryTrace();
      return route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `event: trace\ndata: ${JSON.stringify(trace)}\n\nevent: done\ndata: {}\n\n`,
      });
    }
    if (path === `/api/query/${ids.querySession}/trace`) return json(route, queryTrace());

    if (path === '/api/prompts') {
      return json(route, [
        {
          id: ids.promptTemplate,
          tenant_id: '00000000-0000-0000-0000-000000000001',
          name: 'rag_answer_generation',
          description: 'Grounded answer prompt',
          task_type: 'rag_answer_generation',
          status: 'active',
          created_at: now,
        },
      ]);
    }
    if (path === `/api/prompts/${ids.promptTemplate}/versions`) {
      return json(route, [
        {
          id: ids.promptVersion,
          prompt_template_id: ids.promptTemplate,
          version_number: 2,
          system_prompt: 'Answer from context only.',
          user_prompt_template: 'Question: {query}',
          parameters: {},
          model_config: {},
          is_default: true,
          created_at: now,
        },
      ]);
    }

    if (path === '/api/eval/runs') {
      return json(route, [
        {
          id: ids.evalRun,
          dataset_id: ids.dataset,
          name: 'Nightly faithfulness regression',
          status: 'completed',
          workflow_id: 'eval-demo',
          prompt_version_id: ids.promptVersion,
          started_at: now,
          completed_at: now,
          created_at: now,
        },
      ]);
    }

    return json(route, { error: { code: 'not_mocked', message: `No mock for ${path}` } }, 404);
  });

  return state;
}

function queryTrace() {
  return {
    query_session_id: ids.querySession,
    query: 'What is the AWS deployment order?',
    status: 'completed',
    latency_ms: 842,
    created_at: now,
    retrieval_results: [
      { chunk_id: ids.chunk, stage: 'bm25', rank: 1, score: 0.91, metadata: {} },
      { chunk_id: ids.chunk, stage: 'vector', rank: 1, score: 0.89, metadata: {} },
      { chunk_id: ids.chunk, stage: 'hybrid_merge', rank: 1, score: 0.95, metadata: {} },
      { chunk_id: ids.chunk, stage: 'rerank', rank: 1, score: 0.98, metadata: {} },
    ],
    generation: {
      model: 'ollama/llama3.1:8b',
      prompt_version_id: ids.promptVersion,
      input_tokens: 1024,
      output_tokens: 96,
      cost_usd: 0,
      grounding_score: 0.95,
      hallucination_risk_score: 0.05,
      confidence_score: 0.92,
    },
  };
}
