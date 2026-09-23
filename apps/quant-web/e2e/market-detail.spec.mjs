import { expect, test } from '@playwright/test'

import {
  assertNewowCupFixtureLifecycle,
  detailBar,
  htdyEvent,
  installDetailFakeWebSocket,
  mockMarketDetail,
  navigateClient,
  newowTrendDetailFixture,
  trendGenericBars,
  subingEvent,
  subingRule,
} from './market-detail.helpers.mjs'

const freeJm = '/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=15m'
const trendJm = '/market/chart?symbol=jm&view=trend'

function freeHistory(total) {
  return Array.from({ length: total }, (_, index) => detailBar('jm', index, 100 + index))
}

async function mockPagedFreeHistory(page, total = 540) {
  const all = freeHistory(total)
  return mockMarketDetail(page, {
    barsPage({ url }) {
      const first = all.slice(-300)
      if (!url.searchParams.get('before')) {
        return {
          bars: first,
          page: { has_more_before: all.length > first.length, next_before: first[0].bar_end },
        }
      }
      const older = all.slice(0, -300)
      return { bars: older, page: { has_more_before: false, next_before: null } }
    },
  })
}

async function mockReadyTrend(page, options = {}) {
  return mockMarketDetail(page, {
    barsPage({ url, symbol }) {
      if (url.searchParams.get('frequency') !== '1d') return undefined
      const bars = trendGenericBars(symbol)
      const upper = symbol.toUpperCase()
      return {
        bars,
        resolvedContractSegments: [
          { contract: `${upper}2601`, start_trading_day: bars[0].trading_day, end_trading_day: bars[3].trading_day },
          { contract: `${upper}2605`, start_trading_day: bars[4].trading_day, end_trading_day: bars.at(-1).trading_day },
        ],
      }
    },
    newowTrendDetail: ({ url, product }) => newowTrendDetailFixture({
      product,
      from: url.searchParams.get('from'),
      through: url.searchParams.get('through'),
    }),
    ...options,
  })
}

async function unifiedShellVisual(page) {
  return page.locator('main.market-detail-page').evaluate((element) => {
    const style = getComputedStyle(element)
    const navigation = element.querySelector('.market-navigation')
    const quote = element.querySelector('.quote-header')
    if (!navigation || !quote) throw new Error('unified shell chrome is missing')
    const navigationStyle = getComputedStyle(navigation)
    const quoteStyle = getComputedStyle(quote)
    const navigationBox = navigation.getBoundingClientRect()
    return {
      background: style.backgroundColor,
      color: style.color,
      paddingLeft: style.paddingLeft,
      paddingRight: style.paddingRight,
      navigationMarginLeft: navigationStyle.marginLeft,
      navigationMarginRight: navigationStyle.marginRight,
      navigationLeft: navigationBox.left,
      navigationRight: navigationBox.right,
      quoteDisplay: quoteStyle.display,
      quoteClass: quote.className,
    }
  })
}

async function enableRangeDetector(page) {
  const control = page.getByRole('group', { name: '主图指标' }).getByRole('button', { name: /箱体识别/ })
  await control.click()
  await expect(control).toHaveAttribute('aria-pressed', 'true')
}

test('missing view migrates to the unified Free identity', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&series_kind=actual_dominant&frequency=15m')

  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('view')).toBe('free')
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('15m')
})

test('Newow daily route mounts its chart while its bounded independent daily quote is pending', async ({ page }) => {
  const requests = await mockMarketDetail(page)
  const typedRequests = []
  const genericRequests = []
  await page.route('**/api/v1/market/newow/strategy-detail**', async (route) => {
    typedRequests.push(new URL(route.request().url()))
    await new Promise(() => {})
  })
  await page.route('**/api/v1/market/bars/page**', async (route) => {
    genericRequests.push(new URL(route.request().url()))
    await new Promise(() => {})
  })

  await page.goto('/market/chart?symbol=jm&view=newow&strategy=trend&series_kind=actual_dominant&frequency=1d')

  await expect(page.locator('[data-detail-workspace="newow"]')).toBeVisible()
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
  await expect(page.getByText('正在读取 Newow 主图…', { exact: true })).toBeVisible()
  await expect.poll(() => typedRequests.length).toBe(1)
  expect(typedRequests.map((url) => url.searchParams.get('section'))).toEqual(['chart'])
  expect(genericRequests).toHaveLength(1)
  expect(Object.fromEntries(genericRequests[0].searchParams)).toEqual({
    series_kind: 'actual_dominant', symbol: 'jm', frequency: '1d',
    before: '2026-09-03T07:00:00.000001Z', limit: '2',
  })
  expect(requests.filter((url) => url.pathname.endsWith('/research/product'))).toEqual([])
})

