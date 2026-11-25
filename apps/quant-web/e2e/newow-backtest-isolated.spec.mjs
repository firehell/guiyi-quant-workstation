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

test('PC research reads and locates the existing FU result using the isolated read router', async ({ page }) => {
  const readOrigin = process.env.PLAYWRIGHT_WORKSTATION_NEWOW_READ_ORIGIN
  test.skip(!readOrigin, 'requires the isolated Newow result store and a read-only API')
  expect(new URL(readOrigin).hostname).toBe('127.0.0.1')

  const requests = []
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    requests.push({ url, method: request.method() })
    if (request.method() !== 'GET') return route.abort()
    if (!url.pathname.startsWith('/api/v1/newow/backtests/')) return route.continue()
    const response = await route.fetch({ url: new URL(url.pathname + url.search, readOrigin).href })
    await route.fulfill({ response })
  })

  await page.goto('/research')
  const panel = page.getByTestId('newow-backtest')
  const selectors = page.getByRole('region', { name: '牛哇盘后与固定回测' })
  await selectors.getByRole('combobox', { name: '品种', exact: true }).selectOption('fu')
  await selectors.getByRole('combobox', { name: '周期', exact: true }).selectOption('5m')
  await expect(panel).toContainText('主力历史数据资格不足')
  await expect(panel).toContainText('暂无成功发布结果')

  await panel.getByLabel('结果系列').selectOption({ label: '历史试验' })
  await expect(panel.getByTestId('newow-backtest-identity')).toContainText('历史试验 · 数据截至交易日 2026-01-05')
  await expect(panel).toContainText('9765.07700000')
  const trades = panel.getByRole('region', { name: '逐笔成交' })
  const rows = trades.locator('tbody tr')
  await expect(rows).toHaveCount(5)
  await trades.getByRole('button', { name: '更多逐笔成交' }).click()
  await expect(rows).toHaveCount(8)
  await rows.first().getByRole('button', { name: '信号切片' }).click()
  await expect(trades).toContainText('2026-01-05T09:05:00+08:00')
  const equity = panel.getByRole('region', { name: '结算权益' })
  await expect(equity.locator('tbody tr').first()).toBeVisible()

  const pages = requests.filter(({ url }) => url.pathname.endsWith('/trades'))
  expect(pages).toHaveLength(2)
  expect(pages[0].url.pathname).toBe(pages[1].url.pathname)
  expect(pages[1].url.searchParams.has('cursor')).toBe(true)
  const equityRequest = requests.find(({ url }) => url.pathname.endsWith('/equity'))
  expect(equityRequest.url.pathname).toBe(pages[0].url.pathname.replace(/trades$/, 'equity'))
  expect(requests.every(({ method }) => method === 'GET')).toBe(true)

  if (process.env.PLAYWRIGHT_WORKSTATION_SCREENSHOTS) {
    await page.screenshot({
      path: `${process.env.PLAYWRIGHT_WORKSTATION_SCREENSHOTS}/研究页-FU冻结试验.png`,
      fullPage: true,
      animations: 'disabled',
    })
  }
})
