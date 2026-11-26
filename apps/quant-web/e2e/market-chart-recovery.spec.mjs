import { expect, test } from '@playwright/test'
import { detailBar, installDetailFakeWebSocket, mockMarketDetail, navigateClient } from './market-detail.helpers.mjs'

const chartUrl = (contract = '', frequency = '15m') => '/market/chart?symbol=jm&view=free&frequency=' + frequency
  + (contract ? '&series_kind=contract&contract=' + contract : '&series_kind=actual_dominant')
const candles = page => page.locator('[data-kline-end]')

async function waitForSocket(page, count) {
  await expect.poll(() => page.evaluate(() => window.__marketDetailSockets
    .filter(socket => new URL(socket.url).pathname.endsWith('/market/ws')).length)).toBe(count)
}

async function send(page, index, frames) {
  await page.evaluate(({ index, frames }) => {
    const socket = window.__marketDetailSockets
      .filter(candidate => new URL(candidate.url).pathname.endsWith('/market/ws'))[index]
    for (const frame of frames) socket.onmessage?.({ data: JSON.stringify(frame) })
  }, { index, frames })
}

function snapshot(contract, bars) {
  return { type: 'snapshot', source: 'realtime', trading_day: '2026-09-03', contract, bars }
}

test('price, preview, volume and MACD diagnostics follow their own plotted inputs', async ({ page }) => {
  await installDetailFakeWebSocket(page)
  const hash = 'a'.repeat(64)
  const historical = { ...detailBar('jm', 0), source_bar_sha256: hash }
  const live = detailBar('jm', 1)
  await mockMarketDetail(page, { live: true, barsPage: () => ({ bars: [historical] }) })
  await page.goto(chartUrl())
  await waitForSocket(page, 1)
  await send(page, 0, [snapshot('JM2601', [live])])
  await expect(candles(page)).toHaveAttribute('data-kline-end', live.bar_end)
  const diagnostics = page.locator('.market-kline-stage .chart-layer-diagnostics')
  await diagnostics.getByText('图层诊断', { exact: true }).click()
  const rows = diagnostics.locator('.chart-layer-diagnostics__row')
  const completed = rows.filter({ has: page.getByText('price · 就绪', { exact: true }) })
  await completed.locator('summary').click()
  await expect(completed).toContainText(hash)
  await expect(completed).toContainText(historical.bar_end)
  await expect(completed).not.toContainText(live.bar_end)

  const preview = rows.filter({ has: page.getByText('price_preview · 就绪', { exact: true }) })
  await preview.locator('summary').click()
  await expect(preview).toContainText(live.bar_end)
  await expect(preview).not.toContainText(hash)

  const volume = rows.filter({ has: page.getByText('subing_volume · 就绪', { exact: true }) }).first()
  await volume.locator('summary').click()
  await expect(volume).toContainText('histogram')
  await expect(volume).toContainText(live.bar_end)

  const macd = rows.filter({ has: page.getByText('ths_macd · 就绪', { exact: true }) })
  await macd.locator('summary').click()
  await expect(macd).toContainText('ths_macd_ma21_display_v1')
  await expect(macd).toContainText(live.bar_end)

  const crosses = rows.filter({ has: page.getByText('ths_macd · 预热中', { exact: true }) })
  await crosses.locator('summary').click()
  // The live overlay has no canonical calculation-segment identity.
  await expect(crosses).toContainText('1/21')
  await expect(rows.getByText('subing_volume · 缺少输入', { exact: true })).toHaveCount(1)
})

