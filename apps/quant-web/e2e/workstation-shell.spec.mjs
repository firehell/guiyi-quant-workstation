import { test, expect } from '@playwright/test'

const pages = [
  ['我的看盘', '/market/chart'], ['运行总览', '/workstation'], ['策略中心', '/strategies'],
  ['模拟交易', '/simulations'], ['回测中心', '/backtests'], ['研究中心', '/research'],
  ['交易复盘', '/trade-journal'], ['数据与系统', '/system'],
]
async function mockSources(page) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    if (path === '/api/health') return route.fulfill({ json: { status: 'ok', version: 'fixture-api' } })
    if (path === '/api/runtime/health') return route.fulfill({ json: {
      status: 'degraded', generated_at: '2026-11-27T08:00:00Z', components: {
        db: { status: 'ok' }, redis: { status: 'ok' }, live_market: { status: 'degraded', error_type: 'live_heartbeat_stale', subscribed_count: 2, operational_count: 3 },
        after_market: { status: 'ok', last_successful_trading_day: '2026-11-26' }, alert: { status: 'disabled' },
      }, runtime_identity: { status: 'matched', services: { api: { status: 'matched', runtime_tag: 'fixture-tag', runtime_commit: 'fixture-sha' } } },
    } })
    if (path.endsWith('/product-directory')) return route.fulfill({ status: 503, json: {} })
    if (path === '/api/v1/strategies') return route.fulfill({ json: { items: [], version: 'fixture-strategy' } })
    return route.fulfill({ status: 503, json: {} })
  })
}
for (const [width, height] of [[1366, 768], [1920, 1080]]) {
  test(`desktop navigates all eight areas and preserves a physical chart at ${width}`, async ({ page }) => {
    await mockSources(page)
    const failures = []
    page.on('pageerror', error => failures.push(error.name))
    await page.setViewportSize({ width, height })
    await page.addInitScript(() => {
      localStorage.setItem('guiyi.workstation.chart.v1', JSON.stringify({
        view: 'free', symbol: 'jm', series_kind: 'contract', contract: 'JM2701', frequency: '15m',
      }))
    })
    await page.goto('/')
    await expect(page).toHaveURL(/\/market\/chart\?/)
    expect(new URL(page.url()).searchParams.get('contract')).toBe('JM2701')
    const nav = page.getByRole('navigation', { name: '工作站主导航' })
    for (const [title, path] of pages) {
      const link = nav.getByRole('link', { name: title, exact: true })
      await link.click()
      await expect.poll(() => new URL(page.url()).pathname).toBe(path)
      await expect(link).toHaveAttribute('aria-current', 'page')
      await expect(page.locator('.ws-content').locator('h1, [role=alert], .market-detail-page').first()).toBeVisible()
      expect(await page.locator('.ws-content').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    }
    const system = page.getByRole('main')
    await expect(system.getByText('fixture-api')).toBeVisible()
    await expect(system.getByText('fixture-strategy')).toBeVisible()
    await expect(system.getByText('读取失败', { exact: true })).toBeVisible()
    await system.getByText('服务部署身份 · 身份一致').click()
    await expect(system.getByText('fixture-sha')).toBeVisible()
    await nav.getByRole('link', { name: '运行总览' }).click()
    const issue = page.getByRole('link', { name: /盘中行情.*live_heartbeat_stale/ })
    await issue.click()
    await expect(page).toHaveURL(/\/system#runtime$/)
    expect(failures).toEqual([])
  })
}
test('research links retain the selected run and case without starting a task', async ({ page }) => {
  const writes = []
  const reads = []
  await page.route('**/api/**', route => {
    if (!new URL(route.request().url()).pathname.startsWith('/api/')) return route.continue()
    if (route.request().method() !== 'GET') writes.push(route.request().method())
    else reads.push(new URL(route.request().url()).pathname)
    return route.fulfill({ status: 503, json: {} })
  })
  await page.goto('/research/statistics?mode=case&case=case-identity')
  await expect(page.getByRole('button', { name: '交易案例', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('#statistics-analysis-form input[required]').first()).toHaveValue('case-identity')
  await page.getByRole('button', { name: '因子实验', exact: true }).click()
  await expect(page).toHaveURL(/statistics\?mode=factor$/)
  await page.reload()
  await expect(page.getByRole('button', { name: '因子实验', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.goBack()
  await expect(page.locator('#statistics-analysis-form input[required]').first()).toHaveValue('case-identity')
  expect(reads).not.toContain('/api/v1/statistics-research/backtests')
  await page.goto('/research/statistics?mode=backtest&run=run-identity')
  await expect(page.getByLabel('已发布 Run')).toHaveValue('run-identity')
  expect(writes).toEqual([])
})
