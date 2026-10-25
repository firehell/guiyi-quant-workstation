import { expect, test } from '@playwright/test'
import { detailBar, htdyEvent, mockMarketDetail } from './market-detail.helpers.mjs'

// Fixtures prove presentation/query boundaries, not natural Runtime evidence.
async function setup(page) {
  const bars = Array.from({ length: 80 }, (_, i) => detailBar('jm', i))
  const requests = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.pathname.includes('/api/alerts/events') || url.pathname.includes('/reference-trading/')) requests.push(url)
  })
  await mockMarketDetail(page, { barsPage: ({ url }) => ['1d', '1w'].includes(url.searchParams.get('frequency')) ? undefined : ({ bars }), alertEvents: ({ url }) => [htdyEvent('jm', url.searchParams.get('frequency'))] })
  await page.route('**/api/v1/reference-trading/streams?**', route => route.fulfill({ json: { items: [] } }))
  return requests
}
const address = frequency => `/market/chart?symbol=jm&view=htdy&series_kind=actual_dominant&frequency=${frequency}`
for (const frequency of ['1m', '5m', '15m', '30m', '1d', '1w']) {
  test(`HTDY ${frequency} old link retains chart without realtime reads`, async ({ page }) => {
    const requests = await setup(page)
    await page.goto(address(frequency))
    await expect(page.getByText('实时信号统一记录于60分钟；当前周期保留历史研究图表。')).toBeVisible()
    await expect(page.locator('[data-detail-workspace="htdy"] .market-kline-stage')).toBeVisible()
    await expect(page.locator('.observed-records')).toHaveCount(0)
    await page.waitForTimeout(150)
    expect(requests).toHaveLength(0)
    expect(new URL(page.url()).searchParams.get('frequency')).toBe(frequency)
  })
}
test('HTDY 60m reads events, empty stream is explicit, then switching stops reads', async ({ page }) => {
  const requests = await setup(page)
  await page.goto(address('60m'))
  await expect(page.locator('.observed-records')).toBeVisible()
  await expect(page.getByText('尚无实时留存参考交易流', { exact: false })).toBeVisible()
  await expect.poll(() => requests.filter(url => url.pathname.includes('/api/alerts/events')).length).toBeGreaterThan(0)
  expect(requests.every(url => url.searchParams.get('frequency') === '60m')).toBe(true)
  await page.goto(address('15m'))
  await expect(page.getByText('实时信号统一记录于60分钟；当前周期保留历史研究图表。')).toBeVisible()
  const count = requests.length
  await page.waitForTimeout(150)
  expect(requests).toHaveLength(count)
})
test('HTDY 60m event failure is disclosed and leaving 60m hides the audit', async ({ page }) => {
  await setup(page)
  await page.route('**/api/alerts/events?**', route => route.fulfill({ status: 503, json: { detail: 'fixture unavailable' } }))
  await page.goto(address('60m'))
  await page.locator('.observed-records summary').click()
  await expect(page.getByText('实际预警读取未完成或失败，当前实际覆盖尚不能确认。')).toBeVisible()
  await page.goto(address('15m'))
  await expect(page.locator('.observed-records')).toHaveCount(0)
})
test('HTDY SPA 60m → 15m → 60m rejects a delayed old Event response', async ({ page }) => {
  const requests = await setup(page)
  let release, arrived
  const held = new Promise(resolve => { release = resolve })
  const started = new Promise(resolve => { arrived = resolve })
  let count = 0
  await page.route('**/api/alerts/events?**', async route => {
    if (++count === 1) { arrived(); await held }
    await route.fulfill({ json: { items: [htdyEvent('jm', '60m')] } }).catch(() => {})
  })
  await page.goto(address('60m'))
  await started
  const controls = page.getByRole('group', { name: '周期', exact: true })
  await controls.getByRole('button', { name: '15分钟', exact: true }).click()
  await expect(page.getByText('实时信号统一记录于60分钟；当前周期保留历史研究图表。')).toBeVisible()
  release()
  await expect(page.locator('.observed-records')).toHaveCount(0)
  const before = requests.length
  await page.waitForTimeout(150)
  expect(requests).toHaveLength(before)
  await controls.getByRole('button', { name: '60分钟', exact: true }).click()
  await expect(page.locator('.observed-records')).toBeVisible()
  await expect.poll(() => count).toBe(2)
  expect(requests.every(url => url.searchParams.get('frequency') === '60m')).toBe(true)
})
