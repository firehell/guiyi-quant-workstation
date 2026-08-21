import { expect, test } from '@playwright/test'


function bars(frequency) {
  const step = frequency === '5m' ? 5 : 15
  return Array.from({ length: 32 }, (_, index) => {
    const barEnd = new Date(Date.UTC(2026, 7, 13, 0, index * step)).toISOString()
    return {
      bar_end: barEnd,
      trading_day: '2026-08-13',
      open: 100,
      high: 101,
      low: 99,
      close: 100,
      volume: 10,
      turnover: null,
      open_interest: null,
    }
  })
}

function event({ id, ruleCode, frequency, barEnd, resultCode }) {
  return {
    id,
    rule_code: ruleCode,
    symbol: 'ag',
    contract: 'AG2610',
    trading_day: '2026-08-13',
    frequency,
    bar_end: barEnd,
    result_codes: [resultCode],
    lower_tf_confirmation: false,
    detected_at: '2026-08-13T07:45:01Z',
    notification_attempted_at: '2026-08-13T07:45:01Z',
  }
}

test('persistent Alert V2 markers stay exact-frequency and actual-dominant only', async ({ page }) => {
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.addInitScript(() => {
    window.__GUIYI_E2E_CANVAS_TEXT__ = []
    const original = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function (value, ...args) {
      window.__GUIYI_E2E_CANVAS_TEXT__.push(String(value))
      return original.call(this, value, ...args)
    }
  })
  const requests = []
  let activeFrequency = '30m'
  const barsByFrequency = { '5m': bars('5m'), '15m': bars('15m'), '30m': bars('15m') }

  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/dominants')) return route.fulfill({ json: { items: [
      { product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2610', dominant_mapping_date: '2026-08-13' },
    ] } })
    if (url.pathname.endsWith('/bars/page')) {
      activeFrequency = url.searchParams.get('frequency')
      const marketBars = barsByFrequency[activeFrequency]
      return route.fulfill({ json: {
        request: { series_kind: url.searchParams.get('series_kind'), symbol: 'ag', contract: null, frequency: activeFrequency, before: null, limit: 1200 },
        bars: marketBars,
        canonical_coverage: null,
        page: { has_more_before: false, next_before: null },
        resolved_contract_segments: [],
      } })
    }
    if (url.pathname.endsWith('/state')) return route.fulfill({ json: {
      symbol: 'ag', series_kind: url.searchParams.get('series_kind'), frequency: activeFrequency, operational: true,
      phase: 'CLOSED', trading_day: '2026-08-13', live_eligible: false, live_available: false,
      live_contract: null, canonical_end: barsByFrequency[activeFrequency]?.at(-1)?.bar_end ?? null, after_market: {},
    } })
    if (url.pathname.endsWith('/research/product')) return route.fulfill({ status: 409, json: { detail: { code: 'QUERY_WINDOW_EMPTY' } } })
    if (url.pathname.endsWith('/research/main-force-mirror')) return route.fulfill({ status: 400, json: { detail: { code: 'MFM_V2_UNSUPPORTED_FREQUENCY' } } })
    return route.abort()
  })
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: {
    status: 'ok', components: { alert: { status: 'disabled' } },
  } }))
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/products/ag')) return route.fulfill({ json: { symbol: 'ag', rules: [
      { rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation', input_frequencies: ['15m'], enabled_for_product: false },
      { rule_code: 'subing_entry_signal_v1', display_name: '苏冰入场信号', kind: 'formal_signal', input_frequencies: ['5m', '15m'], enabled_for_product: false },
    ] } })
    if (url.pathname.endsWith('/current-events')) return route.fulfill({ json: { status: 'ready', trading_day: '2026-08-13', items: [] } })
    if (url.pathname.endsWith('/events')) {
      const ruleCode = url.searchParams.get('rule_code')
      requests.push({ ruleCode, activeFrequency })
      const items = ruleCode === 'htdy_original_15m'
        ? [event({ id: 3, ruleCode, frequency: '15m', barEnd: barsByFrequency['15m'].at(-1).bar_end, resultCode: 'sell' })]
        : [
            event({ id: 1, ruleCode, frequency: '5m', barEnd: barsByFrequency['5m'].at(-1).bar_end, resultCode: 'buy' }),
            event({ id: 2, ruleCode, frequency: '15m', barEnd: barsByFrequency['15m'].at(-1).bar_end, resultCode: 'buy' }),
          ]
      return route.fulfill({ json: { items } })
    }
    return route.abort()
  })

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=30m')
  const sidebar = page.locator('.product-workspace__sidebar')
  await expect(sidebar).toBeVisible()
  await expect(sidebar.getByTestId('product-formal-signal')).toBeVisible()
  await expect(sidebar.getByTestId('product-alert-rules')).toBeVisible()
  await expect(sidebar.getByTestId('product-today-alert-events')).toBeVisible()
  expect(await sidebar.locator('[data-testid="product-formal-signal"], [data-testid="product-alert-rules"], [data-testid="product-today-alert-events"]').evaluateAll((nodes) => (
    nodes.every((node, index) => index === 0 || Boolean(nodes[index - 1].compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING))
  ))).toBe(true)
  await page.getByRole('group', { name: 'Overlay' }).getByRole('button', { name: '无', exact: true }).click()
  await page.getByRole('button', { name: '真实主力', exact: true }).click()
  await page.getByRole('button', { name: '5m', exact: true }).click()
  await expect.poll(() => requests.filter((request) => request.activeFrequency === '5m').map((request) => request.ruleCode))
    .toEqual(['subing_entry_signal_v1'])
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')

  await page.getByRole('button', { name: '15m', exact: true }).click()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '2')
  await expect.poll(() => page.evaluate(() => window.__GUIYI_E2E_CANVAS_TEXT__)).toEqual(
    expect.arrayContaining(['卖出观察', '买入信号']),
  )
  await expect.poll(() => requests.filter((request) => request.activeFrequency === '15m').map((request) => request.ruleCode).sort())
    .toEqual(['htdy_original_15m', 'subing_entry_signal_v1'])

  const tabs = page.getByTestId('secondary-panel-tabs')
  await expect(tabs.getByRole('tab')).toHaveText(['MACD', '主力照妖镜 V2'])
  await page.evaluate(() => { window.__GUIYI_E2E_CANVAS_TEXT__ = [] })
  await tabs.getByRole('tab', { name: 'MACD' }).click()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '2')
  await expect.poll(() => page.evaluate(() => window.__GUIYI_E2E_CANVAS_TEXT__)).toEqual(
    expect.arrayContaining(['卖出观察', '买入信号']),
  )

  const eventRequestCount = requests.length
  await page.getByRole('button', { name: '主连', exact: true }).click()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await page.waitForTimeout(100)
  expect(requests).toHaveLength(eventRequestCount)
})