test('Free mounts its generic workspace without the legacy sidebar or strategy markers', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const shell = page.locator('[data-detail-ready="true"]')
  await expect(shell).toBeVisible()
  await expect(shell.getByText('焦煤', { exact: true }).first()).toBeVisible()
  await expect(page.getByTestId('product-check-sidebar')).toHaveCount(0)
  await expect(page.locator('.product-workspace__sidebar')).toHaveCount(0)
  await expect(shell.locator('[data-detail-workspace="free"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-research-marker-count', '0')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-rendered-marker-count', '0')
  await expect(page.getByText('火天大有（原始观察）', { exact: true })).toHaveCount(0)
  await expect(shell.locator('[data-detail-workspace="free"]').getByText(/SuBing|牛哇|Newow/, { exact: false })).toHaveCount(0)

  const order = await shell.locator('[data-detail-section]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-detail-section')))
  expect(order.slice(0, 4)).toEqual(['topbar', 'quote', 'view-nav', 'workspace-slot'])
})

test('Newow HTDY and Free share one visual shell while preserving quote semantics', async ({ page }) => {
  await mockReadyTrend(page)
  await page.goto('/market/chart?symbol=jm&view=newow&strategy=trend&series_kind=actual_dominant&frequency=1w')

  const quote = page.locator('.quote-header')
  await expect(quote).toContainText('最近日线收盘')
  await expect(quote).toContainText('非实时')
  const newowVisual = await unifiedShellVisual(page)
  expect(newowVisual.quoteClass).toContain('quote-header--unified')
  expect(newowVisual.navigationMarginLeft).toBe('-24px')
  expect(newowVisual.navigationMarginRight).toBe('-24px')
  expect(newowVisual.navigationLeft).toBe(0)
  expect(newowVisual.navigationRight).toBe(page.viewportSize().width)

  await page.getByRole('tab', { name: '火天大有' }).click()
  await expect(page).toHaveURL(/view=htdy/)
  await expect(page.locator('[data-detail-workspace="htdy"]')).toBeVisible()
  await expect(quote).toContainText('15分钟收盘')
  await expect(quote).not.toContainText('最近日线收盘')
  await expect(quote).not.toContainText('非实时')
  expect(await unifiedShellVisual(page)).toEqual(newowVisual)

  await page.getByRole('tab', { name: '自由看盘' }).click()
  await expect(page).toHaveURL(/view=free/)
  await expect(page.locator('[data-detail-workspace="free"]')).toBeVisible()
  await expect(quote).toContainText('15分钟收盘')
  await expect(quote).not.toContainText('最近日线收盘')
  await expect(quote).not.toContainText('非实时')
  expect(await unifiedShellVisual(page)).toEqual(newowVisual)
})

test('Free Range warm-up has a 1280 by 800 baseline and does not create a strategy marker', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await enableRangeDetector(page)
  await expect(page.getByText(/箱体历史预载不足|箱体历史预载失败/)).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-rendered-marker-count', '0')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-chart-viewport-ready', 'true')
  await page.mouse.move(0, 0)
  await expect(page.locator('[data-detail-workspace="free"]')).toHaveScreenshot('market-detail-free-range-1280x800.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 400,
  })
})

test('Free Range reaches its fixed ready boundary without strategy markers', async ({ page }) => {
  const requests = await mockPagedFreeHistory(page)
  await page.goto(freeJm)

  await enableRangeDetector(page)
  await expect.poll(() => requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBeGreaterThanOrEqual(2)
  await expect(page.locator('[data-detail-workspace="free"]')).toHaveAttribute('data-range-detector-warmup', 'ready')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-rendered-marker-count', '0')
  await expect(page.getByRole('status')).toContainText('Range Detector 只读回画展示；确认前不可用于策略判断。')
  await expect(page.getByText('箱体历史预载不足')).toHaveCount(0)
})

test('Free shows the fixed Range read-only warning while history is insufficient', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await enableRangeDetector(page)
  await expect(page.getByRole('status')).toContainText('箱体历史预载不足；Range Detector 只读回画展示；确认前不可用于策略判断。')
})

