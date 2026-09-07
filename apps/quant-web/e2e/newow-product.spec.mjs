import { expect, test } from '@playwright/test'
import { performance } from 'node:perf_hooks'
import os from 'node:os'

import {
  NEWOW_FREQUENCIES,
  NEWOW_STRATEGIES,
  assertNoUnexpectedRequests,
  installNewowProductFixtures,
  newowRoute,
  productRequests,
} from './newow-product.helpers.mjs'

const lineByStrategy = {
  trend: 'B',
  oscillation: 'HHV',
  main_rise: 'MA35',
}

for (const strategy of NEWOW_STRATEGIES) {
  for (const frequency of NEWOW_FREQUENCIES) {
    test(`${strategy} × ${frequency} owns an independent chart and reference lifecycle`, async ({ page }) => {
      expect(page.viewportSize()).toEqual({ width: 1440, height: 900 })
      const fixture = await installNewowProductFixtures(page)
      await page.goto(newowRoute(strategy, frequency))

      const workspace = page.locator('[data-detail-workspace="newow"]')
      const chart = page.getByTestId('newow-product-chart-stage')
      await expect(workspace).toHaveAttribute('data-strategy', strategy)
      await expect(workspace).toHaveAttribute('data-frequency', frequency)
      await expect(workspace).toHaveAttribute('data-chart-state', 'ready')
      await expect(chart).toHaveAttribute('data-strategy', strategy)
      await expect(chart).toHaveAttribute('data-frequency', frequency)
      await expect(chart.getByText(lineByStrategy[strategy], { exact: true }).first()).toBeVisible()
      expect(productRequests(fixture, 'reference')).toHaveLength(0)

      await page.getByRole('tab', { name: '参考历史与统计' }).click()
      await expect(page.getByTestId('newow-reference-summary')).toContainText('100')
      const summaryBefore = await page.getByTestId('newow-reference-summary').innerText()
      await page.getByTestId('newow-load-earlier').click()
      await expect.poll(() => productRequests(fixture, 'chart').length).toBe(2)
      expect(await page.getByTestId('newow-reference-summary').innerText()).toBe(summaryBefore)
      const older = productRequests(fixture, 'chart').at(-1).url.searchParams
      expect(older.get('chart_before')).toBe('chart-page-2')
      expect(older.has('performance_since')).toBe(false)
      expect(older.has('history_before')).toBe(false)
      assertNoUnexpectedRequests(fixture)
    })
  }
}

test('same-Bar CLEAR then BUILD actions remain separately locatable', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('oscillation', '1d'))
  const chart = page.getByTestId('newow-product-chart-stage')
  await expect(chart).toHaveAttribute('data-action-ids', /oscillation-1d-clear-same,oscillation-1d-build-same/)
  await page.getByRole('tab', { name: '参考历史与统计' }).click()
  await page.getByRole('button', { name: /定位参考记录 oscillation-1d-closed/ }).click()
  await expect(chart).toHaveAttribute('data-selected-signal-id', 'oscillation-1d-build-old')
  await page.getByRole('button', { name: /定位参考记录 oscillation-1d-open/ }).click()
  await expect(chart).toHaveAttribute('data-selected-signal-id', 'oscillation-1d-build-same')
  assertNoUnexpectedRequests(fixture)
})

test('reference pagination exposes OPEN, CLOSED, interrupted, negative and initial rows without inventing zero metrics', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await page.getByRole('tab', { name: '参考历史与统计' }).click()
  await expect(page.locator('tr[data-reference-category="open"]')).toBeVisible()
  await expect(page.locator('tr[data-reference-category="closed"]')).toBeVisible()
  await page.getByRole('button', { name: '加载更多参考历史' }).click()
  await expect(page.locator('tr[data-reference-category="interrupted"]')).toBeVisible()
  await expect(page.getByText('-10.0000%（中断浮动）')).toBeVisible()
  await expect(page.locator('tr[data-reference-initial="true"]')).toBeVisible()
  await expect(page).toHaveScreenshot('newow-desktop-reference.png', { maxDiffPixelRatio: 0.01 })
  expect(productRequests(fixture, 'reference').at(-1).url.searchParams.get('history_before')).toBe('reference-page-2')
  assertNoUnexpectedRequests(fixture)
})

test('exact locate loads an unloaded window and never falls back to nearest marker', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  await page.getByRole('tab', { name: '参考历史与统计' }).click()
  await page.getByRole('button', { name: '加载更多参考历史' }).click()
  await page.getByRole('button', { name: /定位参考记录 trend-1d-interrupted/ }).click()
  await expect(page.getByTestId('newow-product-chart-stage')).toHaveAttribute('data-selected-signal-id', 'historic-build')
  const locate = productRequests(fixture, 'chart').at(-1).url.searchParams
  expect(locate.get('from')).toBe('2026-01-05')
  expect(locate.has('performance_since')).toBe(false)
  assertNoUnexpectedRequests(fixture)
})

