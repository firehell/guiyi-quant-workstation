import { expect, test } from '@playwright/test'
import { mockSubingReference, referenceBars, subingReferenceFixture } from './subing-reference.helpers.mjs'

test('historical reference uses the unified API base exactly once', async ({ page }) => {
  const referencePaths = []
  page.on('request', request => {
    const pathname = new URL(request.url()).pathname
    if (pathname.endsWith('/subing/reference')) referencePaths.push(pathname)
  })
  await mockSubingReference(page)
  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.getByRole('heading', { name: '乐观参考交易' })).toBeVisible()
  expect(referencePaths).toEqual(['/api/v1/market/jm/subing/reference'])
})

test('30m research loads its own reference without querying 15m events', async ({ page }) => {
  const frequencies = []
  page.on('request', request => {
    if (new URL(request.url()).pathname.endsWith('/subing/reference')) frequencies.push(new URL(request.url()).searchParams.get('frequency'))
  })
  const facts = await mockSubingReference(page, { response: () => ({ ...subingReferenceFixture(), frequency: '30m', formula_version: 'subing_ths_30m_v1' }) })
  await page.goto('/market/chart?symbol=jm&view=subing&series_kind=actual_dominant&frequency=30m')
  await expect(page.getByText('历史研究，本周期未启用预警；正式 S↑ / S↓ 仅在 15分周期。')).toBeVisible()
  await expect(page.getByRole('heading', { name: '乐观参考交易' })).toBeVisible()
  expect(frequencies).toEqual(['30m'])
  expect(facts.alertRequests).toHaveLength(0)
  await expect(page.getByRole('button', { name: '预警记录' })).toHaveCount(0)
})

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`SuBing historical fixture preview ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport)
    await mockSubingReference(page)
    await page.goto('/market/chart?symbol=jm&view=subing')
    await expect(page.getByRole('heading', { name: '乐观参考交易' })).toBeVisible()
    await expect(page.getByLabel('参考开始交易日')).toHaveValue('2026-08-12')
    await page.getByTestId('kline-shell').scrollIntoViewIfNeeded()
    await expect(page.locator('.reference-callout')).not.toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath(`subing-reference-fixture-${viewport.width}x${viewport.height}.png`) })
    await page.locator('.subing-reference').screenshot({ path: testInfo.outputPath(`subing-reference-table-fixture-${viewport.width}.png`) })
    await page.getByTestId('kline-shell').scrollIntoViewIfNeeded()
    const firstCallout = page.locator('.reference-callout').first()
    await expect(firstCallout).toHaveAttribute('role', 'img')
    await firstCallout.click({ force: true })
    await expect(page.getByRole('dialog', { name: '历史重算参考信号' })).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}

test('dense SuBing reference nodes keep their real micro size without becoming interactive cards', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockSubingReference(page, { response() {
    const data = subingReferenceFixture()
    const owner = referenceBars[64]
    return {
      ...data,
      signals: Array.from({ length: 300 }, (_, index) => ({
        signal_id: `dense-subing-${index}`,
        bar_end: owner.bar_end,
        trading_day: owner.trading_day,
        physical_contract: 'JM2601',
        segment_id: 'fixture-segment',
        direction: index % 2 ? 'buy' : 'sell',
        reference_price: String(owner.close),
        action: 'SAME_DIRECTION',
        entry_trade_id: null,
        closed_trade_id: null,
        closed_return_pct: null,
      })),
    }
  } })
  await page.goto('/market/chart?symbol=jm&view=subing')
  const labels = page.locator('.reference-callout')
  await expect(labels).toHaveCount(300)
  const microIndex = await labels.evaluateAll(nodes => nodes.findIndex(node => node.getBoundingClientRect().width <= 8.5))
  expect(microIndex).toBeGreaterThanOrEqual(0)
  const target = labels.nth(microIndex)
  const before = await target.boundingBox()
  expect(before?.width).toBeLessThanOrEqual(8.5)
  expect(before?.height).toBeLessThanOrEqual(8.5)
  await target.click({ force: true })
  await expect(page.getByRole('dialog', { name: '历史重算参考信号' })).toHaveCount(0)
  expect((await target.boundingBox())?.width ?? 0).toBeLessThanOrEqual(8.5)
  expect((await target.boundingBox())?.height ?? 0).toBeLessThanOrEqual(8.5)
})

test('historical unavailable keeps immutable events and Rule facts visible', async ({ page }) => {
  await mockSubingReference(page, { unavailable: true })
  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.getByText('历史参考不可用，请核查数据覆盖或重新读取。实际预警记录独立展示。')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toHaveAttribute('data-alert-marker-count', '1')
  await page.getByRole('tab', { name: '历史记录', exact: true }).click()
  await expect(page.locator('.detail-section-tabs__history')).toContainText('Bar 2026-09-03 12:30 北京时间')
})

test('daily quality interruptions sharing or preceding chart days keep first load ordered', async ({ page }) => {
  const days = ['2026-09-16', '2026-09-17', '2026-09-18']
  const dailyBars = days.map((day, index) => ({ ...referenceBars[index], bar_end: `${day}T15:00:00+08:00`, trading_day: day }))
  await mockSubingReference(page, { bars: dailyBars, response() {
    const base = subingReferenceFixture()
    const qualityBars = days.map((day, index) => ({
      bar_end: `${day}T15:00:00+08:00`, trading_day: day,
      open: String(100 + index), high: String(102 + index), low: String(99 + index), close: String(101 + index),
      volume: '10', turnover: '1000', open_interest: '20', physical_contract: 'JM2601',
      segment_id: 'owner', calculation_segment_id: 'calculation',
    }))
    const interruption = (day, contract) => ({
      bar_end: `${day}T15:00:00+08:00`, trading_day: day, physical_contract: contract,
      segment_id: `owner-${contract}`, classification: 'NONPOSITIVE_CLOSE',
      classification_version: 'rqdata-d1-nonpositive-close-v1', request_sha256: 'b'.repeat(64), response_sha256: 'c'.repeat(64),
    })
    return {
      ...base, frequency: '1d', formula_version: 'subing_ths_1d_v1',
      reference_model_version: 'subing_reference_reverse_close_quality_segment_v2', research_status: 'WARMING',
      as_of: '2026-09-18T16:00:00+08:00', performance_since: '2026-09-16', performance_through: '2026-09-18',
      reference_cutoff: '2026-09-18T15:00:00+08:00',
      summary: { ...base.summary, closed_count: 0, win_count: 0, loss_count: 0, open_count: 0, interrupted_count: 0, rollover_interrupted_count: 0, data_interrupted_count: 0, win_rate_pct: null, mean_return_pct: null, sum_return_percentage_points: '0' },
      signals: [], indicators: [], items: [], quality_policy_version: 'subing-d1-quality-segment-v1',
      coverage_intervals: [{ since: '2026-09-16', through: '2026-09-18', status: 'WARMING', physical_contract: 'JM2601', segment_id: 'owner', calculation_segment_id: 'calculation' }],
      quality_interruptions: [interruption('2026-08-01', 'JM2509'), interruption('2026-09-16', 'JM2601'), interruption('2026-09-16', 'JM2605')],
      quality_chart_bars: qualityBars,
    }
  } })
  await page.goto('/market/chart?symbol=jm&view=subing&series_kind=actual_dominant&frequency=1d')
  await expect(page.locator('[data-detail-workspace="subing"]')).toBeVisible()
  await expect(page.getByTestId('kline-shell')).toBeVisible()
  await expect(page.getByText('日线质量状态：预热中（不足 34 根有效日线）；质量中断 3 项。')).toBeVisible()
  await expect(page.getByText('页面加载失败')).toHaveCount(0)
})

test('date range and cursor keep a fixed summary and row selects its reference record', async ({ page }) => {
  const requests = []
  await mockSubingReference(page, { response(url) {
    requests.push(url)
    const full = subingReferenceFixture()
    return { ...full, performance_since: url.searchParams.get('since') || full.performance_since, performance_through: url.searchParams.get('through') || full.performance_through, items: url.searchParams.get('before') ? full.items.slice(2) : full.items.slice(0, 2), next_before: url.searchParams.get('before') ? null : 'fixture-next' }
  } })
  await page.goto('/market/chart?symbol=jm&view=subing')
  await page.getByLabel('参考开始交易日').fill('2026-08-20')
  await page.getByLabel('参考结束交易日').fill('2026-09-04')
  await page.getByRole('button', { name: '读取参考', exact: true }).click()
  await expect.poll(() => requests.at(-1).searchParams.get('since')).toBe('2026-08-20')
  const summary = await page.locator('.subing-reference__summary').innerText()
  await page.getByRole('button', { name: '加载更多参考记录' }).click()
  await expect(page.locator('.subing-reference tbody tr')).toHaveCount(4)
  expect(await page.locator('.subing-reference__summary').innerText()).toBe(summary)
  expect(requests.at(-1).searchParams.get('as_of')).toBe('2026-09-08T16:00:00+08:00')
  await page.getByRole('button', { name: '查看详情', exact: true }).first().click()
  await expect(page.getByRole('dialog', { name: '历史参考记录详情' })).toContainText('尚无配对平仓')
})

test('wrong physical owner stays unanchored and a date refresh closes prior historical details', async ({ page }) => {
  let mismatch = false
  await mockSubingReference(page, { response() { const data = subingReferenceFixture(); return mismatch ? { ...data, signals: data.signals.map(signal => ({ ...signal, physical_contract: 'JM2605' })), input_snapshot_hash: 'b'.repeat(64) } : data } })
  await page.goto('/market/chart?symbol=jm&view=subing')
  await expect(page.locator('.reference-callout')).toHaveCount(4)
  await page.getByRole('button', { name: '查看详情', exact: true }).first().click()
  await expect(page.getByRole('dialog', { name: '历史参考记录详情' })).toBeVisible()
  await page.keyboard.press('Escape')
  mismatch = true
  await page.getByRole('button', { name: '读取参考', exact: true }).click()
  await expect(page.locator('.reference-callout')).toHaveCount(0)
  await expect(page.getByText('4 个历史参考信号尚未匹配当前已载 Bar 与物理合约；可在参考记录中点击定位，数据不足时不绘制。')).toBeVisible()
  await expect(page.getByRole('dialog', { name: '历史参考记录详情' })).toHaveCount(0)
})

test('explicit same-row focus recenters after pan and highlights its exact physical entry and exit', async ({ page }) => {
  await mockSubingReference(page)
  await page.goto('/market/chart?symbol=jm&view=subing')
  const row = page.getByRole('button', { name: '定位图表', exact: true }).nth(1)
  await row.click()
  await page.getByTestId('kline-shell').scrollIntoViewIfNeeded()
  const selected = page.locator('.reference-candle-selection').last()
  await expect(page.locator('.reference-candle-selection')).toHaveCount(2)
  await expect(page.locator('.reference-callout--selected')).toHaveCount(2)
  const original = await selected.boundingBox()
  const chart = await page.locator('.kline-shell .chart').boundingBox()
  await page.mouse.move(chart.x + chart.width * .5, chart.y + 180)
  await page.mouse.down()
  await page.mouse.move(chart.x + chart.width * .5 + 140, chart.y + 180, { steps: 12 })
  await page.mouse.up()
  await expect.poll(async () => Math.abs((await selected.boundingBox()).x - original.x)).toBeGreaterThan(50)
  await row.click()
  await page.getByTestId('kline-shell').scrollIntoViewIfNeeded()
  await expect.poll(async () => Math.abs((await selected.boundingBox()).x - original.x)).toBeLessThan(3)
  await page.getByRole('button', { name: '读取参考', exact: true }).click()
  await expect(page.locator('.reference-candle-selection')).toHaveCount(0)
  await expect(page.locator('.reference-callout--selected')).toHaveCount(0)
})