test('Free pagination keeps an away-from-latest viewport while prepending history', async ({ page }) => {
  const requests = await mockPagedFreeHistory(page, 600)
  await page.goto(freeJm)

  const chart = page.locator('.chart')
  await chart.scrollIntoViewIfNeeded()
  const chartBox = await chart.boundingBox()
  await page.mouse.move(chartBox.x + chartBox.width * 0.94, chartBox.y + chartBox.height * 0.5)
  await page.mouse.down()
  await page.mouse.move(chartBox.x + chartBox.width * 0.08, chartBox.y + chartBox.height * 0.5, { steps: 12 })
  await page.mouse.up()
  for (let index = 0; index < 2; index += 1) {
    await page.mouse.move(chartBox.x + chartBox.width * 0.08, chartBox.y + chartBox.height * 0.5)
    await page.mouse.down()
    await page.mouse.move(chartBox.x + chartBox.width * 0.94, chartBox.y + chartBox.height * 0.5, { steps: 12 })
    await page.mouse.up()
  }

  await expect.poll(() => requests.filter((url) => url.pathname.endsWith('/bars/page')).length).toBeGreaterThanOrEqual(2)
  await expect(page.getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
})

test('Free exposes fullscreen enter, exit, and return-to-latest controls', async ({ page }) => {
  await mockPagedFreeHistory(page, 600)
  await page.goto(freeJm)

  const chart = page.locator('.chart')
  await chart.scrollIntoViewIfNeeded()
  const chartBox = await chart.boundingBox()
  for (let index = 0; index < 2; index += 1) {
    await page.mouse.move(chartBox.x + chartBox.width * 0.08, chartBox.y + chartBox.height * 0.5)
    await page.mouse.down()
    await page.mouse.move(chartBox.x + chartBox.width * 0.94, chartBox.y + chartBox.height * 0.5, { steps: 12 })
    await page.mouse.up()
  }
  await expect(page.getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '回到最新', exact: true }).click()
  await expect(page.getByRole('button', { name: '回到最新', exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: '全屏图表', exact: true }).click()
  await expect(page.getByRole('button', { name: '退出全屏', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '退出全屏', exact: true }).click()
  await expect(page.getByRole('button', { name: '全屏图表', exact: true })).toBeVisible()
})

test('shared K-line focus retries an unresolved target and clears it on identity replacement', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)
  await page.evaluate(async () => {
    const { createApp, h, ref } = await import('/node_modules/.vite/deps/vue.js')
    const { default: MarketKlineStage } = await import('/src/components/market/detail/MarketKlineStage.vue')
    const bars = [
      { time: '2026-09-03T02:30:00Z', open: 100, high: 102, low: 99, close: 101, volume: 1000, openInterest: 2000 },
      { time: '2026-09-03T02:45:00Z', open: 101, high: 103, low: 100, close: 102, volume: 1001, openInterest: 2001 },
    ]
    const focus = ref('2026-09-03T00:00:00Z')
    const identity = ref('focus-a')
    const resolved = []
    const app = createApp({
      setup() {
        return () => h(MarketKlineStage, {
          bars,
          mutation: { kind: 'replace', bars },
          loading: false,
          error: null,
          period: '15m',
          seriesKind: 'actual_dominant',
          visibleMainIndicators: [],
          rangeDetectorSourceIdentity: 'focus-test',
          rangeDetectorAnchorTime: null,
          identityKey: identity.value,
          focusBarEnd: focus.value,
          onFocusResolved: (value) => resolved.push(value),
        })
      },
    })
    const host = document.createElement('div')
    host.id = 'focus-stage-contract'
    document.body.append(host)
    app.mount(host)
    window.__marketKlineFocusContract = { focus, identity, resolved, app }
  })

  await expect(page.locator('#focus-stage-contract').getByRole('button', { name: '回到最新', exact: true })).toHaveCount(0)
  await page.evaluate(() => { window.__marketKlineFocusContract.focus.value = '2026-09-03T02:45:00Z' })
  await expect(page.locator('#focus-stage-contract').getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__marketKlineFocusContract.resolved)).toEqual(['2026-09-03T02:45:00Z'])
  await page.evaluate(() => {
    window.__marketKlineFocusContract.identity.value = 'focus-b'
    window.__marketKlineFocusContract.focus.value = null
  })
  await expect(page.locator('#focus-stage-contract').getByRole('button', { name: '回到最新', exact: true })).toHaveCount(0)
})

test('shared K-line focus also resolves an existing daily trading day', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)
  await page.evaluate(async () => {
    const { createApp, h } = await import('/node_modules/.vite/deps/vue.js')
    const { default: MarketKlineStage } = await import('/src/components/market/detail/MarketKlineStage.vue')
    const bars = [
      { time: '2026-09-01T07:00:00Z', trading_day: '2026-09-01', open: 100, high: 102, low: 99, close: 101, volume: 1000, openInterest: 2000 },
      { time: '2026-09-02T07:00:00Z', trading_day: '2026-09-02', open: 101, high: 103, low: 100, close: 102, volume: 1001, openInterest: 2001 },
    ]
    const resolved = []
    const app = createApp({
      setup() {
        return () => h(MarketKlineStage, {
          bars,
          mutation: { kind: 'replace', bars },
          loading: false,
          error: null,
          period: '1d',
          seriesKind: 'actual_dominant',
          visibleMainIndicators: [],
          rangeDetectorSourceIdentity: 'focus-daily-test',
          rangeDetectorAnchorTime: null,
          identityKey: 'focus-daily',
          focusBarEnd: '2026-09-02T07:00:00Z',
          onFocusResolved: (value) => resolved.push(value),
        })
      },
    })
    const host = document.createElement('div')
    host.id = 'focus-daily-stage-contract'
    document.body.append(host)
    app.mount(host)
    window.__marketKlineDailyFocusContract = { resolved, app }
  })

  await expect(page.locator('#focus-daily-stage-contract').getByRole('button', { name: '回到最新', exact: true })).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__marketKlineDailyFocusContract.resolved)).toEqual(['2026-09-02T07:00:00Z'])
})

