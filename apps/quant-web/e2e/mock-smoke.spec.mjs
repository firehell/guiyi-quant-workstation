import { expect, test } from '@playwright/test'
import { installMockApi, MAIN_ROUTES, RUNTIME_HEALTH } from './fixtures/mockApi.mjs'

function collectConsoleErrors(page) {
  const consoleErrors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => consoleErrors.push(String(err)))
  return () => consoleErrors
}

test.describe('Web V1 mock smoke', () => {
  test.beforeEach(async ({ page }) => {
    await installMockApi(page)
  })

  test('all main routes open without console errors at 1440x900', async ({ page }) => {
    const consoleErrorsOf = collectConsoleErrors(page)
    await page.setViewportSize({ width: 1440, height: 900 })

    for (const path of MAIN_ROUTES) {
      await page.goto(path)
      await expect(page.locator('.main-layout, .page-shell, .n-layout').first()).toBeVisible({
        timeout: 15_000,
      })
      const bodyText = await page.locator('body').innerText()
      expect(bodyText).not.toMatch(/\/Volumes\//)
      expect(bodyText).not.toMatch(/\/Users\/[^/\s]+\/\.env/)
      expect(bodyText).not.toMatch(/webhook=|password=|api_key=/i)
    }

    const consoleErrors = consoleErrorsOf()
    expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
  })

  test('dashboard navigation and data tab lazy coverage request', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 })
    const coverageCalls = []
    page.on('request', (req) => {
      if (req.url().includes('/data/coverage')) coverageCalls.push(req.url())
    })

    await page.goto('/dashboard')
    await expect(page.getByText('仪表盘').first()).toBeVisible()

    await page.goto('/data')
    await expect(page.getByRole('heading', { name: '数据中心' }).first()).toBeVisible({ timeout: 15_000 })
    const before = coverageCalls.length
    await page.locator('.n-tabs-tab').filter({ hasText: '数据文件' }).first().click()
    await expect.poll(() => coverageCalls.length).toBeGreaterThan(before)
    expect(coverageCalls.some((u) => u.includes('paged=true'))).toBeTruthy()
    expect(coverageCalls.every((u) => !u.includes('include_paths=true'))).toBeTruthy()
  })

  test('market list and chart expose historical/live and contract view controls', async ({ page }) => {
    await page.goto('/market')
    await expect(page.getByText('期货主力行情').first()).toBeVisible()
    await expect(page.getByRole('button', { name: '查看 K 线' }).first()).toBeVisible()

    await page.goto('/market/chart')
    await expect(page.getByText('历史', { exact: true }).first()).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('Live', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('真实主力').first()).toBeVisible()
    await expect(page.getByText('主连研究').first()).toBeVisible()
    await expect(page.getByText('浏览', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('严格研究').first()).toBeVisible()
  })

  test('runtime shows live scheduler, archive, and after-market scheduler sections', async ({ page }) => {
    await page.goto('/runtime')
    await expect(page.getByText('运行状态').first()).toBeVisible()
    await expect(page.getByText('Scheduler').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('After-Market Archive').first()).toBeVisible()
    await expect(page.getByText('After-Market Scheduler').first()).toBeVisible()
    await expect(page.getByText('Archive Lag (trading days)').first()).toBeVisible()
    await expect(page.getByText('Lock Status').first()).toBeVisible()
  })

  test('runtime keeps a compatible empty state when after-market scheduler is absent', async ({ page }) => {
    const legacyHealth = structuredClone(RUNTIME_HEALTH)
    delete legacyHealth.components.after_market_scheduler
    const pageErrors = []
    page.on('pageerror', (err) => pageErrors.push(String(err)))
    await page.route(
      (url) => url.pathname.includes('/runtime/health'),
      (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(legacyHealth) }),
    )
    await page.goto('/runtime')
    await expect(page.getByText('runtime health 未返回 after-market scheduler 组件。').first()).toBeVisible({
      timeout: 15_000,
    })
    expect(pageErrors, pageErrors.join('\n')).toEqual([])
  })

  test('signal page keeps source_mode / research-only boundary copy', async ({ page }) => {
    await page.goto('/signal')
    const body = await page.locator('body').innerText()
    expect(body).toMatch(/source_mode|历史扫描|replay|live/i)
    expect(body).toMatch(/非自动下单|仅供观察|不构成交易指令/)
  })

  test('settings connection validation stays read-only health', async ({ page }) => {
    const methods = []
    page.on('request', (req) => {
      if (req.url().includes('/api/')) methods.push(`${req.method()} ${req.url()}`)
    })
    await page.goto('/settings')
    const testBtn = page.getByRole('button', { name: '测试连接' })
    await expect(testBtn).toBeVisible()
    await testBtn.click()
    await page.waitForTimeout(500)
    expect(methods.some((m) => /^(POST|PUT|PATCH|DELETE)\b/.test(m))).toBeFalsy()
  })

  test('batch page remains research-only without start enabled by default', async ({ page }) => {
    await page.goto('/backtest/batch')
    const body = await page.locator('body').innerText()
    expect(body).toMatch(/BATCH_BACKTEST_RESEARCH_ONLY|research-only|Legacy|默认禁用/i)
    const startBtn = page.getByRole('button', { name: /启动批量/ })
    if (await startBtn.count()) {
      await expect(startBtn.first()).toBeDisabled()
    }
  })

  test('review and backtest deep-link routes open', async ({ page }) => {
    await page.goto('/review?report_id=14')
    await expect(page.locator('.main-layout, .page-shell, .n-layout').first()).toBeVisible({
      timeout: 15_000,
    })
    await page.goto('/market/chart?report_id=14&symbol=jm&period=15m')
    await expect(page.getByText('历史', { exact: true }).first()).toBeVisible({ timeout: 15_000 })
  })
})