test('a snapshot conflict rebuilds once while busy and identity mismatch fail closed', async ({ page }) => {
  const conflict = await installNewowProductFixtures(page, { conflictOnce: 'trend:1d:reference' })
  await page.goto(newowRoute())
  await page.getByRole('tab', { name: '参考历史与统计' }).click()
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  expect(productRequests(conflict, 'reference')).toHaveLength(2)
  expect(productRequests(conflict, 'reference')[0].url.searchParams.get('snapshot_token')).toBeTruthy()
  expect(productRequests(conflict, 'reference')[1].url.searchParams.has('snapshot_token')).toBe(false)
  assertNoUnexpectedRequests(conflict)
})

test('429 is bounded and an identity mismatch clears stale facts', async ({ browser }) => {
  const busyContext = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const busyPage = await busyContext.newPage()
  const busy = await installNewowProductFixtures(busyPage, { busy: 'trend:1d:reference' })
  await busyPage.goto(newowRoute())
  await busyPage.getByRole('tab', { name: '参考历史与统计' }).click()
  await expect(busyPage.getByRole('tabpanel', { name: '参考历史与统计' })).toContainText('NEWOW_RESOURCE_BUSY')
  expect(productRequests(busy, 'reference')).toHaveLength(1)
  assertNoUnexpectedRequests(busy)
  await busyContext.close()

  const mismatchContext = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const mismatchPage = await mismatchContext.newPage()
  const mismatch = await installNewowProductFixtures(mismatchPage, { identityMismatch: 'trend:1d:chart' })
  await mismatchPage.goto(newowRoute())
  await expect(mismatchPage.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'input_conflict')
  await expect(mismatchPage.locator('.newow-product-workspace__notice')).toContainText('NEWOW_RESPONSE_INVALID')
  expect(productRequests(mismatch, 'chart')).toHaveLength(1)
  assertNoUnexpectedRequests(mismatch)
  await mismatchContext.close()
})

test('zero CLOSED summary renders missing metrics instead of zero percent', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page, { zeroClosed: true })
  await page.goto(newowRoute())
  await page.getByRole('tab', { name: '参考历史与统计' }).click()
  const summary = page.getByTestId('newow-reference-summary')
  await expect(summary).toContainText('暂无已完成参考交易；统计指标不是 0%。')
  await expect(summary).not.toContainText('0.00%')
  assertNoUnexpectedRequests(fixture)
})

test('auxiliary cache, applicability and disclosures remain section-local', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('trend', '1d'))
  for (const label of ['主力控盘', '涨跌动能', '主力照妖镜', '杯柄']) {
    await page.getByRole('button', { name: label, exact: true }).click()
    await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'ready')
  }
  await page.getByRole('button', { name: '主力照妖镜', exact: true }).click()
  await expect(page.getByText('仅供历史回看，会重绘；不进入主动作、Hint 或参考交易。')).toBeVisible()
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  expect(productRequests(fixture, 'auxiliary').filter((item) => item.url.searchParams.get('component') === 'main_force_control')).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})

test('explanation and comparator disclose multi-period facts, evidence gaps and synthetic terminals', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute('main_rise', '60m'))
  await page.getByRole('tab', { name: '解释与独立比较器' }).click()
  await expect(page.getByTestId('newow-explanation-panel')).toContainText('completed / strict-before')
  await expect(page.getByTestId('newow-explanation-panel')).toContainText('NEWOW_PRIVATE_SCORE_UNPROVEN')
  await expect(page.getByTestId('newow-explanation-panel')).toContainText('1w')
  await expect(page.getByTestId('newow-explanation-panel')).toContainText('1d')
  await expect(page.getByTestId('newow-explanation-panel')).toContainText('60m')
  await expect(page.getByTestId('newow-comparator-panel')).toContainText('理论平仓')
  expect(productRequests(fixture, 'explanation')).toHaveLength(1)
  expect(productRequests(fixture, 'comparator')).toHaveLength(1)
  assertNoUnexpectedRequests(fixture)
})

test('research tabs support keyboard focus and controls retain minimum target size', async ({ page }) => {
  const fixture = await installNewowProductFixtures(page)
  await page.goto(newowRoute())
  const reference = page.getByRole('tab', { name: '参考历史与统计' })
  await reference.focus()
  await reference.press('ArrowRight')
  await expect(page.getByRole('tab', { name: '解释与独立比较器' })).toBeFocused()
  const box = await page.getByRole('button', { name: '主力控盘', exact: true }).boundingBox()
  expect(box.height).toBeGreaterThanOrEqual(44)
  assertNoUnexpectedRequests(fixture)
})

