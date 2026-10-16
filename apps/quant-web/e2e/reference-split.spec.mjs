import { test, expect } from '@playwright/test'
import { buildNewowSplitFixtureEnvelopeForTest, installNewowProductFixtures, newowRoute, productRequests, assertNoUnexpectedRequests } from './newow-product.helpers.mjs'

test('selected split mode keeps full metrics, lazy records and source positions on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await installNewowProductFixtures(page, { onProductRequest: async ({ route, url, section }) => {
    if (section !== 'reference' || !url.searchParams.has('reference_part')) return
    const payload = buildNewowSplitFixtureEnvelopeForTest(url)
    const value = payload.reference.value
    if (value.reference_mode === 'page_ordinary' && value.reference_part === 'overview') {
      const first = value.recent_items[0]
      value.recent_items = ['2026-06-11T07:00:00.000Z', '2026-06-12T07:00:00.000Z', '2026-06-13T07:00:00.000Z']
        .map((buyDate, index) => ({ ...first, buyDate,
          ...(index === 0 ? { forceClose: true, buyBarIsLive: true } : {}) }))
    }
    if (value.reference_mode === 'page_ordinary' && value.reference_part === 'curve') {
      value.curve.points = [
        { position: 0, bar_end: '2026-01-01T07:00:00.000Z', trading_day: '2026-01-01', segment_id: 'first', value: '0' },
        { position: 1250, bar_end: '2026-06-01T07:00:00.000Z', trading_day: '2026-06-01', segment_id: 'first', value: null },
        { position: 2499, bar_end: '2026-09-03T07:00:00.000Z', trading_day: '2026-09-03', segment_id: 'last', value: '12.34' },
      ]
      value.curve.total_points = 2500
      value.curve.sampled = true
      value.curve.metrics.return_percentage_points = '12.34'
      value.curve.metrics.drawdown = '7.89'
      value.curve.annualized_pct = '14.87'
      value.curve.segment_annuals = [
        { segment_id: 'RB2610', since: '2026-01-01T07:00:00Z', through: '2026-04-01T07:00:00Z', annualized_pct: '11.20' },
        { segment_id: 'RB2701', since: '2026-04-02T07:00:00Z', through: '2026-09-03T07:00:00Z', annualized_pct: '16.40' },
      ]
    }
    if (value.reference_mode === 'page_ordinary' && value.reference_part === 'history') {
      const item = value.items[0]
      if (url.searchParams.has('history_before')) {
        value.items = [{ ...item, buyDate: '2026-01-01T07:00:00.000Z' }]
        value.next_before = null
      } else {
        value.items = Array.from({ length: 50 }, (_, index) => ({ ...item,
          buyDate: new Date(Date.parse('2026-07-01T07:00:00Z') + index * 86400000).toISOString() }))
        value.next_before = 'cursor-2'
      }
    }
    await route.fulfill({ json: payload })
    return 'handled'
  } })
  await page.goto(newowRoute())
  const region = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
  await region.scrollIntoViewIfNeeded()
  await expect.poll(() => productRequests(state, 'reference').map(entry => entry.url.searchParams.get('reference_part'))).toEqual(['overview', 'curve'])
  await expect(region.getByText('曲线显示 3 / 2500 个保留采样点')).toBeVisible()
  await expect(region.getByTestId('newow-reference-summary')).toContainText('12.34')
  await expect(region.getByTestId('newow-reference-summary')).toContainText('7.89')
  await expect(region.getByTestId('newow-reference-summary')).toContainText('页面累计参考收益+12.34 百分点')
  await expect(region.getByTestId('newow-reference-summary')).toContainText('页面曲线回撤（百分点）7.89 百分点')
  await expect(region.getByTestId('newow-reference-summary')).toContainText('页面参考胜率（含期末估值）')
  await expect(region.getByTestId('newow-reference-summary')).toContainText('页面参考次数（含期末估值）')
  await expect(region.getByText('页面参考年化 14.87% · 2个合约段汇总')).toBeVisible()
  await region.getByText('各合约段年化 · 不跨段计算').click()
  await expect(region.getByText('合约段 1 · 01-01 → 04-01 · 年化 11.20%')).toBeVisible()
  expect(productRequests(state, 'reference').filter(entry => entry.url.searchParams.get('reference_part') === 'history')).toHaveLength(0)
  await expect(region.locator('.newow-reference__card')).toHaveCount(3)
  await expect(region.locator('.newow-reference__card').first()).toContainText('持仓参考中')
  await expect(region.locator('.newow-reference__card').first()).toContainText('参考估值')
  await expect(region.locator('.newow-reference__card').first()).toContainText('末根新建仓的页面估值投影')
  const svg = region.locator('.page-performance .return-curve svg')
  await svg.focus(); await svg.press('End')
  await expect(region.locator('.return-curve__readout')).toContainText('2026-09-03')
  await region.getByRole('button', { name: '查看完整历史记录' }).click()
  await expect(region.locator('.newow-reference__card')).toHaveCount(50)
  await region.getByRole('button', { name: '加载更多历史参考记录' }).click()
  await expect(region.locator('.newow-reference__card')).toHaveCount(51)
  await region.getByRole('button', { name: '已完成参考交易' }).click()
  await expect.poll(() => productRequests(state, 'reference').some(entry => entry.url.searchParams.get('reference_mode') === 'closed' && entry.url.searchParams.get('reference_part') === 'curve')).toBe(true)
  await expect(region.getByTestId('newow-reference-summary')).toContainText('参考权益比例回撤')
  await region.getByRole('button', { name: '页面参考收益' }).click()
  await region.getByRole('button', { name: '理论值' }).click()
  await expect.poll(() => productRequests(state, 'reference').some(entry => entry.url.searchParams.get('reference_mode') === 'page_ideal')).toBe(true)
  await expect(region.getByTestId('newow-reference-summary')).toContainText('单笔最大亏损（百分点）')
  await region.getByRole('button', { name: '已完成参考交易' }).click()
  await expect.poll(() => productRequests(state, 'reference').some(entry => entry.url.searchParams.get('reference_mode') === 'theoretical')).toBe(true)
  await region.getByRole('button', { name: '近3月' }).click()
  await expect.poll(() => productRequests(state, 'reference').some(entry => entry.url.searchParams.get('reference_part') === 'overview' && entry.url.searchParams.get('performance_since') === '2026-06-03')).toBe(true)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  assertNoUnexpectedRequests(state)
})