test('native price, volume and THS write failures clear diagnostics and recover independently', async ({ page }) => {
  await installDetailFakeWebSocket(page)
  const historical = { ...detailBar('jm', 0), source_bar_sha256: 'b'.repeat(64) }
  await mockMarketDetail(page, { live: true, barsPage: () => ({ bars: [historical] }) })
  await page.goto(chartUrl())
  await waitForSocket(page, 1)
  await expect(candles(page)).toHaveAttribute('data-kline-end', historical.bar_end)
  const chartModule = await (await page.waitForFunction(() => performance.getEntriesByType('resource')
    .find(entry => new URL(entry.name).pathname.endsWith('/lightweight-charts.js'))?.name)).jsonValue()
  await page.evaluate(async moduleUrl => {
    const { createChart, CandlestickSeries } = await import(moduleUrl)
    const probe = createChart(document.createElement('div'))
    const native = Object.getPrototypeOf(probe.addSeries(CandlestickSeries))
    probe.remove()
    const state = { fail: 'Candlestick', macd: null }
    window.__nativeWriteFailure = state
    for (const method of ['setData', 'update']) {
      const original = native[method]
      native[method] = function (...args) {
        const kind = this.seriesType()
        const isDif = kind === 'Line' && this.options().color === '#00bfcf'
        const isVolume = kind === 'Histogram' && this.options().priceScaleId === 'volume'
        if ((kind === 'Candlestick' && state.fail === kind) || (isDif && state.fail === 'macd') || (isVolume && state.fail === 'volume')) {
          throw Error('Injected native series write failure')
        }
        if (isDif) state.macd = this
        return original.apply(this, args)
      }
    }
  }, chartModule)

  const diagnostics = page.locator('.market-kline-stage .chart-layer-diagnostics')
  await diagnostics.getByText('图层诊断', { exact: true }).click()
  const rows = diagnostics.locator('.chart-layer-diagnostics__row')
  const refresh = diagnostics.getByRole('button', { name: '刷新诊断', exact: true })
  const first = detailBar('jm', 1)
  await send(page, 0, [snapshot('JM2601', [first])])
  const failed = rows.filter({ has: page.getByText('price · 渲染错误', { exact: true }) })
  await expect.poll(async () => { await refresh.click(); return failed.count() }).toBe(1)
  await failed.locator('summary').click()
  await expect(failed).toContainText('CHART_RENDERER_UPDATE_FAILED')
  await expect(failed).not.toContainText(historical.source_bar_sha256)
  await expect(rows.getByText('price_preview · 就绪', { exact: true })).toHaveCount(0)
  const macd = rows.filter({ has: page.getByText('ths_macd · 就绪', { exact: true }) })
  await macd.locator('summary').click()
  await expect(macd).toContainText(first.bar_end)
  const baseHeight = await page.evaluate(() => window.__nativeWriteFailure.macd.getPane().getHeight())

  await page.evaluate(() => { window.__nativeWriteFailure.fail = 'macd' })
  const second = detailBar('jm', 2)
  await send(page, 0, [snapshot('JM2601', [first, second])])
  await expect(candles(page)).toHaveAttribute('data-kline-end', second.bar_end)
  await expect.poll(async () => {
    await refresh.click()
    return rows.getByText('ths_macd · 渲染错误', { exact: true }).count()
  }).toBe(1)
  await expect(rows.getByText('ths_macd · 预热中', { exact: true })).toHaveCount(0)

  await page.evaluate(() => { window.__nativeWriteFailure.fail = 'volume' })
  const third = detailBar('jm', 3)
  await send(page, 0, [snapshot('JM2601', [first, second, third])])
  await expect.poll(async () => { await refresh.click(); return macd.count() }).toBe(1)
  await expect(rows.getByText('ths_macd · 预热中', { exact: true })).toHaveCount(1)
  expect(baseHeight).toBeGreaterThan(80)
  await expect.poll(() => page.evaluate(() => window.__nativeWriteFailure.macd.getPane().getHeight())).toBeGreaterThan(80)
  await expect(candles(page)).toHaveAttribute('data-kline-end', third.bar_end)
  await expect(rows.getByText('subing_volume · 渲染错误', { exact: true })).toHaveCount(1)

  await page.evaluate(() => { window.__nativeWriteFailure.fail = null })
  const fourth = detailBar('jm', 4)
  await send(page, 0, [snapshot('JM2601', [first, second, third, fourth])])
  await expect.poll(async () => {
    await refresh.click()
    return rows.getByText('subing_volume · 就绪', { exact: true }).count()
  }).toBe(1)
})

test('keeps historical candles and catches up automatically after the first state request fails', async ({ page }) => {
  await installDetailFakeWebSocket(page)
  const historical = detailBar('jm', 0)
  await mockMarketDetail(page, {
    live: true, barsPage: () => ({ bars: [historical] }),
  })
  let stateReads = 0
  let failFirstRequest
  const firstRequestPending = new Promise(resolve => { failFirstRequest = resolve })
  await page.route('**/api/v1/market/state?*', async route => {
    if (++stateReads === 1) {
      await firstRequestPending
      return route.fulfill({ status: 503, json: { detail: 'state unavailable' } })
    }
    return route.fulfill({ json: {
      symbol: 'jm', series_kind: 'actual_dominant', frequency: '15m', operational: true,
      phase: 'TRADING', trading_day: '2026-09-03', live_eligible: true, live_available: true,
      live_contract: 'JM2601', canonical_end: historical.bar_end, after_market: {},
    } })
  })
  await page.goto(chartUrl())
  await expect(candles(page)).toHaveAttribute('data-kline-count', '1')
  await expect(candles(page)).toHaveAttribute('data-kline-end', historical.bar_end)
  failFirstRequest()
  await waitForSocket(page, 1)
  const recovered = detailBar('jm', 1, 111)
  const next = detailBar('jm', 2, 112)
  // Snapshot and next event can arrive before Vue flushes a chart update.
  await send(page, 0, [snapshot('JM2601', [recovered]), { type: 'bar', bar: next }])
  await expect(candles(page)).toHaveAttribute('data-kline-count', '3')
  await expect(candles(page)).toHaveAttribute('data-kline-end', next.bar_end)
  await expect(candles(page)).toHaveAttribute('data-kline-close', '112')
  expect(stateReads).toBe(2)
})

