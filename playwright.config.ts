import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config for HeartTwin Lab.
 *
 * - E2E specs live in tests/e2e, API specs in tests/api.
 * - Set E2E_BASE_URL to test a deployed/already-running instance; otherwise a
 *   local dev server (frontend + Python API) is started automatically.
 * - API specs hit `${baseURL}/api/v1` (override with E2E_API_BASE).
 *
 * Browsers must be installed once: `pnpm exec playwright install chromium`.
 */

const baseURL = process.env.E2E_BASE_URL || 'http://localhost:3001'
const useExternal = Boolean(process.env.E2E_BASE_URL)

export default defineConfig({
  testDir: './tests',
  testMatch: ['e2e/**/*.spec.ts', 'api/**/*.spec.ts'],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  // Start a local dev server only when not pointing at an external URL.
  webServer: useExternal
    ? undefined
    : {
        command: 'pnpm dev',
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        stdout: 'pipe',
        stderr: 'pipe',
      },
})
