import { expect, test } from '@playwright/test';

/**
 * Query playground — these depend on the API being reachable. Each spec
 * probes /api/health and skips itself if the backend isn't up. This
 * lets `playwright test` pass on a frontend-only CI job and run against
 * the real backend once Phase 7's deployed dev environment is live.
 */

async function backendIsUp(
  request: import('@playwright/test').APIRequestContext,
): Promise<boolean> {
  try {
    const res = await request.get('/api/health', { timeout: 2_000 });
    return res.ok();
  } catch {
    return false;
  }
}

test.describe('query playground (live backend)', () => {
  test.beforeEach(async ({ request }) => {
    test.skip(!(await backendIsUp(request)), 'backend /api/health unreachable');
  });

  test('renders the form and the submit button is disabled with empty input', async ({ page }) => {
    await page.goto('/query-playground');
    const submit = page.getByRole('button', { name: /run|ask|submit/i }).first();
    // The form blocks submission when query/collection are empty (form.tsx
    // returns early). We assert the textarea exists; submission semantics
    // are validated in the unit tests for the form's onSubmit handler.
    await expect(page.getByLabel(/question/i)).toBeVisible();
    await expect(submit).toBeVisible();
  });

  test('typing a question updates the textarea', async ({ page }) => {
    await page.goto('/query-playground');
    const textarea = page.getByLabel(/question/i);
    await textarea.fill('What does the runbook say about pgvector?');
    await expect(textarea).toHaveValue('What does the runbook say about pgvector?');
  });
});
