import { expect, test } from '@playwright/test'
import { mockMarketDetail, navigateClient } from './market-detail.helpers.mjs'

const htdy = symbol => `/market/chart?symbol=${symbol}&view=htdy&series_kind=actual_dominant&frequency=15m`
const rule = {
  rule_code: 'htdy_original_15m', display_name: '火天大有', kind: 'indicator_observation',
  input_frequencies: ['1m', '5m', '15m', '30m', '60m', '1d', '1w'],
  enabled_for_product: true, enabled_frequencies: ['15m'],
}

test('HTDY never presents the previous product Scope while its new product read is pending', async ({ page }) => {
  await mockMarketDetail(page)
  await page.route('**/api/v1/reference-trading/**', route => route.fulfill({ status: 503, json: { detail: 'Explicit fixture: historical reference unavailable' } }))
  let release
  const gate = new Promise(resolve => { release = resolve })
  await page.route('**/api/alerts/products/rb', async route => {
    await gate
    await route.fulfill({ json: { symbol: 'rb', rules: [rule] } })
  })
  await page.goto(htdy('jm'))
  await page.getByRole('tab', { name: '预警与运行', exact: true }).click()
  await expect(page.getByText(/JM 15m · 当前 Scope 已启用/)).toBeVisible()
  try {
    await navigateClient(page, htdy('rb'))
    await expect(page.locator('[data-detail-workspace="htdy"]')).toBeVisible()
    await page.getByRole('tab', { name: '预警与运行', exact: true }).click()
    await expect(page.getByText('HTDY Rule / Scope 暂不可用', { exact: true })).toBeVisible()
    await expect(page.getByText(/JM 15m · 当前 Scope 已启用/)).toHaveCount(0)
  } finally { release() }
  await expect(page.getByText(/RB 15m · 当前 Scope 已启用/)).toBeVisible()
})

test('HTDY rejects a fulfilled Scope response whose product identity is wrong', async ({ page }) => {
  await mockMarketDetail(page)
  await page.route('**/api/v1/reference-trading/**', route => route.fulfill({ status: 503, json: { detail: 'Explicit fixture: historical reference unavailable' } }))
  await page.route('**/api/alerts/products/jm', route => route.fulfill({ json: { symbol: 'rb', rules: [rule] } }))
  await page.goto(htdy('jm'))
  await page.getByRole('tab', { name: '预警与运行', exact: true }).click()
  await expect(page.getByText('HTDY Rule / Scope 暂不可用', { exact: true })).toBeVisible()
  await expect(page.getByText(/JM 15m · 当前 Scope 已启用/)).toHaveCount(0)
  await expect(page.getByText(/RB 15m · 当前 Scope 已启用/)).toHaveCount(0)
})
