import { expect, test } from '@playwright/test'

function marketBars() {
  return Array.from({ length: 40 }, (_, index) => {
    const barEnd = new Date(Date.UTC(2026, 7, 20, index, 0)).toISOString()
    return {
      bar_end: barEnd,
      trading_day: index < 16 ? '2026-08-20' : '2026-08-21',
      open: 100 + index,
      high: 102 + index,
      low: 99 + index,
      close: 101 + index,
      volume: 1_000 + index,
      turnover: null,
      open_interest: 2_000 + index,
    }
  })
}

function mirrorPoint(barEnd, overrides = {}) {
  return {
    bar_end: barEnd,
    trading_day: '2026-08-21',
    physical_contract: 'JM2609',
    pressure_ready: true,
    pressure_state: 'long_build',
    instant_pressure: 36.2,
    accumulated_ready: true,
    accumulated_pressure: 18.7,
    caution_ready: true,
    caution: 'long_chase_caution',
    caution_conflict: false,
    long_caution_score: 70,
    short_caution_score: 5,
    caution_reason_codes: ['LONG_UPPER_EXTREME'],
    price_impulse: 0.2,
    clv: 0.3,
    volume_ratio: 1.4,
    delta_oi: 120,
    oi_impulse: 0.5,
    range_position: 0.8,
    member_status: 'ready',
    member_trade_date: '2026-08-20',
    member_direction: 'long',
    member_change_bias: 0.2,
    member_strength: 1.8,
    position_skew: 0.4,
    top5_volume_share: 0.5,
    relation_to_accumulated: 'strong_aligned',
    relation_to_caution: 'strong_aligned',
    unavailable_reason: null,
    ...overrides,
  }
}

