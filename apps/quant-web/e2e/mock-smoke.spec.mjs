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
    await expect(page.getByText('今日工作台').first()).toBeVisible()
    await expect(page.getByLabel('建议动作')).toContainText('打开 JM 15m 工作台')
    await page.getByRole('button', { name: '打开 JM 15m 工作台' }).click()
    await expect(page).toHaveURL(/\/market\/chart\?.*symbol=jm.*period=15m.*contract_view=actual.*data_mode=historical/)

    await page.goto('/data')
    await expect(page.getByRole('heading', { name: '数据中心' }).first()).toBeVisible({ timeout: 15_000 })
    const before = coverageCalls.length
    await page.locator('.n-tabs-tab').filter({ hasText: '数据文件' }).first().click()
    await expect.poll(() => coverageCalls.length).toBeGreaterThan(before)
    expect(coverageCalls.some((u) => u.includes('paged=true'))).toBeTruthy()
    expect(coverageCalls.every((u) => !u.includes('include_paths=true'))).toBeTruthy()
  })

  test('brand uses the single professional logo source in expanded and collapsed sidebar', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/dashboard')

    const logo = page.getByRole('img', { name: '归一量化' })
    await expect(logo).toBeVisible()
    await expect(logo).toHaveAttribute('src', /data-brand(?:=|%3d).*guiyi-quant/i)
    await expect(page.locator('.brand__mark span')).toHaveCount(0)

    const faviconHref = await page.locator('link[rel="icon"]').getAttribute('href')
    expect(faviconHref).toBe('/favicon.svg')
    const favicon = await page.request.get('/favicon.svg')
    expect(favicon.ok()).toBeTruthy()
    expect(await favicon.text()).toContain('data-brand="guiyi-quant"')

    await page.setViewportSize({ width: 1280, height: 720 })
    await expect(logo).toBeVisible()
    await expect(page.getByText('归一量化', { exact: true })).toHaveCount(0)
  })

  test('workspace shell groups navigation and shares one visible runtime pulse', async ({ page }) => {
    const runtimeCalls = []
    page.on('request', (req) => {
      if (req.url().includes('/api/runtime/health')) runtimeCalls.push(req.url())
    })
    await page.goto('/dashboard')
    await expect(page.getByText('工作', { exact: true })).toBeVisible()
    await expect(page.getByText('研究', { exact: true })).toBeVisible()
    await expect(page.getByText('系统保障', { exact: true })).toBeVisible()
    await expect(page.getByLabel('System Pulse')).toContainText('ok')
    await page.getByRole('menuitem', { name: '运行状态' }).click()
    await expect(page.getByRole('heading', { name: '运行状态' })).toBeVisible()
    expect(runtimeCalls).toHaveLength(1)

    await page.goto('/dashboard?symbol=jm&contract=JM2609&period=15m&data_mode=historical&contract_view=actual')
    const context = page.getByLabel('研究上下文')
    await expect(context).toContainText('JM')
    await expect(context).toContainText('JM2609')
    await expect(context).toContainText('15m')
    await expect(context).toContainText('historical')
    await expect(context).toContainText('actual')
  })

  test('retired backtest and settings URLs fall through to not-found without navigation entries', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page.getByRole('menuitem', { name: /回测|批量回测|系统设置/ })).toHaveCount(0)
    await expect(page.getByLabel('打开回测中心')).toHaveCount(0)

    for (const path of ['/backtest', '/backtest/batch', '/settings']) {
      await page.goto(path)
      await expect(page.getByRole('heading', { name: '页面不存在' })).toBeVisible()
      await expect(page).toHaveURL(path)
    }
  })

  test('market list and chart expose historical/live and contract view controls', async ({ page }) => {
    const chartDataCalls = []
    page.on('request', (req) => {
      if (/\/market\/(bars|indicators)/.test(req.url())) chartDataCalls.push(req.url())
    })
    await page.goto('/market')
    await expect(page.getByText('期货主力行情').first()).toBeVisible()
    await expect(page.getByRole('button', { name: '查看 K 线' }).first()).toBeVisible()

    await page.goto('/market/chart?symbol=jm&contract=JM2609&period=15m')
    await expect(page.getByText('历史', { exact: true }).first()).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('Live', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('真实主力').first()).toBeVisible()
    await expect(page.getByText('主连研究').first()).toBeVisible()
    await expect(page.getByText('浏览', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('严格研究').first()).toBeVisible()
    for (const tabName of ['策略', '信号', '复盘', '运行']) {
      await expect(page.getByRole('tab', { name: tabName })).toBeVisible()
    }
    await page.waitForTimeout(100)
    const beforeTabSwitch = chartDataCalls.length
    await page.getByRole('tab', { name: '运行' }).click()
    await page.getByRole('tab', { name: '策略' }).click()
    expect(chartDataCalls).toHaveLength(beforeTabSwitch)
    await page.goto('/market/chart?symbol=jm&contract=JM2609&period=15m&signal_event_id=7')
    await expect(page.getByRole('tab', { name: '信号' })).toHaveAttribute('aria-selected', 'true')
  })

  test('runtime shows archive and after-market scheduler sections without the retired scheduler', async ({ page }) => {
    await page.goto('/runtime')
    await expect(page.getByText('运行状态').first()).toBeVisible()
    await expect(page.getByText('After-Market Archive').first()).toBeVisible()
    await expect(page.getByText('After-Market Scheduler').first()).toBeVisible()
    await expect(page.getByText('Scheduler', { exact: true })).toHaveCount(0)
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

  test('signal event chart review event round-trip restores empty review without writes', async ({ page }) => {
    const writes = []
    page.on('request', (request) => {
      if (/^(POST|PUT|PATCH|DELETE)$/.test(request.method())) writes.push(`${request.method()} ${request.url()}`)
    })
    await page.goto('/signal?tab=events')
    await page.getByRole('button', { name: '打开K线' }).first().click()
    await expect(page).toHaveURL(/\/market\/chart\?.*signal_event_id=7.*data_mode=live/)
    await page.getByRole('button', { name: '打开事件复盘' }).click()
    await expect(page).toHaveURL(/\/review\?.*source_type=signal_event.*source_id=7/)
    await expect(page.getByText(/尚无复盘/).first()).toBeVisible()
    await expect(page.getByRole('button', { name: '创建复盘' })).toBeVisible()
    await page.reload()
    await expect(page.getByText(/SignalEvent #7/).first()).toBeVisible()
    await page.goBack()
    await expect(page).toHaveURL(/\/market\/chart\?.*signal_event_id=7/)
    await page.goForward()
    await expect(page.getByText(/尚无复盘/).first()).toBeVisible()
    await page.getByRole('button', { name: '返回来源' }).click()
    await expect(page).toHaveURL(/\/signal\?.*tab=events.*event_id=7/)
    expect(writes).toEqual([])
  })

  test('security storage, keyboard tabs, focus, and responsive baselines', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('token', 'legacy-browser-secret')
      localStorage.setItem('guiyi_app_settings', '{"apiBaseUrl":"http://legacy.invalid"}')
      sessionStorage.setItem('guiyi_connection_overrides', '{"wsUrl":"ws://legacy.invalid"}')
    })
    const authorizationHeaders = []
    page.on('request', (request) => {
      const authorization = request.headers().authorization
      if (authorization) authorizationHeaders.push(authorization)
    })

    await page.setViewportSize({ width: 1280, height: 720 })
    await page.goto('/dashboard')
    expect(await page.evaluate(() => localStorage.getItem('token'))).toBeNull()
    expect(await page.evaluate(() => localStorage.getItem('guiyi_app_settings'))).toBeNull()
    expect(await page.evaluate(() => sessionStorage.getItem('guiyi_connection_overrides'))).toBeNull()
    expect(authorizationHeaders).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()

    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/market/chart?symbol=jm&contract=JM2609&period=15m')
    const strategyTab = page.getByRole('tab', { name: '策略' })
    await strategyTab.focus()
    await strategyTab.press('ArrowRight')
    await expect(page.getByRole('tab', { name: '信号' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('tab', { name: '信号' })).toBeFocused()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  })
})
