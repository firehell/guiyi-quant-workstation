import { expect, test } from '@playwright/test'


function bars() {
  return Array.from({ length: 32 }, (_, index) => {
    const barEnd = new Date(Date.UTC(2026, 7, 13, 0, index * 15)).toISOString()
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

test('server scope control and persistent bell stay bounded to actual-dominant 15m', async ({ page }) => {
  await page.setViewportSize({ width: 1680, height: 1000 })
  const requests = []
  let enabled = false
  const marketBars = bars()

  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/dominants')) return route.fulfill({ json: { items: [
      { product: 'ag', product_name: '白银', sector: 'precious', exchange: 'SHFE', actual_contract: 'AG2610', dominant_mapping_date: '2026-08-13' },
    ] } })
    if (url.pathname.endsWith('/bars/page')) return route.fulfill({ json: {
      request: { series_kind: url.searchParams.get('series_kind'), symbol: 'ag', contract: null, frequency: '15m', before: null, limit: 1200 },
      bars: marketBars,
      canonical_coverage: null,
      page: { has_more_before: false, next_before: null },
      resolved_contract_segments: [],
    } })
    if (url.pathname.endsWith('/state')) return route.fulfill({ json: {
      symbol: 'ag', series_kind: url.searchParams.get('series_kind'), frequency: '15m', operational: true,
      phase: 'CLOSED', trading_day: '2026-08-13', live_eligible: false, live_available: false,
      live_contract: null, canonical_end: marketBars.at(-1).bar_end, after_market: {},
    } })
    if (url.pathname.endsWith('/research/product')) return route.fulfill({ status: 409, json: { detail: { code: 'QUERY_WINDOW_EMPTY' } } })
    return route.abort()
  })
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: {
    status: 'ok', components: { alert: { status: 'disabled' } },
  } }))
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    requests.push({ method: route.request().method(), url, body: route.request().postDataJSON() })
    if (url.pathname.endsWith('/products/ag')) return route.fulfill({ json: { symbol: 'ag', rules: [{
      rule_code: 'htdy_original_15m', display_name: '火天大有', indicator_code: 'huotian_dayou_original_v0',
      series_kind: 'actual_dominant', frequency: '15m', enabled_for_product: enabled,
    }] } })
    if (url.pathname.includes('/scope/ag')) {
      enabled = route.request().postDataJSON().enabled
      return route.fulfill({ json: {
        rule_code: 'htdy_original_15m', display_name: '火天大有', indicator_code: 'huotian_dayou_original_v0',
        series_kind: 'actual_dominant', frequency: '15m', enabled_for_product: enabled,
      } })
    }
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: { items: [{
      id: 1, rule_code: 'htdy_original_15m', symbol: 'ag', contract: 'AG2610', frequency: '15m',
      bar_end: marketBars.at(-1).bar_end, observation_types: ['buy', 'sell'],
      detected_at: '2026-08-13T07:45:01Z', notified_at: '2026-08-13T07:45:01Z',
    }] } })
    return route.abort()
  })

  await page.goto('/market/chart?symbol=ag&series_kind=actual_dominant&frequency=15m')
  await expect(page.getByText('火天大有 · 15m 实际主力')).toBeVisible()
  await expect(page.getByText('未启用', { exact: true })).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')

  await page.getByRole('switch').click()
  await expect.poll(() => requests.find((request) => request.method === 'PUT')?.body).toEqual({ enabled: true })
  await expect(page.getByRole('switch')).toBeChecked()

  const eventRequests = requests.filter((request) => request.url.pathname.endsWith('/events')).length
  await page.getByRole('button', { name: '主连', exact: true }).click()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '0')
  await page.waitForTimeout(100)
  expect(requests.filter((request) => request.url.pathname.endsWith('/events')).length).toBe(eventRequests)
})
