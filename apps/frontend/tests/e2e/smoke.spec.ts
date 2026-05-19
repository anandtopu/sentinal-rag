import { expect, test } from '@playwright/test';

/**
 * Smoke specs — exercise paths that don't require seeded data.
 *
 * These run against a live `next dev` (default :3107). The backend at /api
 * doesn't need to be up for these specs; they only assert client-side
 * rendering and navigation. Specs that depend on the API live in their
 * own files and skip gracefully if /api/health is unreachable.
 */

test.describe('shell renders', () => {
  test('dashboard page renders the page header', async ({ page }) => {
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: /dashboard/i, level: 1 })).toBeVisible();
  });

  test('query playground exposes the question textarea', async ({ page }) => {
    await page.goto('/query-playground');
    await expect(page.getByRole('heading', { name: /query playground/i, level: 1 })).toBeVisible();
    await expect(page.getByLabel(/question/i)).toBeVisible();
  });

  test('sidebar links the major sections', async ({ page }) => {
    await page.goto('/dashboard');
    for (const label of [
      'Dashboard',
      'Collections',
      'Documents',
      'Query',
      'Evaluations',
      'Prompts',
    ]) {
      // Sidebar uses anchor labels — be tolerant of "Query Playground" vs "Query".
      const link = page.getByRole('link', { name: new RegExp(label, 'i') }).first();
      await expect(link).toBeVisible();
    }
  });
});
