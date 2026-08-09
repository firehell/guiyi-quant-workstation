import { defineConfig, devices } from '@playwright/test'

const e2ePort = Number(process.env.PLAYWRIGHT_PORT || 5182)
const e2eBaseURL = process.env.PLAYWRIGHT_BASE_URL || `http://127.0.0.1:${e2ePort}`

/**
 * Web V1 最小浏览器 Gate：mock smoke 默认；readonly 需 REAL_BACKEND=1。
 * 使用本机 Chrome channel，避免 headless_shell 未装齐时启动失败。
 * 使用 .mjs 避免 Node 26 下 Playwright TS loader（module.register）挂起。
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: /.*\.spec\.mjs/,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list']],
  timeout: 60_000,
  use: {
    baseURL: e2eBaseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome',
    headless: true,
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
  webServer: process.env.PLAYWRIGHT_SKIP_WEBSERVER
    ? undefined
    : {
        command: `npm run dev -- --host 127.0.0.1 --port ${e2ePort}`,
        url: e2eBaseURL,
        // An arbitrary local server can belong to another worktree; fail rather than test stale source.
        reuseExistingServer: false,
        timeout: 120_000,
      },
})
