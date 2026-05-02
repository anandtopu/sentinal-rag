import { expect, test } from '@playwright/test';

/**
 * Collections — list page renders and the create form fields are wired.
 * Skipped when the backend is unreachable (the page reads /api/v1/collections
 * via TanStack Query on mount).
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

test.describe('collections', () => {
  test.beforeEach(async ({ request }) => {
    test.skip(!(await backendIsUp(request)), 'backend /api/health unreachable');
  });

  test('renders the page header', async ({ page }) => {
    await page.goto('/collections');
    await expect(page.getByRole('heading', { name: /collections/i, level: 1 })).toBeVisible();
  });

  test('exposes a name input on the create form', async ({ page }) => {
    await page.goto('/collections');
    const nameInput = page.getByLabel(/^name/i).first();
    await expect(nameInput).toBeVisible();
    await nameInput.fill('e2e-smoke');
    await expect(nameInput).toHaveValue('e2e-smoke');
  });
});