test('Free identity controls keep the selected contract in the URL', async ({ page }) => {
  const requests = await mockMarketDetail(page)
  await page.goto(freeJm)

  await page.getByLabel('指定合约').fill('JM2605')
  await page.getByRole('button', { name: '指定合约' }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('contract')
  expect(new URL(page.url()).searchParams.get('contract')).toBe('JM2605')
  await expect.poll(() => requests.some((url) => (
    url.pathname.endsWith('/bars/page')
    && url.searchParams.get('series_kind') === 'contract'
    && url.searchParams.get('contract') === 'JM2605'
  ))).toBe(true)
})

test('Free uses one shared series and frequency control surface while keeping a contract selector', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await expect(page.getByRole('button', { name: '真实主力', exact: true })).toHaveCount(1)
  await expect(page.getByRole('button', { name: '15m', exact: true })).toHaveCount(1)
  await expect(page.getByLabel('指定合约')).toHaveCount(1)
  await expect(page.getByRole('button', { name: /市场背景/ })).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('button', { name: /数据详情/ })).toHaveAttribute('aria-expanded', 'false')
})

test('Free reloads continuous, 60m, and daily identities without inventing a physical contract', async ({ page }) => {
  const requests = await mockMarketDetail(page)
  await page.goto(freeJm)
  const seriesControls = page.getByRole('group', { name: '序列' })
  const frequencyControls = page.getByRole('group', { name: '周期' })

  await seriesControls.getByRole('button', { name: '主连', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('continuous')
  await expect(page.locator('.detail-topbar__contract')).toHaveText('JM')
  await expect.poll(() => requests.some((url) => (
    url.pathname.endsWith('/bars/page') && url.searchParams.get('series_kind') === 'continuous'
  ))).toBe(true)

  await frequencyControls.getByRole('button', { name: '60m', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('frequency')).toBe('60m')
  await frequencyControls.getByRole('button', { name: '日K', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('frequency')).toBe('1d')
  await expect.poll(() => requests.some((url) => (
    url.pathname.endsWith('/bars/page') && url.searchParams.get('frequency') === '1d'
  ))).toBe(true)
})

test('Free restores enabled EMA preferences after reload', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const ema10 = page.getByRole('group', { name: '主图指标' }).getByRole('button', { name: /EMA10/ })
  await ema10.click()
  await expect(ema10).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page.getByRole('group', { name: '主图指标' }).getByRole('button', { name: /EMA10/ })).toHaveAttribute('aria-pressed', 'true')
})

test('Free clears a contract when the product changes and keeps HTDY preferences untouched', async ({ page }) => {
  const recursiveUpdates = []
  page.on('console', (message) => {
    if (message.text().includes('Maximum recursive updates exceeded')) recursiveUpdates.push(message.text())
  })
  await page.addInitScript(() => {
    localStorage.setItem('guiyi.market.detail.preferences.v1', JSON.stringify({
      version: 1, lastView: 'htdy',
      htdy: { seriesKind: 'continuous', frequency: '30m', optionalEmaIndicators: ['ema_60'], showRangeDetector: true },
      free: { seriesKind: 'actual_dominant', frequency: '15m', optionalEmaIndicators: [], showRangeDetector: false },
    }))
  })
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=contract&contract=JM2605&frequency=15m')

  const productSearch = page.getByRole('combobox', { name: '搜索60品种' })
  await productSearch.fill('rb')
  await productSearch.press('Enter')
  await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('actual_dominant')
  expect(new URL(page.url()).searchParams.has('contract')).toBe(false)
  await expect(page.getByText('已切换品种，指定合约已清除并回到真实主力。')).toBeVisible()
  await enableRangeDetector(page)
  const preferences = await page.evaluate(() => JSON.parse(localStorage.getItem('guiyi.market.detail.preferences.v1')))
  expect(recursiveUpdates).toEqual([])
  expect(preferences.lastView).toBe('htdy')
  expect(preferences.htdy).toEqual({ seriesKind: 'continuous', frequency: '30m', optionalEmaIndicators: ['ema_60'], showRangeDetector: true })
})

test('shared quote header exposes quote availability and display source', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const quote = page.locator('[data-detail-section="quote"]')
  await expect(quote.getByText('报价可用', { exact: true })).toBeVisible()
  await expect(quote).toContainText('15分钟收盘')
  await expect(quote).toContainText('截至 2026-09-03 10:45 北京时间')
})

test('invalid identity fails closed and only recovers after an explicit click', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=2m')

  await expect(page.getByRole('heading', { name: '详情页地址无效' })).toBeVisible()
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('2m')
  await page.getByRole('button', { name: '恢复安全设置' }).click()
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('15m')
})

