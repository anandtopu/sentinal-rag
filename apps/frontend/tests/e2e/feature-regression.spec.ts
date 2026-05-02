import { expect, test } from '@playwright/test';

import { ids, installApiMocks } from './helpers/api-mocks';

test.describe('feature regression suite (mocked API)', () => {
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
});
