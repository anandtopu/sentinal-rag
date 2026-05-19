import { expect, test } from '@playwright/test';

import { ids, installApiMocks } from './helpers/api-mocks';

test.describe('feature regression suite (mocked API)', () => {
  test('dashboard summarizes tenant, collection, evaluation, and pillar state', async ({
    page,
  }) => {
    await installApiMocks(page);

    await page.goto('/dashboard');

    await expect(page.getByRole('heading', { name: 'Dashboard', level: 1 })).toBeVisible();
    await expect(page.getByText('Acme Research', { exact: true })).toBeVisible();
    await expect(page.getByText('acme', { exact: true })).toBeVisible();
    await expect(page.getByText('Active scopes for retrieval')).toBeVisible();
    await expect(page.getByText('Lifetime runs (ragas + custom)')).toBeVisible();
    await expect(page.getByText(/RBAC injected at retrieval time/i)).toBeVisible();
    await expect(page.getByText(/Prompts are versioned artifacts/i)).toBeVisible();
  });

  test('collections list and create flow preserves RBAC scope fields', async ({ page }) => {
    await installApiMocks(page);

    await page.goto('/collections');
    await expect(page.getByRole('heading', { name: 'Collections', level: 1 })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'Seed Runbooks' })).toBeVisible();

    await page.getByRole('button', { name: 'New collection' }).click();
    await page.getByLabel(/^name/i).fill('Regression Evidence');
    await page.getByLabel(/visibility/i).selectOption('private');
    await page.getByLabel(/description/i).fill('Captured release verification artifacts');
    await page.getByRole('button', { name: 'Create collection' }).click();

    await expect(page.getByRole('cell', { name: 'Regression Evidence' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'private' }).first()).toBeVisible();
  });

  test('documents upload queues ingestion and refreshes document/job tables', async ({ page }) => {
    await installApiMocks(page);

    await page.goto('/documents');
    await expect(page.getByRole('heading', { name: 'Documents', level: 1 })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'aws-runbook.md' })).toBeVisible();

    await page.getByLabel(/file/i).setInputFiles({
      name: 'regression.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('# Regression\n\nEvidence for ingestion flow.'),
    });

    await expect(page.getByText(/Queued ingestion job eeeeeeee/i)).toBeVisible();
    await expect(page.getByRole('cell', { name: 'regression.md' })).toBeVisible();
    await expect(page.getByText('queued', { exact: true })).toBeVisible();
  });

  test('query playground submits selected collection and renders answer, citations, trace', async ({
    page,
  }) => {
    const state = await installApiMocks(page);

    await page.goto('/query-playground');
    await page.getByRole('button', { name: 'Seed Runbooks' }).click();
    await page.getByLabel(/question/i).fill('What is the AWS deployment order?');
    await page.getByLabel(/top-k/i).fill('4');
    await page.getByRole('button', { name: 'Run query' }).click();

    await expect(
      page.getByText('The AWS runbook requires Terraform apply before ArgoCD sync. [1]'),
    ).toBeVisible();
    await expect(
      page.getByText('Run terraform apply, then sync the ArgoCD Application.'),
    ).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Trace' })).toBeVisible();
    await expect(page.getByText('bm25', { exact: true })).toBeVisible();
    await expect(page.getByText('vector', { exact: true })).toBeVisible();
    await expect(page.getByText('hybrid_merge', { exact: true })).toBeVisible();
    await expect(page.getByText('rerank', { exact: true })).toBeVisible();

    expect(state.postedQuery).toMatchObject({
      query: 'What is the AWS deployment order?',
      collection_ids: [ids.collection],
      generation: { model: 'ollama/llama3.1:8b' },
      retrieval: { top_k_rerank: 4 },
      options: { include_debug_trace: true },
    });
  });

  test('query playground keeps trace optional while preserving query payload', async ({ page }) => {
    const state = await installApiMocks(page);

    await page.goto('/query-playground');
    await page.getByRole('button', { name: 'Security Notes' }).click();
    await page.getByLabel(/question/i).fill('Summarize restricted review notes.');
    await page.getByLabel(/model/i).fill('ollama/qwen2.5:7b');
    await page.getByLabel(/show stage trace/i).uncheck();
    await page.getByRole('button', { name: 'Run query' }).click();

    await expect(page.getByRole('heading', { name: 'Answer' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Trace' })).toHaveCount(0);
    expect(state.postedQuery).toMatchObject({
      query: 'Summarize restricted review notes.',
      collection_ids: [ids.collectionPrivate],
      generation: { model: 'ollama/qwen2.5:7b' },
      options: { include_debug_trace: true },
    });
  });

  test('prompt and evaluation pages expose versioned/reproducible artifacts', async ({ page }) => {
    await installApiMocks(page);

    await page.goto('/prompts');
    const promptNameCell = page.getByRole('cell', { name: 'rag_answer_generation' }).first();
    await expect(promptNameCell).toBeVisible();
    await promptNameCell.click();
    await expect(page.getByRole('cell', { name: 'v2' })).toBeVisible();
    await expect(page.getByText('default', { exact: true })).toBeVisible();

    await page.goto('/evaluations');
    await expect(page.getByRole('cell', { name: 'Nightly faithfulness regression' })).toBeVisible();
    await expect(page.getByText('completed', { exact: true })).toBeVisible();
  });

  test('settings page renders tenant and user context from authenticated API calls', async ({
    page,
  }) => {
    await installApiMocks(page);

    await page.goto('/settings');

    await expect(page.getByRole('heading', { name: 'Settings', level: 1 })).toBeVisible();
    await expect(page.getByText(/name:\s*Acme Research/i)).toBeVisible();
    await expect(page.getByText(/plan:\s*enterprise/i)).toBeVisible();
    await expect(page.getByText(/email:\s*demo\.admin@acme\.test/i)).toBeVisible();
    await expect(page.getByText(/name:\s*Demo Admin/i)).toBeVisible();
    await expect(page.getByText('dev token', { exact: true })).toBeVisible();
  });

  test('audit and usage pages keep cost and immutability work visible in navigation', async ({
    page,
  }) => {
    await installApiMocks(page);

    await page.goto('/audit');
    await expect(page.getByRole('heading', { name: 'Audit', level: 1 })).toBeVisible();
    await expect(page.getByText(/dual-written to Postgres \+ S3 Object Lock/i)).toBeVisible();

    await page.getByRole('link', { name: 'Usage' }).click();
    await expect(page.getByRole('heading', { name: 'Usage & Cost', level: 1 })).toBeVisible();
    await expect(page.getByText(/soft\/hard caps/i)).toBeVisible();
  });
});