test('mixed page segments retain their own drawdown unit', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, url, section }) => {
    if (section !== 'reference' || url.searchParams.get('reference_mode') !== 'page_ordinary'
      || url.searchParams.get('reference_part') !== 'curve') return
    const payload = buildNewowSplitFixtureEnvelopeForTest(url)
    payload.reference.value.curve.metrics.drawdown_kind = 'mixed_segment'
    payload.reference.value.curve.metrics.drawdown = '3.125'
    await route.fulfill({ json: payload })
    return 'handled'
  } })
  await page.goto(newowRoute())
  const region = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
  await region.scrollIntoViewIfNeeded()
  await expect(region.getByTestId('newow-reference-summary')).toContainText('分段页面损失统计（百分点）3.13 百分点')
  assertNoUnexpectedRequests(fixture)
})

test('mode switch cancels a delayed curve without displaying its stale metrics', async ({ page }) => {
  const state = await installNewowProductFixtures(page, { onProductRequest: async ({ route, url, section }) => {
    if (section !== 'reference' || url.searchParams.get('reference_part') !== 'curve') return
    const payload = buildNewowSplitFixtureEnvelopeForTest(url)
    if (url.searchParams.get('reference_mode') === 'page_ordinary') {
      payload.reference.value.curve.metrics.return_percentage_points = '99.99'
      await new Promise(resolve => setTimeout(resolve, 350))
    } else payload.reference.value.curve.metrics.return_percentage_points = '5.10'
    try { await route.fulfill({ json: payload }) } catch { /* request cancelled by mode switch */ }
    return 'handled'
  } })
  await page.goto(newowRoute())
  const region = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
  await region.scrollIntoViewIfNeeded()
  await expect.poll(() => productRequests(state, 'reference').some(entry => entry.url.searchParams.get('reference_mode') === 'page_ordinary' && entry.url.searchParams.get('reference_part') === 'curve')).toBe(true)
  await region.getByRole('button', { name: '已完成参考交易' }).click()
  await expect(region.getByTestId('newow-reference-summary')).toContainText('+5.1%')
  await expect(region.getByTestId('newow-reference-summary')).not.toContainText('99.99')
  assertNoUnexpectedRequests(state)
})

test('changing the window in the same mode clears a selected older trade', async ({ page }) => {
  const oldId = 'trade-before-three-month-window'
  const fixture = await installNewowProductFixtures(page, { onProductRequest: async ({ route, url, section }) => {
    if (section !== 'reference' || url.searchParams.get('reference_mode') !== 'closed'
      || url.searchParams.get('reference_part') !== 'curve') return
    const payload = buildNewowSplitFixtureEnvelopeForTest(url)
    const value = payload.reference.value
    if (!url.searchParams.has('performance_since') || url.searchParams.get('performance_since') === '2026-01-01') {
      const current = value.curve.points[0]
      const trade = { ...current.trade, reference_trade_id: oldId,
        entry_bar_end: '2026-01-05T07:00:00Z', entry_trading_day: '2026-01-05',
        exit_bar_end: '2026-02-01T07:00:00Z', exit_trading_day: '2026-02-01' }
      const older = { ...current, position: 0, bar_end: trade.exit_bar_end, trading_day: trade.exit_trading_day,
        reference_trade_id: oldId, value: '1.00', trade }
      value.curve.points = [older, { ...current, position: 1 }]
      value.curve.total_points = 2
    }
    await route.fulfill({ json: payload })
    return 'handled'
  } })
  await page.goto(newowRoute())
  const region = page.getByRole('region', { name: 'Newow 参考与解释', exact: true })
  await region.scrollIntoViewIfNeeded()
  await region.getByRole('button', { name: '已完成参考交易' }).click()
  const curve = region.getByLabel('参考收益曲线，点击查看读数或定位交易记录', { exact: true })
  await expect(curve).toBeVisible()
  await curve.focus(); await curve.press('Home'); await curve.press('Enter')
  await expect(region.locator(`#reference-trade-${oldId}`)).toBeVisible()
  await region.getByRole('button', { name: '近3月' }).click()
  await expect.poll(() => productRequests(fixture, 'reference').some(entry => entry.url.searchParams.get('reference_mode') === 'closed'
    && entry.url.searchParams.get('reference_part') === 'curve' && entry.url.searchParams.get('performance_since') === '2026-06-03')).toBe(true)
  await expect(region.locator(`#reference-trade-${oldId}`)).toHaveCount(0)
  assertNoUnexpectedRequests(fixture)
})