test('legacy Trend route migrates once into the unified Newow trend identity', async ({ page }) => {
  await mockMarketDetail(page)
  await page.route('**/api/v1/market/newow/strategy-detail**', route => route.abort('blockedbyclient'))
  await page.goto('/market/chart?symbol=jm&view=trend&focus_bar_end=2026-09-03T07%3A00%3A00Z')

  await expect.poll(() => new URL(page.url()).searchParams.get('view')).toBe('newow')
  const route = new URL(page.url())
  expect(Object.fromEntries(route.searchParams)).toEqual({
    symbol: 'jm', view: 'newow', strategy: 'trend', series_kind: 'actual_dominant',
    frequency: '1d', focus_bar_end: '2026-09-03T07:00:00Z',
  })
  await expect(page.getByText('当前牛哇周期未开放', { exact: true })).toHaveCount(0)
  await expect(page.getByTestId('market-detail-migration-notice')).toContainText('旧趋势详情已迁移到牛哇趋势策略')
  await expect(page.locator('[data-detail-workspace="trend"]')).toHaveCount(0)
  await expect(page.getByTestId('newow-trend-chart-stage')).toHaveCount(0)
})

test('Free, HTDY, and SuBing remain isolated workspaces with only SuBing Event facts', async ({ page }) => {
  const requests = await mockReadyTrend(page, {
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  await page.goto(freeJm)
  await expect(page.locator('[data-detail-workspace="free"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-research-marker-count', '0')

  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.locator('[data-detail-workspace="htdy"]')).toBeVisible()
  await expect(page.getByText(/当前回画观察与持久首次识别 Event 分别展示/)).toBeVisible()
  await page.getByRole('tab', { name: '预警与运行' }).click()
  await expect(page.getByText(/仅真实主力序列的 HTDY AlertEvent/)).toBeVisible()

  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.locator('[data-detail-workspace="subing"]')).toBeVisible()
  await expect(page.getByText(/实际预警记录 · 以下仅为已持久化 AlertEvent/)).toBeVisible()
  await expect(page.getByText(/S↑ 多头预警/).first()).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await page.getByRole('tab', { name: '历史记录', exact: true }).click()
  await expect(page.locator('[data-detail-workspace="subing"] .detail-section-tabs__history')).toContainText('Bar 2026-09-03 10:45 北京时间')
  expect(requests.alertRequests.every(({ method }) => method === 'GET')).toBe(true)
  expect(requests.newowRequests).toEqual([])
})

test('SuBing projects Rule-specific runtime warm-up and failure states', async ({ page }) => {
  let errorType = 'evaluation_warming_up'
  await mockReadyTrend(page, {
    alertRules: [subingRule()],
    subingRuntimeRuleStatus: () => ({ error_type: errorType }),
  })
  await page.goto('/market/chart?symbol=jm&view=subing')
  const runtimeSection = page.locator('.detail-insight-deck').getByText(/正在 warm-up/)
  await expect(runtimeSection).toBeVisible()

  errorType = 'evaluation_failed'
  await page.reload()
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.locator('.detail-insight-deck').getByText(/评估失败/)).toBeVisible()
})

test('SuBing has stable desktop and narrow viewport visuals with selectable history', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockReadyTrend(page, {
    barsPage: ({ url, symbol }) => url.searchParams.get('frequency') === '15m'
      ? { bars: Array.from({ length: 40 }, (_, index) => detailBar(symbol, index, 100 + index)) }
      : undefined,
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  await page.goto('/market/chart?symbol=jm&view=subing')
  const workspace = page.locator('[data-detail-workspace="subing"]')
  await expect(workspace).toBeVisible()
  const chart = page.getByTestId('kline-shell')
  await chart.scrollIntoViewIfNeeded()
  await expect(page).toHaveScreenshot('market-detail-subing-1440x900.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 500,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('tab', { name: '历史记录', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '历史记录' })).toContainText('Bar 2026-09-03 10:45 北京时间')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page).toHaveScreenshot('market-detail-subing-390x844.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 500,
  })
})

