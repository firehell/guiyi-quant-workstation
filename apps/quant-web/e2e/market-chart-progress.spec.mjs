import { expect, test } from '@playwright/test'
import { detailBar, installDetailFakeWebSocket, mockMarketDetail } from './market-detail.helpers.mjs'

for (const [status, label] of [
  ['source', '行情采集未跟上'],
  ['confirmation', '完成确认未跟上'],
  ['confirmed', '图表显示未跟上'],
  ['waiting', '交易暂停'],
]) {
  test(`market chart identifies ${status} from independent progress`, async ({ page }) => {
    await installDetailFakeWebSocket(page)
    await mockMarketDetail(page, { live: true, barsPage: () => ({ bars: [detailBar('jm', 0)] }) })
    await page.route('**/api/v1/market/chart-progress?*', route => route.fulfill({ json: {
      phase: status === 'waiting' ? 'BREAK' : 'TRADING',
      trading_day: '2026-09-03',
      contract: 'JM2601',
      status,
      expected_end: '2026-09-03T02:45:00Z',
      source_end: status === 'source' ? '2026-09-03T02:30:00Z' : '2026-09-03T02:45:00Z',
      source_received_at: '2026-09-03T02:45:02Z',
      completed_end: status === 'confirmed' ? '2026-09-03T02:45:00Z' : '2026-09-03T02:30:00Z',
    } }))
    await page.goto('/market/chart?symbol=jm&view=free&series_kind=actual_dominant&frequency=15m')
    if (status === 'confirmed') {
      await expect.poll(() => page.evaluate(() => window.__marketDetailSockets.some(socket =>
        new URL(socket.url).pathname.endsWith('/market/ws')))).toBe(true)
      await page.evaluate(() => window.__marketDetailSockets.find(socket =>
        new URL(socket.url).pathname.endsWith('/market/ws')).close())
    }
    const progress = page.getByTestId('market-chart-progress')
    await expect(progress.locator('summary')).toContainText(label)
    await expect(progress.locator('summary')).toContainText('北京时间')
    await progress.locator('summary').click()
    await expect(progress.getByText('JM2601', { exact: true })).toBeVisible()
    await expect(progress.getByText('浏览器最后绘制')).toBeVisible()
  })
}