test.describe('mobile', () => {
  test.use({ viewport: { width: 390, height: 844 } })
  test('starts at the real mobile viewport with scrollable reference content', async ({ page }) => {
    expect(page.viewportSize()).toEqual({ width: 390, height: 844 })
    const fixture = await installNewowProductFixtures(page)
    await page.goto(newowRoute('oscillation', '1d'))
    await page.getByRole('tab', { name: '参考历史与统计' }).click()
    const overflow = await page.locator('.newow-reference__table-wrap').evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth }))
    expect(overflow.scroll).toBeGreaterThan(overflow.client)
    await expect(page).toHaveScreenshot('newow-mobile-oscillation-reference.png', { maxDiffPixelRatio: 0.01 })
    assertNoUnexpectedRequests(fixture)
  })
})

test('records raw cold, warm, reuse, rebuild and long-history timings without fixed sleeps', async ({ page }, testInfo) => {
  const samples = []
  const fixture = await installNewowProductFixtures(page, { longHistory: true })
  const start = performance.now()
  await page.goto(newowRoute())
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  samples.push({ metric: 'cold_chart_visible_ms', value: performance.now() - start })
  samples.push({ metric: 'cold_chart_request_dispatch_ms', value: productRequests(fixture, 'chart')[0].startedAt - start })
  const beforeReference = performance.now()
  await page.getByRole('tab', { name: '参考历史与统计' }).click()
  await expect(page.getByTestId('newow-reference-summary')).toBeVisible()
  samples.push({ metric: 'warm_reference_visible_ms', value: performance.now() - beforeReference })
  samples.push({ metric: 'warm_reference_request_dispatch_ms', value: productRequests(fixture, 'reference')[0].startedAt - beforeReference })
  const beforeAux = performance.now()
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'ready')
  samples.push({ metric: 'cold_auxiliary_visible_ms', value: performance.now() - beforeAux })
  samples.push({ metric: 'cold_auxiliary_request_dispatch_ms', value: productRequests(fixture, 'auxiliary')[0].startedAt - beforeAux })
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  const reuse = performance.now()
  const auxiliaryRequestsBeforeReuse = productRequests(fixture, 'auxiliary').length
  await page.getByRole('button', { name: '主力控盘', exact: true }).click()
  await expect(page.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-auxiliary-state', 'ready')
  samples.push({ metric: 'auxiliary_cache_reuse_visible_ms', value: performance.now() - reuse })
  samples.push({ metric: 'auxiliary_cache_reuse_request_delta', value: productRequests(fixture, 'auxiliary').length - auxiliaryRequestsBeforeReuse })
  const beforeOlder = performance.now()
  await page.getByTestId('newow-load-earlier').click()
  await expect.poll(() => productRequests(fixture, 'chart').length).toBe(2)
  samples.push({ metric: 'long_history_prepend_ms', value: performance.now() - beforeOlder, initial_bars: 480, prepended_bars: 360 })
  samples.push({ metric: 'long_history_request_dispatch_ms', value: productRequests(fixture, 'chart')[1].startedAt - beforeOlder })

  const rebuildPage = await page.context().newPage()
  const rebuildFixture = await installNewowProductFixtures(rebuildPage, { conflictOnce: 'trend:1d:chart' })
  const rebuildStart = performance.now()
  await rebuildPage.goto(newowRoute())
  await expect(rebuildPage.locator('[data-detail-workspace="newow"]')).toHaveAttribute('data-chart-state', 'ready')
  samples.push({ metric: 'snapshot_rebuild_visible_ms', value: performance.now() - rebuildStart })
  samples.push({ metric: 'snapshot_rebuild_request_count', value: productRequests(rebuildFixture, 'chart').length })
  await rebuildPage.close()
  const environment = await page.evaluate(() => ({ userAgent: navigator.userAgent, hardwareConcurrency: navigator.hardwareConcurrency, viewport: [innerWidth, innerHeight] }))
  await testInfo.attach('newow-performance.json', { body: JSON.stringify({ samples, environment: { ...environment, node: process.version, platform: `${os.platform()} ${os.release()}`, cpu: os.cpus()[0]?.model } }, null, 2), contentType: 'application/json' })
  console.log(`NEWOW_PERFORMANCE ${JSON.stringify(samples)}`)
  assertNoUnexpectedRequests(fixture)
})
