import { expect, test } from '@playwright/test'

test('reads the real frozen FU trial from isolated PostgreSQL through the develop page', async ({ page }) => {
  test.skip(process.env.PLAYWRIGHT_NEWOW_BACKTEST_ISOLATED !== '1', 'requires the isolated P4 preview and frozen FU run')
  const requests = []
  page.on('request', request => {
    const url = new URL(request.url())
    if (url.pathname.includes('/newow/backtests')) requests.push({ url, method: request.method() })
  })
  await page.goto('/market/chart?symbol=fu&view=newow&strategy=trend&frequency=5m&series_kind=actual_dominant')
  await expect(page.getByRole('button', { name: '回测记录', exact: true })).toBeVisible()
  expect(requests).toHaveLength(0)
  await page.getByRole('button', { name: '回测记录', exact: true }).click()
  const panel = page.getByTestId('newow-backtest')
  await expect(panel).toContainText('主力历史数据资格不足')
  await expect(panel).toContainText('暂无成功回测结果')
  if (process.env.PLAYWRIGHT_NEWOW_BACKTEST_SCREENSHOTS) {
    await panel.screenshot({ path: `${process.env.PLAYWRIGHT_NEWOW_BACKTEST_SCREENSHOTS}/p4-fu-formal.png` })
  }
  await panel.getByLabel('结果系列').selectOption({ label: '历史试验' })
  await expect(panel.getByTestId('newow-backtest-identity')).toContainText('历史试验 · 数据截至 2026-01-05')
  await expect(panel).toContainText('9765.07700000')
  const tradeRows = panel.getByRole('region', { name: '逐笔成交' }).locator('tbody tr')
  await expect(tradeRows).toHaveCount(5)
  await panel.getByRole('button', { name: '更多逐笔成交' }).click()
  await expect(tradeRows).toHaveCount(8)
  await tradeRows.first().getByRole('button', { name: '信号切片' }).click()
  await expect(panel).toContainText('2026-01-05T09:05:00+08:00')
  expect(requests.every(item => item.method === 'GET')).toBe(true)
  const pages = requests.filter(item => item.url.pathname.endsWith('/trades'))
  expect(pages).toHaveLength(2)
  expect(pages[0].url.pathname).toBe(pages[1].url.pathname)
  expect(pages[1].url.searchParams.has('cursor')).toBe(true)
  if (process.env.PLAYWRIGHT_NEWOW_BACKTEST_SCREENSHOTS) {
    await panel.screenshot({ path: `${process.env.PLAYWRIGHT_NEWOW_BACKTEST_SCREENSHOTS}/p4-fu-trial.png` })
    await panel.getByRole('region', { name: '结算权益' }).screenshot({
      path: `${process.env.PLAYWRIGHT_NEWOW_BACKTEST_SCREENSHOTS}/p4-fu-equity.png`,
    })
  }
  await page.goto('/market/chart?symbol=fu&view=newow&strategy=oscillation&frequency=15m&series_kind=actual_dominant')
  await page.getByRole('button', { name: '回测记录', exact: true }).click()
  await expect(panel).toContainText('暂无成功回测结果')
  expect(requests.at(-1).url.searchParams.get('strategy')).toBe('oscillation')
  expect(requests.at(-1).url.searchParams.get('frequency')).toBe('15m')
  await expect(page.getByRole('tab', { name: '运行台', exact: true })).toBeVisible()
  await expect(page.getByRole('tab', { name: '研究', exact: true })).toBeVisible()
})