test('reconnects and reconciles a missing candle older than the last painted candle', async ({ page }) => {
  await installDetailFakeWebSocket(page)
  await mockMarketDetail(page, { live: true, barsPage: () => ({ bars: [detailBar('jm', 0)] }) })
  await page.goto(chartUrl())
  await waitForSocket(page, 1)
  const gap = detailBar('jm', 1, 111)
  const previousTail = detailBar('jm', 2, 112)
  await send(page, 0, [snapshot('JM2601', [previousTail])])
  await expect(candles(page)).toHaveAttribute('data-kline-count', '2')
  await page.evaluate(() => window.__marketDetailSockets.find(socket =>
    new URL(socket.url).pathname.endsWith('/market/ws')).close())
  await expect(candles(page)).toHaveAttribute('data-kline-end', previousTail.bar_end)
  await waitForSocket(page, 2)
  await send(page, 1, [snapshot('JM2601', [gap, previousTail, previousTail])])
  await expect(candles(page)).toHaveAttribute('data-kline-count', '3')
  await expect(candles(page)).toHaveAttribute('data-kline-end', previousTail.bar_end)
})

test('discards late old-contract frames during navigation and keeps updating the selected contract', async ({ page }) => {
  await installDetailFakeWebSocket(page)
  await mockMarketDetail(page, { live: true, barsPage: ({ url }) => ({
    bars: [0, 1].map(index => ({ ...detailBar('jm', index), physical_contract: url.searchParams.get('contract') })),
  }) })
  await page.route('**/api/v1/market/state?*', route => route.fulfill({ json: {
    symbol: 'jm', series_kind: 'contract', frequency: '15m', operational: true,
    phase: 'TRADING', trading_day: '2026-09-03', live_eligible: true, live_available: true,
    live_contract: new URL(route.request().url()).searchParams.get('contract'),
    canonical_end: detailBar('jm', 1).bar_end, after_market: {},
  } }))
  await page.goto(chartUrl('JM2605'))
  await waitForSocket(page, 1)
  await expect(candles(page)).toHaveAttribute('data-kline-contract', 'JM2605')
  await navigateClient(page, chartUrl('JM2601'))
  await waitForSocket(page, 2)
  await send(page, 0, [snapshot('JM2605', [detailBar('jm', 8, 999)])])
  const next = detailBar('jm', 2, 120)
  await send(page, 1, [snapshot('JM2601', [next])])
  await expect(candles(page)).toHaveAttribute('data-kline-contract', 'JM2601')
  await expect(candles(page)).toHaveAttribute('data-kline-count', '3')
  await expect(candles(page)).toHaveAttribute('data-kline-end', next.bar_end)
  await expect(candles(page)).toHaveAttribute('data-kline-close', '120')
})

test('indicator request failure leaves the base candles updating', async ({ page }) => {
  await installDetailFakeWebSocket(page)
  await mockMarketDetail(page, { live: true })
  await page.route('**/api/v1/market/indicators/dynamic-range?*', route =>
    route.fulfill({ status: 503, json: { detail: 'indicator unavailable' } }))
  await page.goto(chartUrl('', '30m'))
  await waitForSocket(page, 1)
  await page.getByRole('button', { name: '震荡／趋势' }).click()
  await expect(page.getByTestId('dynamic-range-status')).toContainText('指标计算不可用')
  const next = detailBar('jm', 3, 130)
  await send(page, 0, [snapshot('JM2601', [next])])
  await expect(candles(page)).toHaveAttribute('data-kline-count', '3')
  await expect(candles(page)).toHaveAttribute('data-kline-close', '130')
  await expect(page.getByTestId('dynamic-range-status')).toContainText('指标计算不可用')
})