test('Market renders only MACD and parent-owned historical Main Force Mirror V2', async ({ page }) => {
  await page.setViewportSize({ width: 1680, height: 1000 })
  await page.addInitScript(() => {
    window.__GUIYI_E2E_CANVAS_TEXT__ = []
    const original = CanvasRenderingContext2D.prototype.fillText
    CanvasRenderingContext2D.prototype.fillText = function (value, ...args) {
      window.__GUIYI_E2E_CANVAS_TEXT__.push(String(value))
      return original.call(this, value, ...args)
    }
  })

  const bars = marketBars()
  const mirrorRequests = []
  await page.route('**/api/v1/market/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/dominants')) return route.fulfill({ json: { items: [
      { product: 'jm', product_name: '焦煤', sector: 'black', exchange: 'DCE', actual_contract: 'JM2609', dominant_mapping_date: '2026-08-21' },
    ] } })
    if (url.pathname.endsWith('/bars/page')) return route.fulfill({ json: {
      request: {
        series_kind: url.searchParams.get('series_kind'), symbol: 'jm', contract: null,
        frequency: url.searchParams.get('frequency'), before: null, limit: 1200,
      },
      bars,
      canonical_coverage: { start: bars[0].bar_end, end: bars.at(-1).bar_end },
      page: { has_more_before: false, next_before: null },
      resolved_contract_segments: [{ contract: 'JM2609', start_trading_day: '2026-08-20', end_trading_day: '2026-08-21' }],
    } })
    if (url.pathname.endsWith('/state')) return route.fulfill({ json: {
      symbol: 'jm', series_kind: url.searchParams.get('series_kind'), frequency: url.searchParams.get('frequency'),
      operational: true, phase: 'TRADING', trading_day: '2026-08-21', live_eligible: true,
      live_available: true, live_contract: 'JM2609', canonical_end: bars.at(-1).bar_end, after_market: {},
    } })
    if (url.pathname.endsWith('/research/main-force-mirror')) {
      mirrorRequests.push(Object.fromEntries(url.searchParams))
      if (url.searchParams.get('series_kind') === 'continuous') {
        return route.fulfill({ status: 400, json: { detail: { code: 'MFM_V2_UNSUPPORTED_SERIES_KIND' } } })
      }
      const unavailable = mirrorPoint(bars[34].bar_end, {
        caution: 'short_chase_caution', long_caution_score: 5, short_caution_score: 74,
        member_status: 'unavailable', member_trade_date: null, member_direction: null,
        member_change_bias: null, member_strength: null, position_skew: null, top5_volume_share: null,
        relation_to_accumulated: 'unavailable', relation_to_caution: 'unavailable',
        unavailable_reason: 'MFM_MEMBER_SNAPSHOT_MISSING',
      })
      const ready = mirrorPoint(bars[35].bar_end)
      return route.fulfill({ json: {
        request: {
          series_kind: 'actual_dominant', symbol: 'jm', contract: null, frequency: '60m', before: null, limit: 1200,
        },
        indicator: {
          indicator_code: 'main_force_mirror_v2', indicator_version: 'futures-member-research-v2',
          formal_policy_id: 'main_force_mirror_observation_v2', parameters_hash: 'frozen-parameters',
          interpretation: 'directional_position_pressure_proxy_not_measured_fund_flow',
          observation_only: true, historical_only: true, auto_order: false,
        },
        member_dataset: {
          status: 'ready', dataset_id: 'member-rank-v1', schema_version: 1, admitted_product: true,
          coverage: { start: '2026-08-20', end: '2026-08-20' },
        },
        points: [unavailable, ready],
        page: { has_more_before: false, next_before: null },
        resolved_contract_segments: [{ contract: 'JM2609', start_trading_day: '2026-08-20', end_trading_day: '2026-08-21' }],
      } })
    }
    if (url.pathname.endsWith('/research/product')) return route.fulfill({ status: 409, json: { detail: { code: 'QUERY_WINDOW_EMPTY' } } })
    return route.abort()
  })
  await page.route('**/api/runtime/health', (route) => route.fulfill({ json: {
    status: 'ok', components: { alert: { status: 'disabled' } },
  } }))
  await page.route('**/api/alerts/**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/products/jm')) return route.fulfill({ json: { symbol: 'jm', rules: [] } })
    if (url.pathname.endsWith('/current-events')) return route.fulfill({ json: { status: 'ready', trading_day: '2026-08-21', items: [] } })
    if (url.pathname.endsWith('/events')) return route.fulfill({ json: { items: [] } })
    return route.abort()
  })

  await page.goto('/market/chart?symbol=jm&series_kind=actual_dominant&frequency=60m')
  const shell = page.getByTestId('kline-shell')
  const tabs = page.getByTestId('secondary-panel-tabs')
  await expect(tabs.getByRole('tab')).toHaveText(['MACD', '主力照妖镜 V2'])
  await expect(shell).toHaveAttribute('data-secondary-panel', 'macd')
  await expect.poll(() => mirrorRequests.length).toBe(0)

  await tabs.getByRole('tab', { name: '主力照妖镜 V2' }).click()
  await expect.poll(() => mirrorRequests.length).toBe(1)
  await expect(shell).toHaveAttribute('data-secondary-panel', 'main_force_mirror_v2')
  await expect(page.getByText('席位强同向', { exact: true })).toBeVisible()
  await expect(page.getByText('席位日期 2026-08-20', { exact: true })).toBeVisible()
  await expect(page.getByText('席位数据 ready', { exact: true })).toBeVisible()
  await expect(page.getByText(/历史确认截至 2026-08-21T11:00:00\.000Z/)).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__GUIYI_E2E_CANVAS_TEXT__)).toEqual(
    expect.arrayContaining(['追多小心 70｜席位强同向', '追空小心 74｜席位不可用']),
  )

  await tabs.getByRole('tab', { name: 'MACD' }).click()
  await expect.poll(() => mirrorRequests.length).toBe(1)
  await expect(shell).toHaveAttribute('data-secondary-panel', 'macd')
  await tabs.getByRole('tab', { name: '主力照妖镜 V2' }).click()
  await expect.poll(() => mirrorRequests.length).toBe(2)

  await page.getByRole('button', { name: '主连', exact: true }).click()
  await expect.poll(() => mirrorRequests.length).toBe(3)
  await expect(shell).toHaveAttribute('data-secondary-panel', 'main_force_mirror_v2')
  await expect(page.getByText('MFM_V2_UNSUPPORTED_SERIES_KIND', { exact: true })).toBeVisible()
})
