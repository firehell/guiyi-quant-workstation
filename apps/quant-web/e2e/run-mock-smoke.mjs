#!/usr/bin/env node
/**
 * Web V1 mock smoke runner（Playwright library API）。
 * 绕过 Node 26 下 `playwright test` CLI 的 module.register 挂起问题。
 */
import { chromium, expect } from '@playwright/test'
import { installMockApi, MAIN_ROUTES, RUNTIME_HEALTH } from './fixtures/mockApi.mjs'

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5174'
const channel = process.env.PLAYWRIGHT_CHANNEL || 'chrome'

function channelToLinear(channel) {
  const normalized = channel / 255
  return normalized <= 0.03928
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4
}

function rgbLuminance(color) {
  const channels = color.match(/\d+(?:\.\d+)?/g)?.slice(0, 3).map(Number)
  expect(channels, `expected an rgb color, received ${color}`).toHaveLength(3)
  const [red, green, blue] = channels.map(channelToLinear)
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

function contrastRatio(foreground, background) {
  const light = Math.max(rgbLuminance(foreground), rgbLuminance(background))
  const dark = Math.min(rgbLuminance(foreground), rgbLuminance(background))
  return (light + 0.05) / (dark + 0.05)
}

async function withPage(browser, fn) {
  const context = await browser.newContext({
    baseURL,
    viewport: { width: 1440, height: 900 },
  })
  const page = await context.newPage()
  await installMockApi(page)
  try {
    await fn(page)
  } finally {
    await context.close()
  }
}

async function run() {
  const browser = await chromium.launch({ headless: true, channel })
  const failures = []

  const cases = [
    [
      'all main routes open without console errors at 1440x900',
      async (page) => {
        const consoleErrors = []
        page.on('console', (msg) => {
          if (msg.type() === 'error') consoleErrors.push(msg.text())
        })
        page.on('pageerror', (err) => consoleErrors.push(String(err)))
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
        expect(consoleErrors, consoleErrors.join('\n')).toEqual([])
      },
    ],
    [
      'dashboard navigation and data tab lazy coverage request',
      async (page) => {
        await page.setViewportSize({ width: 1280, height: 720 })
        const coverageCalls = []
        page.on('request', (req) => {
          if (req.url().includes('/data/coverage')) coverageCalls.push(req.url())
        })
        await page.goto('/dashboard')
        await expect(page.getByRole('heading', { name: '今日工作台' }).first()).toBeVisible({ timeout: 15_000 })
        await expect(page.getByLabel('建议动作')).toContainText('打开 JM 15m 工作台')
        await page.getByRole('button', { name: '打开 JM 15m 工作台' }).click()
        await expect(page).toHaveURL(/\/market\/chart\?.*symbol=jm.*period=15m.*contract_view=actual.*data_mode=historical/)
        await page.goto('/data')
        await expect(page.getByRole('heading', { name: '数据中心' }).first()).toBeVisible({ timeout: 15_000 })
        await expect(page.getByText('当前处理优先级：')).toBeVisible()
        await expect(page.getByText('2026-07-01 00:00')).toBeVisible()
        const before = coverageCalls.length
        await page.locator('.n-tabs-tab').filter({ hasText: '数据文件' }).first().click()
        await expect.poll(() => coverageCalls.length).toBeGreaterThan(before)
        expect(coverageCalls.some((u) => u.includes('paged=true'))).toBeTruthy()
        expect(coverageCalls.every((u) => !u.includes('include_paths=true'))).toBeTruthy()
        await page.getByRole('button', { name: '详情' }).first().click()
        await expect(page.getByText('数据资产证据（只读）')).toBeVisible()
        await expect(page.getByText('可作为 active 研究候选')).toBeVisible()
        await expect(page.locator('.n-drawer')).not.toContainText(/file_path|\/Users\/|\/Volumes\//)
      },
    ],
    [
      'brand uses the single professional logo source in expanded and collapsed sidebar',
      async (page) => {
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
      },
    ],
    [
      'workspace shell groups navigation and shares one visible runtime pulse',
      async (page) => {
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
      },
    ],
    [
      'market list and chart expose historical/live and contract view controls',
      async (page) => {
        const chartDataCalls = []
        const marketCoverageCalls = []
        const dataProfileCalls = []
        page.on('request', (req) => {
          if (/\/market\/(bars|indicators)/.test(req.url())) chartDataCalls.push(req.url())
          if (/\/market\/(workbench\/coverage|coverage\/canonical)/.test(req.url())) {
            marketCoverageCalls.push(req.url())
          }
          if (req.url().includes('/data/profiles')) dataProfileCalls.push(req.url())
        })
        await page.goto('/market')
        await expect(page.getByText('期货主力行情').first()).toBeVisible({ timeout: 15_000 })
        await expect(page.getByRole('button', { name: '查看 K 线' }).first()).toBeVisible()
        await page.goto('/market/chart?symbol=jm&contract=JM2609&period=15m')
        await expect(page.getByText('历史', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
        await expect(page.getByText('Live', { exact: true }).first()).toBeVisible()
        await expect(page.getByText('真实主力').first()).toBeVisible()
        await expect(page.getByText('主连研究').first()).toBeVisible()
        await expect(page.getByText('浏览', { exact: true }).first()).toBeVisible()
        await expect(page.getByText('严格研究').first()).toBeVisible()
        if (process.env.EXPECT_CANONICAL_MARKET === '1') {
          await expect.poll(() => chartDataCalls.some((url) => url.includes('/bars/canonical'))).toBeTruthy()
          expect(marketCoverageCalls.some((url) => url.includes('/coverage/canonical'))).toBeTruthy()
          expect(marketCoverageCalls.some((url) => url.includes('/workbench/coverage'))).toBeFalsy()
          expect(dataProfileCalls).toEqual([])
        }
        for (const tabName of ['盘面', '信号', '复盘', '运行']) {
          await expect(page.getByRole('tab', { name: tabName })).toBeVisible()
        }
        await page.waitForTimeout(100)
        const beforeTabSwitch = chartDataCalls.length
        await page.getByRole('tab', { name: '运行' }).click()
        await page.getByRole('tab', { name: '盘面' }).click()
        expect(chartDataCalls).toHaveLength(beforeTabSwitch)
        await page.goto('/market/chart?symbol=jm&contract=JM2609&period=15m&signal_event_id=7')
        await expect(page.getByRole('tab', { name: '信号' })).toHaveAttribute('aria-selected', 'true')
      },
    ],
    [
      'selected segmented control renders with readable computed contrast',
      async (page) => {
        await page.goto('/market/chart?symbol=jm&contract=JM2609&period=15m')
        const selectedRadio = page.locator('.n-radio-button.n-radio-button--checked').first()
        await expect(selectedRadio).toBeVisible({ timeout: 20_000 })
        const radioColors = await selectedRadio.evaluate((element) => {
          const style = getComputedStyle(element)
          return {
            background: style.backgroundColor,
            foreground: style.color,
          }
        })
        expect(contrastRatio(radioColors.foreground, radioColors.background)).toBeGreaterThanOrEqual(4.5)
      },
    ],
    [
      'market keeps qualification visible and raw lineage behind evidence disclosure',
      async (page) => {
        await page.goto('/market/chart?symbol=jm&contract=JM2609&period=15m')
        await expect(page.getByText('仅观察', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
        await expect(page.locator('.chart-header')).not.toContainText('rqdata_jm_20260721_v2')
        await page.getByRole('button', { name: '数据证据' }).click()
        const drawer = page.getByRole('dialog', { name: '数据证据' })
        await expect(drawer).toContainText('rqdata_jm_20260721_v2')
        await expect(drawer).toContainText('mock-lineage')
        await expect(page.locator('body')).not.toContainText('TypeError')
      },
    ],
    [
      'market explains warning impact once and keeps HTDY risk separate',
      async (page) => {
        await page.goto('/market/chart?symbol=jm&contract=JM2609&period=15m')
        const qualityCard = page.getByRole('region', { name: '数据质量影响' })
        await expect(qualityCard).toHaveCount(1)
        await expect(qualityCard).toContainText('数据仅可观察')
        await expect(qualityCard).toContainText('20 个跨文件 OHLCV 冲突')
        await expect(qualityCard).toContainText('严格研究')
        await expect(qualityCard).toContainText('当前 warning 数据作为正式回测或信号输入')
        await expect(qualityCard).not.toContainText('HTDY')

        const compactMarker = page.getByRole('button', { name: /数据质量风险：20 个跨文件冲突/ })
        await expect(compactMarker).toHaveCount(1)
        await compactMarker.click()
        await expect(qualityCard).toBeFocused()

        await expect(page.getByText(/HTDY\/XMA 重绘边界不变/).first()).toBeVisible()
        await expect(page.locator('body')).not.toContainText('/Volumes/mock-data')
      },
    ],
    [
      'runtime shows archive and after-market scheduler sections without the retired scheduler',
      async (page) => {
        await page.goto('/runtime')
        await expect(page.getByRole('heading', { name: '运行状态' }).first()).toBeVisible({ timeout: 15_000 })
        await expect(page.getByText('After-Market Archive').first()).toBeVisible()
        await expect(page.getByText('After-Market Scheduler').first()).toBeVisible()
        await expect(page.getByText('Scheduler', { exact: true })).toHaveCount(0)
        await expect(page.getByText('Archive Lag (trading days)').first()).toBeVisible()
        await expect(page.getByText('Lock Status').first()).toBeVisible()
        await expect(page.getByText('Runtime 时序与恢复信息（只读）')).toBeVisible()
        await expect(page.getByText('Watermark')).toBeVisible()
        await expect(page.getByText('Last success', { exact: true }).first()).toBeVisible()
        await expect(page.getByRole('button', { name: /恢复|重启|重试任务/ })).toHaveCount(0)
      },
    ],
    [
      'runtime keeps a compatible empty state when after-market scheduler is absent',
      async (page) => {
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
      },
    ],
    [
      'signal page keeps source_mode / research-only boundary copy',
      async (page) => {
        await page.goto('/signal')
        await expect(page.getByRole('heading', { name: '信号监控' }).first()).toBeVisible({ timeout: 15_000 })
        const body = await page.locator('body').innerText()
        expect(body).toMatch(/source_mode|历史扫描|replay|live/i)
        expect(body).toMatch(/非自动下单|仅供观察|不构成交易指令/)
        await expect(page.getByRole('button', { name: '紧凑' })).toBeVisible()
        await page.getByRole('button', { name: '详情' }).first().click()
        await expect(page.getByText('exact source_mode')).toBeVisible()
        await expect(page.getByText(/研究输入合格|研究输入需复核|研究输入不合格/)).toBeVisible()
        await expect(page.getByRole('button', { name: '查看 Event' })).toBeVisible()
        await expect(page.getByRole('button', { name: '进入复盘' })).toBeVisible()
        await page.keyboard.press('Escape')
        await expect(page.getByText('exact source_mode')).toBeHidden()
        await page.getByRole('button', { name: '舒适' }).click()
        expect(await page.evaluate(() => localStorage.getItem('guiyi.signal.table-density'))).toBe('medium')
        await page.reload()
        await expect(page.getByRole('button', { name: '舒适' })).toHaveClass(/n-button--primary-type/)
      },
    ],
    [
      'HTDY first-seen event exposes immutable observation evidence without trading capability',
      async (page) => {
        await page.goto('/dashboard')
        await expect(page.getByText('查看新的 HTDY 观察事件')).toBeVisible({ timeout: 15_000 })

        await page.goto('/signal')
        const htdySignalDetail = page
          .getByRole('row')
          .filter({ hasText: 'HTDY 实时重绘观察' })
          .getByRole('button', { name: '详情' })
        await expect(htdySignalDetail).toHaveCount(1, { timeout: 15_000 })
        await htdySignalDetail.click()
        await expect(page.getByText('HTDY first-seen 安全边界')).toBeVisible({ timeout: 15_000 })
        await expect(page.getByText('htdy_original_realtime_first_seen / v1.0')).toBeVisible()
        await expect(page.getByText('signal_review_lineage_v2')).toBeVisible()
        await page.keyboard.press('Escape')

        await page.goto('/signal?tab=events')
        await expect(page.getByText('HTDY 实时重绘观察').first()).toBeVisible({ timeout: 15_000 })
        await page.getByRole('button', { name: '查看 HTDY 证据' }).click()
        await expect(page.getByText('HTDY first-seen 冻结证据')).toBeVisible()
        await expect(page.getByText('htdy_original_realtime_first_seen / v1.0')).toBeVisible()
        await expect(page.getByText('signal_review_lineage_v2')).toBeVisible()
        await expect(page.getByText('future-looking=true')).toBeVisible()
        await expect(page.getByText('repainting=true')).toBeVisible()
        await expect(page.getByText('first-seen 不撤回')).toBeVisible()
        await expect(page.getByText('notification=false')).toBeVisible()
        await expect(page.getByText('auto-order=false')).toBeVisible()
        await expect(page.getByRole('button', { name: /发送|下单|买入|卖出/ })).toHaveCount(0)
        await page.keyboard.press('Escape')

        const htdyEventRow = page.getByRole('row').filter({ hasText: 'HTDY 实时重绘观察' })
        await htdyEventRow.getByRole('button', { name: '打开K线' }).click()
        await expect(page).toHaveURL((url) => (
          url.pathname === '/market/chart'
          && url.searchParams.get('signal_event_id') === '8'
          && url.searchParams.get('data_mode') === 'live'
        ))
        await expect(page.getByText('#8 · signal_created')).toBeVisible({ timeout: 15_000 })
        await expect(page.getByText('live_realtime_repainting').first()).toBeVisible()

        await page.goto('/review?review_id=10&source_type=signal_event&source_id=8&signal_event_id=8')
        await expect(page.getByRole('heading', { name: '复盘中心' }).first()).toBeVisible({ timeout: 15_000 })
        await expect(page.getByText('source_snapshot_schema_version=signal_review_lineage_v2')).toBeVisible({
          timeout: 15_000,
        })
      },
    ],
    [
      'signal event chart review event round-trip restores empty review without writes',
      async (page) => {
        const writes = []
        page.on('request', (request) => {
          if (/^(POST|PUT|PATCH|DELETE)$/.test(request.method())) writes.push(`${request.method()} ${request.url()}`)
        })
        await page.goto('/signal?tab=events')
        await page.getByRole('button', { name: '打开K线' }).first().click()
        await expect(page).toHaveURL((url) => (
          url.pathname === '/market/chart'
          && url.searchParams.get('signal_event_id') === '7'
          && url.searchParams.get('data_mode') === 'live'
        ))
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
      },
    ],
    [
      'security storage, keyboard tabs, focus, and responsive baselines',
      async (page) => {
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
        const strategyTab = page.getByRole('tab', { name: '盘面' })
        await strategyTab.focus()
        await strategyTab.press('ArrowRight')
        await expect(page.getByRole('tab', { name: '信号' })).toHaveAttribute('aria-selected', 'true')
        await expect(page.getByRole('tab', { name: '信号' })).toBeFocused()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()

        await page.setViewportSize({ width: 1024, height: 768 })
        for (const route of ['/dashboard', '/signal', '/review', '/data', '/runtime']) {
          await page.goto(route)
          await expect(page.locator('.page-shell').first()).toBeVisible({ timeout: 15_000 })
          expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
            `${route} overflowed at 1024px`,
          ).toBeTruthy()
        }
      },
    ],
  ]

  for (const [name, fn] of cases) {
    process.stdout.write(`› ${name} ... `)
    try {
      await withPage(browser, fn)
      console.log('ok')
    } catch (err) {
      console.log('FAIL')
      console.error(err)
      failures.push(name)
    }
  }

  await browser.close()
  if (failures.length) {
    console.error(`\n${failures.length} failed: ${failures.join(', ')}`)
    process.exit(1)
  }
  console.log(`\n${cases.length} passed`)
}

run().catch((err) => {
  console.error(err)
  process.exit(1)
})
