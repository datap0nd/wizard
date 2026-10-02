import {defineConfig, devices} from '@playwright/test';

// Browser E2E against the real API in replay mode over SYNTHETIC data (no model, no network).
const port = Number(process.env.WIZARD_E2E_PORT ?? 8779);
// Locally use the installed Edge (no browser download); CI installs Playwright's Chromium.
const channel = process.env.CI ? undefined : (process.env.WIZARD_E2E_CHANNEL ?? 'msedge');

export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  // One worker: projects share test identities, and Wizard allows one active run per user.
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {baseURL: `http://127.0.0.1:${port}`, trace: 'retain-on-failure'},
  projects: [
    {name: 'desktop', use: {...devices['Desktop Chrome'], channel, viewport: {width: 1440, height: 900}}},
    {name: 'narrow', use: {...devices['Desktop Chrome'], channel, viewport: {width: 1024, height: 768}}},
  ],
  webServer: {
    command: `uv run --project ../.. python ../../scripts/e2e_server.py --port ${port}`,
    url: `http://127.0.0.1:${port}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
