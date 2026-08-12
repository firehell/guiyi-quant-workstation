import { expect, test } from '@playwright/test'

function radar(status = 'ready') {
  const items = [
    {
      symbol: 'ag', product_name: '白银', sector: 'precious', price_change_1d: '0.032',
      price_change_5d: '0.061', volume_ratio20: '1.72', oi_change_1d: '0.081',
      atr14_percentile252: '0.83', position20: '0.91', turnover: '9000',
      reason_codes: ['price_move_up', 'volume_expansion', 'oi_increase'],
    },
    {
      symbol: 'jm', product_name: '焦煤', sector: 'black', price_change_1d: '-0.021',
      price_change_5d: '-0.034', volume_ratio20: '1.12', oi_change_1d: '-0.06',
      atr14_percentile252: '0.56', position20: '0.24', turnover: '6000',
      reason_codes: ['price_move_down', 'oi_decrease'],
    },
  ]
  return {
    status,
    expected_as_of: '2026-08-11', active_count: 60,
    participant_count: status === 'ready' ? 60 : 59,
    stale: status === 'ready' ? [] : ['jm'], unavailable: [],
    summary: {
      up_count: 1, down_count: 1, volume_expansion_count: 1,
      oi_increase_count: 1, high_volatility_count: 1,
    },
    items,
    attention: items,
    sector_summary: [
      { sector: 'precious', total_count: 1, participant_count: 1, up_count: 1, down_count: 0, median_price_change_1d: '0.032', attention_count: 1 },
      { sector: 'black', total_count: 1, participant_count: status === 'ready' ? 1 : 0, up_count: 0, down_count: status === 'ready' ? 1 : 0, median_price_change_1d: status === 'ready' ? '-0.021' : null, attention_count: status === 'ready' ? 1 : 0 },
    ],
  }
}

async function mockRadar(page, payload) {
  await page.route('**/api/v1/market/research/radar', (route) => route.fulfill({ json: payload }))
}

test('renders a freshness-aware market discovery view and routes scatter items to Product Workspace', async ({ page }) => {
  await mockRadar(page, radar())
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto('/market')

  await expect(page.getByText('市场概览', { exact: true })).toBeVisible()
  await expect(page.getByText('2026-08-11 · 60/60')).toBeVisible()
  await expect(page.getByText('价格变化 × OI 变化', { exact: true })).toBeVisible()
  await expect(page.getByText('值得关注', { exact: true })).toBeVisible()
  await expect(page.getByText('上涨 + 增仓', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'AG 白银', exact: true }).first()).toBeVisible()
  await expect(page.getByText('价格上涨', { exact: true })).toBeVisible()
  await expect(page.getByText('系统透明规则', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '自选', exact: true })).toBeVisible()
  await expect(page.getByText('综合分数', { exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: 'AG 白银', exact: true }).first().click()
  await expect(page).toHaveURL(/\/market\/chart\?symbol=ag&series_kind=actual_dominant&frequency=15m/)
})

test('does not conceal incomplete freshness as a full-universe result', async ({ page }) => {
  await mockRadar(page, radar('degraded'))
  await page.goto('/market')

  await expect(page.getByText('2026-08-11 · 59/60')).toBeVisible()
  await expect(page.getByText('Radar 数据不完整：stale jm', { exact: true })).toBeVisible()
})
