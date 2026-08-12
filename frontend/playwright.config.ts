import { defineConfig, devices } from '@playwright/test'

const candidate = process.env.MING_RELEASE_CANDIDATE ?? 'unassigned'
const runId = process.env.MING_RELEASE_SMOKE_RUN_ID ?? 'local'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.mjs',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [['line']],
  outputDir: `../output/playwright/release-smoke/${candidate}/${runId}`,
  // Network traces can contain request bodies. Live smoke artifacts therefore
  // deliberately disable trace/video/screenshot capture; the report stores only
  // allowlisted IDs and stage statuses.
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'off',
    video: 'off',
    screenshot: 'off',
    actionTimeout: 15_000,
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['iPhone 13'] } },
  ],
  webServer: [
    {
      command: 'python scripts/release_smoke_server.py',
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/health',
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      cwd: '.',
      env: { VITE_API_BASE: 'http://127.0.0.1:8000/api' },
      url: 'http://127.0.0.1:5173',
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
})
