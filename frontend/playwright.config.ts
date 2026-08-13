import { defineConfig, devices } from '@playwright/test'

const candidate = process.env.MING_RELEASE_CANDIDATE ?? 'unassigned'
const runId = process.env.MING_RELEASE_SMOKE_RUN_ID ?? 'local'
const offlineLifecycle = process.env.MING_E2E_MODE === 'offline'
const visualCapture = Boolean(process.env.MING_VISUAL_EVIDENCE_DIR)
const deterministicOffline = offlineLifecycle || visualCapture

export default defineConfig({
  testDir: './e2e',
  // Offline lifecycle evidence and operator live smoke are separate gates.
  // Keep the live spec undiscovered in the deterministic profile so a local
  // browser run cannot fail merely because BYOK configuration is absent.
  testMatch: visualCapture
    ? '**/desktop-visual-capture.spec.mjs'
    : offlineLifecycle
      ? '**/lifecycle-continuity.spec.mjs'
      : '**/release-smoke.spec.mjs',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [['line']],
  outputDir: visualCapture
    ? '../output/playwright/desktop-visual-capture'
    : offlineLifecycle
      ? '../output/playwright/lifecycle-continuity'
      : `../output/playwright/release-smoke/${candidate}/${runId}`,
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
  ],
  webServer: [
    {
      command: deterministicOffline
        ? 'python scripts/lifecycle_e2e_server.py'
        : 'python scripts/release_smoke_server.py',
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
