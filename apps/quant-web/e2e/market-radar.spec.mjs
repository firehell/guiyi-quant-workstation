import { expect, test } from '@playwright/test'

function radar(freshnessState = 'current') {
  const degraded = freshnessState === 'degraded'
  const pending = freshnessState === 'pending_after_market'
  const items = [
    {
      symbol: 'ag', product_name: '白银', sector: 'precious', price_change_1d: '0.032',
      price_change_5d: '0.061', volume_ratio20: '1.72', oi_change_1d: '0.081',
      atr14_percentile252: '0.83', position20: '0.91', turnover: '9000',
      reason_codes: ['ema21_up', 'price_move_up', 'volume_expansion', 'oi_increase'],
    },
    {
      symbol: 'jm', product_name: '焦煤', sector: 'black', price_change_1d: '-0.021',
      price_change_5d: '-0.034', volume_ratio20: '1.12', oi_change_1d: '-0.06',
      atr14_percentile252: '0.56', position20: '0.24', turnover: '6000',
      reason_codes: ['price_move_down', 'oi_decrease'],
    },
  ]
  return {
    status: degraded ? 'degraded' : 'ready',
    expected_as_of: '2026-08-11',
    target_as_of: '2026-08-11',
    data_as_of: pending ? '2026-08-10' : '2026-08-11',
    freshness_state: freshnessState,
    freshness_message: degraded ? '数据异常' : pending ? '盘后更新待完成' : '当前完整',
    active_count: 60,
    participant_count: degraded ? 59 : 60,
    stale: degraded ? ['jm'] : [], unavailable: [],
    summary: {
      up_count: 1, down_count: 1, volume_expansion_count: 1,
      oi_increase_count: 1, high_volatility_count: 1,
    },
    items,
    attention: items,
    sector_summary: [
      { sector: 'precious', total_count: 1, participant_count: 1, up_count: 1, down_count: 0, median_price_change_1d: '0.032', attention_count: 1 },
      { sector: 'black', total_count: 1, participant_count: degraded ? 0 : 1, up_count: 0, down_count: degraded ? 0 : 1, median_price_change_1d: degraded ? null : '-0.021', attention_count: degraded ? 0 : 1 },
    ],
  }
}

function trendFocusItem() {
  return {
    symbol: 'ag', product_name: '白银', sector: 'precious', physical_contract: 'AG2601',
    direction: 'long', stage: 'ready', hot_conditions: ['price_move_up', 'volume_expansion'],
    hot_count: 2, price_change_1d: '0.032', volume_ratio20: '1.72',
    atr14_percentile252: '0.83', daily_volume_support: true,
    hourly_state: 'continuation', hourly_volume_support: true,
    range_upper: '101.25', range_lower: '96.5', confirmation_count: 3,
    retest_held: true, rebreak_reference: '103.5', ready_invalidation: '99.25',
    volume_confirmed: true, five_minute_confirmed: false, entry_confirmed_at: null,
    latest_swing_high: '103.5', latest_swing_low: '99.25', next_level: '104.75',
    invalidation_level: '101.25', last_transition_at: '2026-08-11T09:30:00Z',
  }
}

function trendFocus(overrides = {}) {
  return {
    status: 'ready', observed_at: '2026-08-11T10:00:00Z',
    long_opportunities: [trendFocusItem()], short_opportunities: [],
    running_trends: [], weakening_trends: [], unavailable: [],
    ...overrides,
  }
}

async function mockRadar(page, payload, focusPayload = trendFocus()) {
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: payload }))
  await page.route('**/api/v1/market/research/trend-focus', (route) => route.fulfill({ json: focusPayload }))
}

test('renders Focus before collapsed full-market research and routes it to Product Workspace', async ({ page }) => {
  await mockRadar(page, radar())
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto('/market')

  const focus = page.getByTestId('market-focus')
  await expect(focus).toBeVisible()
  await expect(page.getByTestId('market-focus-card')).toHaveCount(1)
  await expect(focus).toContainText('多头 1')
  await expect(focus).toContainText('观察时点')
  await expect(focus.getByText('价格 Hot', { exact: true })).toBeVisible()
  await expect(page.getByText('市场概览', { exact: true })).toBeHidden()
  await expect(page.getByText('价格变化 × OI 变化', { exact: true })).toBeHidden()
  await expect(page.getByText('综合分数', { exact: true })).toHaveCount(0)

  await page.getByText('展开全市场研究', { exact: true }).click()
  await expect(page.getByText('市场概览', { exact: true })).toBeVisible()
  await expect(page.getByText('价格变化 × OI 变化', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '自选', exact: true })).toBeVisible()

  await focus.getByRole('button', { name: '检查 AG', exact: true }).click()
  await expect(page).toHaveURL(/\/market\/chart\?symbol=ag&series_kind=actual_dominant&frequency=15m/)
})

test('keeps the backend Focus snapshot independent from a pending Radar refresh', async ({ page }) => {
  await mockRadar(page, radar('pending_after_market'))
  await page.goto('/market')

  const focus = page.getByTestId('market-focus')
  await expect(focus).toContainText('AG 白银')
  await expect(focus).toContainText('观察时点')
  await expect(focus).not.toContainText('盘后更新待完成')
  await expect(page.getByText(/Radar 数据不完整/)).toHaveCount(0)
})

test('keeps backend Focus available while Radar reports degraded freshness', async ({ page }) => {
  await mockRadar(page, radar('degraded'))
  await page.goto('/market')

  await expect(page.getByTestId('market-focus')).toContainText('AG 白银')
  await expect(page.getByText('Radar 数据不完整：stale jm', { exact: true })).toBeVisible()
  await expect(page.getByTestId('market-focus-card')).toHaveCount(1)
})

test('keeps the backend Focus observation summary readable at a narrow viewport', async ({ page }) => {
  await mockRadar(page, radar('pending_after_market'))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/market')

  const focus = page.getByTestId('market-focus')
  await expect(focus).toContainText('观察时点')
  await expect(focus).toContainText('AG 白银')
})