test('SuBing history opens the matching immutable AlertEvent detail while chart markers remain passive', async ({ page }) => {
  await mockReadyTrend(page, {
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await page.getByRole('tab', { name: '历史记录', exact: true }).click()
  await page.locator('[data-detail-workspace="subing"] .detail-section-tabs__history button').first().click()
  await expect(page.getByRole('dialog', { name: '苏冰预警详情' })).toContainText('S↑ 多头预警 · 2026-09-03 10:45 北京时间 · JM2601')
})

test('SuBing consumes its exact AlertEvent focus once', async ({ page }) => {
  await mockReadyTrend(page, {
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  const focus = '2026-09-03T02:45:00.000Z'
  await page.goto(`/market/chart?symbol=jm&view=subing&focus_bar_end=${encodeURIComponent(focus)}`)
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
})

test('SuBing focus remains visible after viewport readiness settles', async ({ page }) => {
  await mockReadyTrend(page, {
    barsPage: ({ url, symbol }) => url.searchParams.get('frequency') === '15m'
      ? { bars: Array.from({ length: 600 }, (_, index) => detailBar(symbol, index, 100 + index)) }
      : undefined,
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  const focus = '2026-09-03T02:45:00.000Z'
  await page.goto(`/market/chart?symbol=jm&view=subing&focus_bar_end=${encodeURIComponent(focus)}`)
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-chart-viewport-ready', 'true')
  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  const range = await page.getByTestId('kline-shell').evaluate((element) => {
    const instance = element.__vueParentComponent
    return instance?.setupState?.chart?.timeScale().getVisibleLogicalRange() ?? null
  })
  expect(range).not.toBeNull()
  expect(range.from).toBeLessThanOrEqual(1)
  expect(range.to).toBeGreaterThanOrEqual(1)
  expect(range.to - range.from).toBeLessThan(100)
})

test('HTDY resolves immutable Event focus across every official frequency', async ({ page }) => {
  const cases = [
    ['1m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['5m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['15m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['30m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['60m', '2026-09-03T02:30:00.000Z', '2026-09-03'],
    ['1d', '2026-07-02T02:45:00.000Z', '2026-07-02', '2026-07-02T02:46:00.000Z'],
    ['1w', '2026-07-08T02:45:00.000Z', '2026-07-08', '2026-07-08T02:46:00.000Z'],
  ]
  let currentCase = null
  const requests = await mockMarketDetail(page, {
    barsPage: ({ url, symbol }) => {
      const frequency = url.searchParams.get('frequency')
      if (frequency === '1d' || frequency === '1w') {
        const total = frequency === '1w' ? 10 : 60
        return { bars: Array.from({ length: total }, (_, index) => {
          const day = new Date(Date.UTC(2026, 6, 1 + index * (frequency === '1w' ? 7 : 1))).toISOString().slice(0, 10)
          return { ...detailBar(symbol, index, 100 + index), bar_end: `${day}T07:00:00.000Z`, trading_day: day }
        }) }
      }
      return { bars: Array.from({ length: 60 }, (_, index) => detailBar(symbol, index, 100 + index)) }
    },
    alertEvents: () => currentCase ? [htdyEvent('jm', currentCase[0], currentCase[1], currentCase[2], currentCase[3])] : [],
  })
  for (const [frequency, focus, tradingDay, detectedAt] of cases) {
    currentCase = [frequency, focus, tradingDay, detectedAt]
    await page.goto(`/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=${frequency}&focus_bar_end=${encodeURIComponent(focus)}`)
    await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
    await page.getByRole('tab', { name: '历史记录' }).click()
    await expect(page.locator('.detail-section-tabs__history')).toContainText('买入观察')
    await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
    await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  }
  const eventRequests = requests.alertRequests.filter(({ url }) => url.pathname.endsWith('/events'))
  expect(eventRequests.length).toBeGreaterThanOrEqual(7)
  expect(new Set(eventRequests.map(({ url }) => url.searchParams.get('frequency'))))
    .toEqual(new Set(cases.map(([frequency]) => frequency)))
  expect(eventRequests.every(({ url }) => url.searchParams.get('rule_code') === 'htdy_original_15m')).toBe(true)
  expect(requests.alertRequests.every(({ method }) => method !== 'PUT')).toBe(true)

  const before = eventRequests.length
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=continuous&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=contract&contract=JM2601&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  expect(requests.alertRequests.filter(({ url }) => url.pathname.endsWith('/events'))).toHaveLength(before)
})

test('HTDY keeps last successful immutable Event evidence when a later Event refresh fails', async ({ page }) => {
  let eventCalls = 0
  await mockMarketDetail(page, {
    alertEvents: () => (++eventCalls === 1 ? [htdyEvent('jm', '15m')] : 'error'),
  })
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await expect(page.getByRole('tab', { name: '历史记录' })).toBeVisible()
  await expect.poll(() => eventCalls, { timeout: 35_000 }).toBeGreaterThan(1)
  await page.getByRole('tab', { name: '历史记录' }).click()
  await expect(page.locator('.detail-section-tabs__history')).toContainText('买入观察')
  await expect(page.getByText(/Bar 2026-09-03 10:45 北京时间/)).toBeVisible()
})

test('HTDY focus resolves and keyboard product selection stays in the unified identity', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&overlay=htdy&series_kind=actual_dominant&frequency=30m&focus_bar_end=2026-09-03T02%3A30%3A00Z')
  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  await page.getByRole('button', { name: '切换品种或合约' }).click()
  const symbol = page.getByRole('combobox', { name: '搜索60品种' })
  await expect(symbol).toBeFocused()
  await symbol.fill('rb')
  await symbol.press('Enter')
  await expect.poll(() => new URL(page.url()).searchParams.get('symbol')).toBe('rb')
  expect(new URL(page.url()).searchParams.get('view')).toBe('htdy')
  expect(new URL(page.url()).searchParams.get('frequency')).toBe('30m')
  await expect(page.getByText('返回旧版详情')).toHaveCount(0)
})

test('a late JM response cannot overwrite a newer RB identity', async ({ page }) => {
  await mockMarketDetail(page, { researchDelayMs: { jm: 400 } })
  await page.goto(freeJm)
  await navigateClient(page, '/market/chart?symbol=rb&view=free&series_kind=actual_dominant&frequency=15m')

  const shell = page.locator('[data-detail-ready="true"]')
  await expect(shell.getByText('螺纹钢', { exact: true }).first()).toBeVisible()
  await expect(shell.getByText('201', { exact: true })).toBeVisible()
  await page.waitForTimeout(500)
  await expect(shell.getByText('螺纹钢', { exact: true }).first()).toBeVisible()
  await expect(shell.getByText('201', { exact: true })).toBeVisible()
})

test('leaving the Free shell closes its live series resource', async ({ page }) => {
  await installDetailFakeWebSocket(page)
  await mockMarketDetail(page, { live: true })
  await page.route('**/api/v1/market/newow/strategy-detail**', route => route.abort('blockedbyclient'))
  await page.goto(freeJm)

  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect.poll(() => page.evaluate(() => (
    window.__marketDetailSockets?.filter((socket) => socket.url.includes('/api/v1/market/ws') && !socket.closed).length ?? 0
  ))).toBeGreaterThan(0)

  await navigateClient(page, '/market/chart?symbol=jm&view=newow&strategy=trend&series_kind=actual_dominant&frequency=1d')
  await expect(page.locator('[data-detail-workspace="newow"]')).toBeVisible()
  await expect.poll(() => page.evaluate(() => (
    window.__marketDetailSockets
      ?.filter((socket) => socket.url.includes('/api/v1/market/ws'))
      .every((socket) => socket.closed) ?? false
  ))).toBe(true)
})

test('390px shell opens market facts in a keyboard-dismissible dialog and does not invent history', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockMarketDetail(page)
  await page.goto(freeJm)

  const disclosure = page.getByRole('button', { name: /更多行情数据/ })
  await disclosure.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: '行情数据详情' })
  await expect(dialog).toBeVisible()
  expect(await dialog.evaluate((element) => {
    const bounds = element.getBoundingClientRect()
    return bounds.left >= 0 && bounds.right <= window.innerWidth && bounds.top >= 0 && bounds.bottom <= window.innerHeight
  })).toBe(true)
  await page.mouse.click(8, 8)
  await expect(dialog).not.toBeVisible()
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false')
  await expect(disclosure).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(disclosure).toBeFocused()
  await expect(page.getByRole('button', { name: '历史记录' })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.locator('[data-detail-workspace="free"]')).toHaveScreenshot('market-detail-free-390.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 400,
  })
})

test('market facts dialog closes when its identity changes', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await page.evaluate(async () => {
    const { createApp, h, ref } = await import('/node_modules/.vite/deps/vue.js')
    const { default: MarketFactsDialog } = await import('/src/components/market/detail/MarketFactsDialog.vue')
    const host = document.createElement('div')
    host.id = 'market-facts-dialog-browser-contract'
    document.body.append(host)
    const open = ref(true)
    const identity = ref('free:jm:actual_dominant:15m')
    createApp({
      setup: () => () => h(MarketFactsDialog, {
        open: open.value,
        title: '行情数据详情测试',
        identityKey: identity.value,
        onClose: () => { open.value = false },
      }),
    }).mount(host)
    window.__changeMarketFactsIdentity = () => { identity.value = 'free:rb:actual_dominant:15m' }
  })

  const dialog = page.getByRole('dialog', { name: '行情数据详情测试' })
  await expect(dialog).toBeVisible()
  await page.evaluate(() => window.__changeMarketFactsIdentity())
  await expect(dialog).not.toBeVisible()
})

test('mobile history drawer traps focus, closes with Escape, and restores its trigger', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockMarketDetail(page)
  await page.goto(freeJm)
  await page.evaluate(async () => {
    const { createApp, h, ref } = await import('/node_modules/.vite/deps/vue.js')
    const { default: MarketDetailDrawer } = await import('/src/components/market/detail/MarketDetailDrawer.vue')
    const host = document.createElement('div')
    host.id = 'drawer-browser-contract'
    document.body.append(host)
    const open = ref(false)
    const app = createApp({
      setup() {
        return () => h('div', [
          h('button', { id: 'drawer-trigger', onClick: () => { open.value = true } }, '打开历史'),
          h(MarketDetailDrawer, {
            open: open.value,
            title: '历史记录',
            onClose: () => { open.value = false },
          }, { default: () => h('button', { id: 'drawer-action' }, '历史项') }),
        ])
      },
    })
    app.mount(host)
    window.__marketDetailDrawerContractApp = app
  })

  const trigger = page.locator('#drawer-trigger')
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: '历史记录' })
  await expect(dialog).toBeVisible()
  await expect(page.getByRole('button', { name: '关闭' })).toBeFocused()
  await page.locator('#drawer-action').focus()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: '关闭' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

for (const width of [1440, 390]) {
  test(`unified migrated Free preview and keyboard at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await mockMarketDetail(page, { barsPage() {
      const bars = Array.from({ length: 300 }, (_, index) => {
        const close = 100 + index * 0.03 + Math.sin(index / 9) * 5 + Math.sin(index / 3) * 1.5
        const open = close + Math.cos(index / 4) * 1.2
        return { ...detailBar('jm', index, close), open, high: Math.max(open, close) + 0.8, low: Math.min(open, close) - 0.8 }
      })
      return { bars, page: { has_more_before: false, next_before: null } }
    } })
    await page.goto('/market/chart?symbol=jm&series_kind=contract&contract=JM2601&frequency=60m')
    await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
    expect(new URL(page.url()).searchParams.get('contract')).toBe('JM2601')
    await page.getByRole('button', { name: '切换品种或合约' }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('combobox', { name: '搜索60品种' })).toBeFocused()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-chart-viewport-ready', 'true')
    await page.locator('[data-detail-section="topbar"]').scrollIntoViewIfNeeded()
    await page.screenshot({ path: `/tmp/market-convergence-free-${width}-top.png`, fullPage: true })
    await page.getByTestId('kline-shell').scrollIntoViewIfNeeded()
    await page.screenshot({ path: `/tmp/market-convergence-free-${width}.png`, fullPage: true })
  })
}

test('unavailable bars still permit keyboard product recovery inside the unified page', async ({ page }) => {
  await mockMarketDetail(page)
  await page.route('**/api/v1/market/bars/page**', async route => {
    await route.fulfill({ status: 409, json: { detail: { code: 'QUERY_WINDOW_EMPTY' } } })
  })
  await page.goto(freeJm)
  await expect(page.getByText('行情事实不可用', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '切换品种或合约' }).click()
  const symbol = page.getByRole('combobox', { name: '搜索60品种' })
  await expect(symbol).toBeFocused()
  await symbol.fill('rb')
  await symbol.press('Enter')
  await expect.poll(() => new URL(page.url()).searchParams.get('symbol')).toBe('rb')
  expect(new URL(page.url()).searchParams.get('view')).toBe('free')
})

test('product selection closes once, keeps focus, and reopens only after a fresh user focus', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)
  await page.getByRole('button', { name: '切换品种或合约' }).click()
  const productSearch = page.getByRole('combobox', { name: '搜索60品种' })
  await productSearch.fill('rb')
  await page.getByRole('option', { name: /螺纹钢 RB/ }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('symbol')).toBe('rb')
  await expect(productSearch).toBeFocused()
  await expect(page.getByRole('listbox', { name: '搜索60品种' })).toHaveCount(0)
  await productSearch.blur()
  await productSearch.focus()
  await expect(page.getByRole('listbox', { name: '搜索60品种' })).toBeVisible()
})

test('cancelled older migration cannot activate its identity after a newer route', async ({ page }) => {
  const requests = await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=rb&view=free&series_kind=actual_dominant&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await page.evaluate(async () => {
    const { router } = await import('/src/app/router.ts')
    window.__releaseMigration = null
    router.beforeEach(to => {
      if (to.query.symbol === 'jm' && to.query.view === 'free') return new Promise(resolve => { window.__releaseMigration = resolve })
    })
    await router.push('/market/chart?symbol=jm&frequency=15m')
  })
  await expect.poll(() => page.evaluate(() => typeof window.__releaseMigration)).toBe('function')
  await navigateClient(page, '/market/chart?symbol=rb&view=free&series_kind=actual_dominant&frequency=60m')
  await page.evaluate(() => window.__releaseMigration(true))
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('symbol')).toBe('rb')
  await expect(page.locator('.detail-topbar__name')).toHaveText('螺纹钢')
  expect(requests.filter(url => url.pathname.endsWith('/bars/page') && url.searchParams.get('symbol') === 'jm')).toHaveLength(0)
})
