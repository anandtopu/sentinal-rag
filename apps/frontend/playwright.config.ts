import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright configuration for SentinelRAG frontend e2e specs.
 *
 * Most regression specs mock the FastAPI boundary so they can run in CI
 * without Docker/Ollama. Live-backend specs still probe /api/v1/health and
 * skip when no backend is reachable.
 */

const PORT = process.env.E2E_PORT ?? '3107';
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`;
const REUSE_SERVER = process.env.E2E_REUSE_SERVER === 'true';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: `npx next dev --hostname 127.0.0.1 --port ${PORT}`,
    url: BASE_URL,
    reuseExistingServer: REUSE_SERVER,
    timeout: 120_000,
  },
});
