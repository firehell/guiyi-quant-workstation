import { test, expect } from '@playwright/test'
import { mockMarketDetail, subingEvent, subingRule } from './market-detail.helpers.mjs'
const frequencies = ['5m', '15m', '30m', '60m', '1d', '1w']
test('six-period references preserve unavailable state without historical fallback', async ({ page }) => {
  const rule = { ...subingRule(true), input_frequencies: frequencies, enabled_frequencies: frequencies }
  await mockMarketDetail(page, { alertRules: [rule], alertEvents: ({ url }) => [
    { ...subingEvent('jm'), frequency: url.searchParams.get('frequency') ?? '15m' },
  ] })
  const forward = [], historical = []
  await page.route('**/api/v1/market/*/subing/reference**', route => {
    historical.push(route.request().url())
    return route.fulfill({ status: 503, json: { detail: 'Explicit fixture: history unavailable' } })
  })
  await page.route('**/api/v1/reference-trading/**', route => {
    forward.push(new URL(route.request().url()))
    return route.fulfill({ status: 503, json: { detail: 'Explicit fixture: reference unavailable' } })
  })
  for (const frequency of frequencies) {
    await page.goto(`/market/chart?symbol=jm&view=subing&frequency=${frequency}`)
    const workspace = page.locator('[data-detail-workspace="subing"]')
    await expect(workspace.getByRole('region', { name: '实时留存参考交易收益面板', exact: true })).toBeVisible()
    await expect(workspace.getByRole('alert').filter({ hasText: '不会回退到历史重算' })).toBeVisible()
    await expect.poll(() => forward.some(url => url.searchParams.get('frequency') === frequency)).toBe(true)
  }
  expect(historical).toEqual([])
})
