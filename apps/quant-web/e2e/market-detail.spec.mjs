import { expect, test } from '@playwright/test'
import { buildNewowSplitFixtureEnvelopeForTest, installNewowProductFixtures, newowRoute, productRequests, assertNoUnexpectedRequests } from './newow-product.helpers.mjs'

import {
  detailBar,
  htdyEvent,
  installDetailFakeWebSocket,
  mockMarketDetail,
  navigateClient,
  trendGenericBars,
  subingEvent,
  subingRule,
} from './market-detail.helpers.mjs'

const freeJm = '/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=15m'

function freeHistory(total) {
  return Array.from({ length: total }, (_, index) => detailBar('jm', index, 100 + index))
}

async function mockPagedFreeHistory(page, total = 900) {
  const all = freeHistory(total)
  return mockMarketDetail(page, {
    barsPage({ url }) {
      const before = url.searchParams.get('before')
      const end = before ? all.findIndex(bar => bar.bar_end === before) : all.length
      expect(end).toBeGreaterThan(0)
      const start = Math.max(0, end - 300)
      const bars = all.slice(start, end)
      return { bars, page: { has_more_before: start > 0, next_before: start > 0 ? bars[0].bar_end : null } }
    },
  })
}

async function mockDetailDailyQuote(page, options = {}) {
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
      quoteUnified: quote.classList.contains('quote-header--unified'),
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

// Shell tests serve existing typed chart fixtures but explicitly leave lazy research unavailable.
// Record those reads separately so they cannot hide premature requests before verification.
async function installNewowShellFixture(page, options = {}) {
  const state = await installNewowProductFixtures(page, options)
  state.secondaryRequests = []
  await page.route('**/api/v1/market/newow/strategy-detail**', route => {
    const url = new URL(route.request().url())
    if (!['reference', 'explanation'].includes(url.searchParams.get('section'))) return route.fallback()
    expect(route.request().method()).toBe('GET')
    state.secondaryRequests.push(url)
    return route.fulfill({ status: 503, json: { detail: 'Explicit fixture: shell-only research unavailable' } })
  })
  return state
}

test('Newow daily route keeps only a bounded price preview until the current chart is verified', { tag: '@contract-alignment' }, async ({ page }) => {
  const state = await installNewowShellFixture(page, { deferOnce: 'trend:1d:chart' })
  await page.goto(newowRoute())

  const preview = page.getByRole('region', { name: '价格预览', exact: true })
  await expect(preview.locator('canvas').first()).toBeVisible()
  await expect(preview).toContainText('截止')
  await expect(preview).toContainText('策略确认后显示')
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveCount(0)
  await expect.poll(() => productRequests(state, 'chart').length).toBe(1)
  const currentChart = productRequests(state, 'chart')[0].url
  expect(currentChart.searchParams.get('resolve_current')).toBe('true')
  expect(currentChart.searchParams.has('as_of')).toBe(false)
  expect(productRequests(state, 'reference')).toHaveLength(0)
  expect(productRequests(state, 'explanation')).toHaveLength(0)
  expect(state.secondaryRequests).toHaveLength(0)
  const prices = state.requests.filter(item => item.url.pathname.endsWith('/bars/page'))
  expect(prices).toHaveLength(1)
  expect(Object.fromEntries(prices[0].url.searchParams)).toEqual({
    series_kind: 'actual_dominant', symbol: 'rb', frequency: '1d', limit: '500',
  })
  expect(state.requests.filter(item => /\/(daily|weekly)-snapshot$/.test(item.url.pathname))).toHaveLength(0)

  await expect.poll(() => state.deferred.has('trend:1d:chart')).toBe(true)
  await state.deferred.get('trend:1d:chart')()
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()
  await expect(preview).toHaveCount(0)
  await expect(page.locator('.quote-header__price strong')).not.toHaveText('—')
  expect(state.requests.filter(item => item.url.pathname.endsWith('/bars/page'))).toHaveLength(1)
  assertNoUnexpectedRequests(state)
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

test('Newow HTDY and Free share one visual shell while preserving quote semantics', { tag: '@contract-alignment' }, async ({ page }) => {
  const state = await installNewowShellFixture(page)
  await page.goto(newowRoute())
  await expect(page.getByTestId('newow-product-chart-stage')).toBeVisible()

  const quote = page.locator('.quote-header')
  await expect(quote.locator('.quote-header__price strong')).not.toHaveText('—')
  await expect(quote.locator('[title="日涨跌（较前一日收盘）"]')).toBeVisible()
  await expect(quote).toContainText('报价可用')
  const newowVisual = await unifiedShellVisual(page)
  expect(newowVisual.quoteUnified).toBe(true)
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
  assertNoUnexpectedRequests(state)
})

test('Free Range warm-up has a 1280 by 800 baseline and does not create a strategy marker', { tag: '@contract-alignment' }, async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await enableRangeDetector(page)
  const workspace = page.locator('[data-detail-workspace="free"]')
  await expect(workspace).toHaveAttribute('data-range-detector-status', 'insufficient')
  await expect(workspace.locator('.free-workspace__hint')).toContainText('同合约／质量分段预热不足')
  await expect(workspace.locator('.free-workspace__hint')).toContainText('历史图形参考；加载更早数据可能修订箱体。')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-rendered-marker-count', '0')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-chart-viewport-ready', 'true')
  await page.mouse.move(0, 0)
  await expect(page.locator('[data-detail-workspace="free"]')).toHaveScreenshot('market-detail-free-range-1280x800.png', {
    animations: 'disabled', caret: 'hide', maxDiffPixels: 400,
  })
})

test('Free Range warms the first visible Bar with at least 520 preceding same-segment Bars', { tag: '@contract-alignment' }, async ({ page }) => {
  const requests = await mockPagedFreeHistory(page)
  await page.goto(freeJm)

  await enableRangeDetector(page)
  await expect.poll(() => requests.filter(url => url.pathname.endsWith('/bars/page')).length).toBeGreaterThanOrEqual(3)
  const workspace = page.locator('[data-detail-workspace="free"]')
  await expect(workspace).toHaveAttribute('data-range-detector-status', 'ready')
  const firstVisible = await workspace.getAttribute('data-range-detector-visible-from')
  expect(firstVisible).not.toBeNull()
  expect(freeHistory(900).filter(bar => Date.parse(bar.bar_end) < Date.parse(firstVisible)).length).toBeGreaterThanOrEqual(520)
  await expect(workspace.locator('.free-workspace__hint')).toContainText('历史图形参考；加载更早数据可能修订箱体。')
  await expect(workspace.locator('.free-workspace__hint')).not.toContainText('预热不足')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-rendered-marker-count', '0')
})

test('Free discloses insufficient same-segment history and revisable Range graphics', { tag: '@contract-alignment' }, async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)

  await enableRangeDetector(page)
  const workspace = page.locator('[data-detail-workspace="free"]')
  await expect(workspace).toHaveAttribute('data-range-detector-status', 'insufficient')
  await expect(workspace.locator('.free-workspace__hint')).toContainText('同合约／质量分段预热不足')
  await expect(workspace.locator('.free-workspace__hint')).toContainText('历史图形参考；加载更早数据可能修订箱体。')
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

test('Free keeps return-to-latest without restoring retired fullscreen controls', { tag: '@contract-alignment' }, async ({ page }) => {
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

  await expect(page.getByRole('button', { name: '全屏图表', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '退出全屏', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => document.fullscreenElement)).toBeNull()
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

test('Free explicit contract identity survives visible frequency selection and reload', async ({ page }) => {
  const requests = await mockMarketDetail(page, {
    barsPage: ({ url, symbol }) => url.searchParams.get('series_kind') === 'contract'
      ? { bars: [0, 1].map(index => ({ ...detailBar(symbol, index), physical_contract: 'JM2605' })) }
      : undefined,
  })
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=contract&contract=JM2605&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  const periods = page.getByRole('group', { name: '周期', exact: true })
  await periods.getByRole('button', { name: '60分钟', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('frequency')).toBe('60m')
  await page.reload()
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('series_kind')).toBe('contract')
  expect(new URL(page.url()).searchParams.get('contract')).toBe('JM2605')
  await expect.poll(() => requests.some(url => (
    url.pathname.endsWith('/bars/page') && url.searchParams.get('series_kind') === 'contract'
    && url.searchParams.get('contract') === 'JM2605' && url.searchParams.get('frequency') === '60m'
  ))).toBe(true)
})

test('Free uses one visible frequency surface and the shared indicator controls', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto(freeJm)
  const periods = page.getByRole('group', { name: '周期', exact: true })
  await expect(periods).toHaveCount(1)
  await expect(periods.getByRole('button', { name: '15分钟', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: '15分钟', exact: true })).toHaveCount(1)
  await expect(page.getByRole('group', { name: '主图指标', exact: true })).toBeVisible()
  await expect(page.getByRole('tab', { name: '自由看盘', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByLabel('指定合约')).toHaveCount(0)
})

test('Free migrates legacy continuous links and keeps 60-minute and daily navigation', async ({ page }) => {
  const requests = await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&view=free&series_kind=continuous&frequency=15m')
  await expect.poll(() => new URL(page.url()).searchParams.get('series_kind')).toBe('actual_dominant')
  await expect(page.getByText('已切换为真实主力序列', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '主连', exact: true })).toHaveCount(0)
  const frequencyControls = page.getByRole('group', { name: '周期' })
  await frequencyControls.getByRole('button', { name: '60分钟', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('frequency')).toBe('60m')
  await frequencyControls.getByRole('button', { name: '日线', exact: true }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('frequency')).toBe('1d')
  await expect.poll(() => requests.some(url => url.pathname.endsWith('/bars/page') && url.searchParams.get('frequency') === '1d')).toBe(true)
  expect(requests.some(url => url.searchParams.get('series_kind') === 'continuous')).toBe(false)
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
  const preferences = await page.evaluate(() => JSON.parse(localStorage.getItem('guiyi.market.detail.preferences.v2')))
  expect(recursiveUpdates).toEqual([])
  expect(preferences.lastView).toBe('htdy')
  expect(preferences.htdy).toEqual({ seriesKind: 'actual_dominant', frequency: '30m', optionalEmaIndicators: ['ema_60'], showRangeDetector: true })
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

test('Free, HTDY, and SuBing remain isolated workspaces with only SuBing Event facts', { tag: '@contract-alignment' }, async ({ page }) => {
  const requests = await mockDetailDailyQuote(page, {
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  await page.goto(freeJm)
  await expect(page.locator('[data-detail-workspace="free"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-research-marker-count', '0')

  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=15m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.locator('[data-detail-workspace="htdy"]')).toBeVisible()
  await expect(page.getByText('实时信号统一记录于60分钟；当前周期保留历史研究图表。')).toBeVisible()
  await expect(page.locator('.observed-records')).toHaveCount(0)
  expect(requests.alertRequests.filter(({ url }) => url.searchParams.get('rule_code') === 'htdy_original_15m')).toHaveLength(0)
  await page.getByRole('group', { name: '周期', exact: true }).getByRole('button', { name: '60分钟', exact: true }).click()
  const htdyAudit = page.locator('[data-detail-workspace="htdy"] .observed-records')
  await expect(htdyAudit).toBeVisible()
  await htdyAudit.locator('summary').click()
  await expect(htdyAudit).toContainText('当前已加载图表范围未读到实际观察记录；不以历史重算补齐。')
  const htdyRequests = requests.alertRequests.filter(({ url }) => url.searchParams.get('rule_code') === 'htdy_original_15m')
  expect(htdyRequests.length).toBeGreaterThan(0)
  expect(htdyRequests.every(({ url }) => url.searchParams.get('frequency') === '60m')).toBe(true)

  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect(page.locator('[data-detail-workspace="subing"]')).toBeVisible()
  const subingAudit = page.locator('[data-detail-workspace="subing"] .observed-records')
  await subingAudit.locator('summary').click()
  await expect(subingAudit).toContainText('首次事件仅在审计视图展示，不覆盖盘后 Canonical 历史')
  await expect(page.getByText(/S↑ 多头预警/).first()).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await page.getByRole('tab', { name: '历史记录', exact: true }).click()
  await expect(page.locator('[data-detail-workspace="subing"] .detail-section-tabs__history')).toContainText('Bar 2026-09-03 10:45 北京时间')
  expect(requests.alertRequests.every(({ method }) => method === 'GET')).toBe(true)
  expect(requests.newowRequests).toEqual([])
})

test('SuBing projects Rule-specific runtime warm-up and failure states', async ({ page }) => {
  let errorType = 'evaluation_warming_up'
  await mockDetailDailyQuote(page, {
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

test('SuBing current MACD and immutable history remain usable on desktop and mobile', async ({ page }) => {
  await mockDetailDailyQuote(page, {
    barsPage: ({ url, symbol }) => url.searchParams.get('frequency') === '15m'
      ? { bars: Array.from({ length: 40 }, (_, index) => detailBar(symbol, index, 100 + index)) }
      : undefined,
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect.poll(async () => Number(await page.getByTestId('kline-shell').getAttribute('data-macd-point-count'))).toBeGreaterThan(30)
  await expect(page.getByText('MACD · MA21 金死叉', { exact: true })).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await page.getByRole('tab', { name: '历史记录', exact: true }).click()
    const history = width === 390 ? page.getByRole('dialog', { name: '历史记录', exact: true }) : page.locator('.detail-section-tabs__history')
    await expect(history).toContainText('Bar 2026-09-03 10:45 北京时间')
    await expect(history).toContainText('JM2601')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    if (width === 390) {
      await page.keyboard.press('Escape')
      await expect(history).not.toBeVisible()
      await expect(page.getByRole('tab', { name: '历史记录', exact: true })).toBeFocused()
    }
  }
})

test('SuBing has stable desktop and narrow viewport visuals with selectable history', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockDetailDailyQuote(page, {
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
  for (const label of ['5分钟', '15分钟', '30分钟', '60分钟', '日线', '周线']) await expect(page.getByRole('button', { name: label, exact: true })).toBeVisible()
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
  await mockDetailDailyQuote(page, {
    alertEvents: ({ url }) => url.searchParams.get('rule_code') === 'subing_ths_alert_15m_v1' ? [subingEvent('jm')] : [],
    alertRules: [subingRule()],
  })
  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await page.getByRole('tab', { name: '历史记录', exact: true }).click()
  await page.locator('[data-detail-workspace="subing"] .detail-section-tabs__history button').first().click()
  await expect(page.getByRole('dialog', { name: '苏冰预警详情' })).toContainText('S↑ 多头预警 · 未记录 · 2026-09-03 10:45 北京时间 · JM2601')
})

test('SuBing consumes its exact AlertEvent focus once', async ({ page }) => {
  await mockDetailDailyQuote(page, {
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
  await mockDetailDailyQuote(page, {
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

test('HTDY keeps seven historical periods but only 60m resolves immutable Event focus', async ({ page }) => {
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
    const beforeReads = requests.alertRequests.filter(({ url }) => url.pathname.endsWith('/events')).length
    await page.goto(`/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=${frequency}&focus_bar_end=${encodeURIComponent(focus)}`)
    await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
    await expect(page.getByTestId('kline-shell')).toBeVisible()
    expect(new URL(page.url()).searchParams.get('frequency')).toBe(frequency)
    if (frequency === '60m') {
      await page.locator('.observed-records__audit summary').click()
      await expect(page.locator('.observed-records__table')).toContainText('买入观察')
      await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
    } else {
      await expect(page.getByText('实时信号统一记录于60分钟；当前周期保留历史研究图表。')).toBeVisible()
      await expect(page.locator('.observed-records')).toHaveCount(0)
      await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
      await page.waitForTimeout(100)
      expect(requests.alertRequests.filter(({ url }) => url.pathname.endsWith('/events'))).toHaveLength(beforeReads)
    }
    await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  }
  const eventRequests = requests.alertRequests.filter(({ url }) => url.pathname.endsWith('/events'))
  expect(eventRequests.length).toBeGreaterThanOrEqual(1)
  expect(new Set(eventRequests.map(({ url }) => url.searchParams.get('frequency')))).toEqual(new Set(['60m']))
  expect(eventRequests.every(({ url }) => url.searchParams.get('rule_code') === 'htdy_original_15m')).toBe(true)
  expect(requests.alertRequests.every(({ method }) => method !== 'PUT')).toBe(true)

  const before = eventRequests.length
  currentCase = ['60m', '2026-09-03T02:30:00.000Z', '2026-09-03']
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=continuous&frequency=60m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  await expect.poll(() => requests.alertRequests.filter(({ url }) => url.pathname.endsWith('/events')).length).toBe(before + 1)
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=contract&contract=JM2601&frequency=60m')
  await expect(page.locator('[data-detail-ready="true"]')).toBeVisible()
  expect(requests.alertRequests.filter(({ url }) => url.pathname.endsWith('/events'))).toHaveLength(before + 1)
})

test('HTDY keeps last successful immutable Event evidence when a later Event refresh fails', async ({ page }) => {
  await page.clock.install({ time: new Date('2026-09-03T03:00:00.000Z') })
  let eventCalls = 0
  await mockMarketDetail(page, {
    alertEvents: () => (++eventCalls === 1 ? [htdyEvent('jm', '60m')] : 'error'),
  })
  await page.goto('/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=60m')
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await expect(page.locator('.observed-records__audit summary')).toBeVisible()
  expect(eventCalls).toBe(1)
  await page.clock.runFor(30_000)
  await expect.poll(() => eventCalls).toBe(2)
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await page.locator('.observed-records__audit summary').click()
  await expect(page.locator('.observed-records__table')).toContainText('买入观察')
  await expect(page.locator('.observed-records__table')).toContainText('2026-09-03 10:45 北京时间')
  await expect(page.locator('.observed-records__audit')).toContainText('实际预警读取未完成或失败')
})

test('HTDY focus resolves and keyboard product selection stays in the unified identity', async ({ page }) => {
  await mockMarketDetail(page)
  await page.goto('/market/chart?symbol=jm&overlay=htdy&series_kind=actual_dominant&frequency=30m&focus_bar_end=2026-09-03T02%3A30%3A00Z')
  await expect.poll(() => new URL(page.url()).searchParams.has('focus_bar_end')).toBe(false)
  await page.getByRole('combobox', { name: '搜索60品种' }).focus()
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

test('390px shell shows inline market facts and does not invent history', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockMarketDetail(page)
  await page.goto(freeJm)
  await expect(page.getByText('OHLCV · 15分钟收盘', { exact: true })).toBeVisible()
  await expect(page.getByText('报价可用', { exact: true })).toBeVisible()
  for (const name of ['开', '高', '低', '成交量', '持仓量']) await expect(page.getByRole('term').filter({ hasText: new RegExp(`^${name}$`) })).toBeVisible()
  await expect(page.getByRole('button', { name: /更多行情数据/ })).toHaveCount(0)
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
    await page.getByRole('combobox', { name: '搜索60品种' }).focus()
    await page.keyboard.press('ArrowDown')
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
  await page.getByRole('combobox', { name: '搜索60品种' }).focus()
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
  await page.getByRole('combobox', { name: '搜索60品种' }).focus()
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


for (const view of ['htdy', 'subing', 'free']) {
  for (const width of [1188, 390]) {
    test(`shared price and period toolbar ${view} width ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 })
      await installNewowProductFixtures(page)
      await page.route('**/api/v1/market/newow/strategy-detail**', route => {
        const url = new URL(route.request().url())
        if (url.searchParams.get('section') !== 'chart') return route.fallback()
        const raw = buildNewowSplitFixtureEnvelopeForTest(url)
        const value = raw.chart.value, bar = value.bars.at(-1)
        value.price_reference = {
          surface: 'chart_legend', frequency: raw.meta.identity.frequency, as_of: raw.meta.as_of,
          anchor_bar_end: bar.bar_end, physical_contract: bar.physical_contract,
          segment_id: bar.segment_id, calculation_segment_id: bar.calculation_segment_id,
          input_sha256: 'a'.repeat(64), formula_version: 'newow_chart_legend_hhv_llv10_page_v1',
          adapter_version: 'newow_chart_price_projection_v1',
          target: { raw: '3600', display: '3600.00', status: { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null } },
          absorb: { raw: '3400', display: '3400.00', status: { status: 'ready', evidence_status: 'ACTIVE_CODE_VERIFIED', reason_code: null } },
        }
        return route.fulfill({ json: raw })
      })
      await page.goto(`/market/chart?symbol=rb&view=${view}&series_kind=actual_dominant&frequency=60m`)
      const toolbar = page.getByLabel('主图参考价格', { exact: true })
      await expect(toolbar).toHaveCount(1)
      await expect(toolbar).toContainText('目标价: 3600.00')
      await expect(toolbar).toContainText('吸筹价: 3400.00')
      const periods = toolbar.getByRole('group', { name: '周期', exact: true })
      await expect(periods.getByRole('button', { name: '1分钟', exact: true })).toHaveCount(view === 'free' ? 1 : 0)
      const selected = periods.getByRole('button', { name: '60分钟', exact: true })
      await expect(selected).toHaveAttribute('aria-pressed', 'true')
      const colors = await selected.evaluate(el => ({ background: getComputedStyle(el).backgroundColor, height: getComputedStyle(el).height }))
      expect(colors.background).toBe('rgb(255, 255, 255)')
      expect(colors.height).toBe('22px')
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
      await periods.getByRole('button', { name: '5分钟', exact: true }).click()
      await expect.poll(() => new URL(page.url()).searchParams.get('frequency')).toBe('5m')
      await expect(toolbar).toContainText('目标价: 3600.00')
    })
  }
}
